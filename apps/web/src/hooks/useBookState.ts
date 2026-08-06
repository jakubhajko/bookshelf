import { type QueryClient, skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect } from 'react'
import * as booksApi from '../api/books'
import type { BookUserState } from '../api/books'
import { queryKeys } from '../api/queryKeys'
import type { RatedBookItem } from '../api/ratings'
import type { SearchResultItem } from '../api/search'
import { showToast } from '../toast/toastStore'

const NEUTRAL_STATE: BookUserState = { rating: null, not_interested: false, shelf_ids: [] }

/**
 * Reactive read of a book's rating/not-interested/shelf state, shared
 * between every surface that shows that book (cards, detail page) via one
 * TanStack Query cache entry (spec §12.11: no separate client store).
 *
 * Home-feed cards never fetch this directly — spec §5.5 eligibility
 * guarantees every book `GET /recommendations/home` returns starts Neutral
 * and unsaved, so `NEUTRAL_STATE` is a correct default, not a
 * placeholder-while-loading. The detail page's `GET /books/{id}` seeds the
 * authoritative value for a specific book; the mutations below update it
 * from whichever surface (card or detail) the user acted on.
 */
export function useBookState(bookId: number): BookUserState {
  const { data } = useQuery({
    queryKey: queryKeys.books.state(bookId),
    queryFn: skipToken,
    initialData: NEUTRAL_STATE,
  })
  return data ?? NEUTRAL_STATE
}

/** `GET /books/{id}` (spec §9.2) plus seeding the shared per-book state
 * cache from its `user_state` — the detail page is the one place that
 * fetches the *authoritative* state, so every card/control showing this
 * book benefits from a detail view, not just this one component. `useQuery`
 * has no `onSuccess` in TanStack Query v5, hence the effect. */
export function useBookDetailQuery(bookId: number) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.books.detail(bookId),
    queryFn: () => booksApi.getBookDetail(bookId),
  })

  useEffect(() => {
    if (query.data) {
      seedBookState(queryClient, bookId, query.data.user_state)
    }
  }, [query.data, queryClient, bookId])

  return query
}

export function seedBookState(
  queryClient: QueryClient,
  bookId: number,
  state: BookUserState,
): void {
  queryClient.setQueryData(queryKeys.books.state(bookId), state)
}

function mergeBookState(queryClient: QueryClient, bookId: number, patch: Partial<BookUserState>) {
  queryClient.setQueryData<BookUserState>(queryKeys.books.state(bookId), (current) => ({
    ...(current ?? NEUTRAL_STATE),
    ...patch,
  }))
}

interface RollbackContext {
  previous: BookUserState | undefined
}

/**
 * Synchronous on purpose. This used to `await queryClient.cancelQueries(...)`
 * first — the standard TanStack Query optimistic-update recipe, meant to
 * stop an in-flight *refetch* of the same key from overwriting the
 * optimistic value with stale data. But `useBookState`'s query is
 * `queryFn: skipToken` (a pure cache mirror with no fetcher of its own,
 * seeded/mutated only by calls in this file) — there is never anything
 * fetching against this key for `cancelQueries` to cancel, so the `await`
 * was dead weight that did one real, harmful thing: it delayed the
 * optimistic write by a tick. A native checkbox/radio flips its own DOM
 * state the instant it's clicked; React then re-renders the *controlled*
 * `checked` prop from whatever this cache currently holds. With the write
 * delayed past that first render, the old (pre-click) value could win the
 * race and snap the control back before the real write landed — a visible
 * flicker for a real user, and, caught live via the Phase 9 E2E test
 * clicking two shelf checkboxes back to back, an outright lost click when
 * Playwright's post-click verification sampled state during that window.
 * Applying the patch synchronously, in the same tick as the click, closes
 * the window entirely.
 */
function optimisticallyPatch(
  queryClient: QueryClient,
  bookId: number,
  patch: Partial<BookUserState>,
): RollbackContext {
  const previous = queryClient.getQueryData<BookUserState>(queryKeys.books.state(bookId))
  mergeBookState(queryClient, bookId, patch)
  return { previous }
}

/** Reverts the optimistic patch and explains why (spec §15: "mutation
 * toasts", "optimistic rollback") — without this, a failed mutation would
 * revert the UI silently, leaving no clue what happened or that anything
 * needs retrying. */
function rollback(
  queryClient: QueryClient,
  bookId: number,
  context: RollbackContext | undefined,
  message: string,
) {
  if (context) {
    queryClient.setQueryData(queryKeys.books.state(bookId), context.previous)
  }
  showToast(message, 'error')
}

/** Spec §5.3: setting a rating atomically clears Not Interested. */
export function useSetRatingMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rating: number) => booksApi.setRating(bookId, rating),
    onMutate: (rating) => optimisticallyPatch(queryClient, bookId, { rating, not_interested: false }),
    onError: (_error, _rating, context) =>
      rollback(queryClient, bookId, context, "Couldn't save your rating."),
    onSuccess: (result) => mergeBookState(queryClient, bookId, result),
  })
}

export function useRemoveRatingMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.removeRating(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { rating: null }),
    onError: (_error, _vars, context) =>
      rollback(queryClient, bookId, context, "Couldn't remove your rating."),
  })
}

/** Spec §5.3: setting Not Interested atomically clears any rating. */
export function useSetNotInterestedMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.setNotInterested(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { not_interested: true, rating: null }),
    onError: (_error, _vars, context) =>
      rollback(queryClient, bookId, context, "Couldn't mark this book Not Interested."),
    onSuccess: (result) => mergeBookState(queryClient, bookId, result),
  })
}

export function useRemoveNotInterestedMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.removeNotInterested(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { not_interested: false }),
    onError: (_error, _vars, context) =>
      rollback(queryClient, bookId, context, "Couldn't undo Not Interested."),
  })
}

/** Full-replace sync (spec §9.2) — always sent with the complete desired
 * shelf-id set, matching what `api/books.ts::syncBookShelves` sends.
 *
 * Deliberately no `onSuccess` cache write (unlike the rating/not-interested
 * mutations above): the popover lets a visitor toggle several checkboxes in
 * quick succession, firing one mutation per click, each capturing "the full
 * desired set" from the *closure* at click time. `onMutate`'s optimistic
 * patch already applies that exact value, so on success there's nothing new
 * to write — and writing it anyway is actively wrong once two syncs for the
 * same book overlap in flight: an earlier click's now-stale server response
 * can arrive *after* a later click's optimistic update and clobber it back
 * to the earlier, incomplete set. Confirmed live (not theoretical) via the
 * Phase 9 E2E test checking two shelf boxes back to back — the second
 * checkbox visibly reverted to unchecked once the first request's response
 * landed. `onError`'s rollback has the same class of hazard on the failure
 * path (rarer — needs an actual request failure, not just a slow one) and
 * is left as a known, documented gap rather than solved here.
 */
export function useSyncShelvesMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (shelfIds: string[]) => booksApi.syncBookShelves(bookId, shelfIds),
    onMutate: (shelfIds) => optimisticallyPatch(queryClient, bookId, { shelf_ids: shelfIds }),
    onError: (_error, _vars, context) =>
      rollback(queryClient, bookId, context, "Couldn't update shelves for this book."),
  })
}

/**
 * Search results carry each book's *authoritative* `user_state` (spec
 * §9.6: "search keeps prior user states visible") — seed it into the
 * shared cache so `BookCard`'s badges/shelf-selector are correct
 * immediately, not just after a detail-page visit corrects them.
 * `useLayoutEffect`, not `useEffect`: this must run before paint, or an
 * already-rated result would flash as unrated for one frame first.
 */
export function useSeedBookStatesFromSearchResults(items: readonly SearchResultItem[]) {
  const queryClient = useQueryClient()
  useLayoutEffect(() => {
    for (const item of items) {
      seedBookState(queryClient, item.book_id, item.user_state)
    }
  }, [items, queryClient])
}

/**
 * Rated-books results only carry the rating itself — spec §9.4's
 * `RatedBookItem` has no `shelf_ids` (a batched lookup a plain ratings
 * listing doesn't need) — merges rather than replaces so it never
 * clobbers a `shelf_ids` some other surface already seeded correctly.
 * `not_interested: false` is always safe to assert: a rated book is never
 * Not Interested by construction (spec §5.2's mutual exclusion).
 */
export function useSeedRatingsIntoBookState(items: readonly RatedBookItem[]) {
  const queryClient = useQueryClient()
  useLayoutEffect(() => {
    for (const item of items) {
      mergeBookState(queryClient, item.book_id, { rating: item.rating, not_interested: false })
    }
  }, [items, queryClient])
}
