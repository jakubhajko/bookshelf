import { type QueryClient, skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import * as booksApi from '../api/books'
import type { BookUserState } from '../api/books'
import { queryKeys } from '../api/queryKeys'

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

async function optimisticallyPatch(
  queryClient: QueryClient,
  bookId: number,
  patch: Partial<BookUserState>,
): Promise<RollbackContext> {
  await queryClient.cancelQueries({ queryKey: queryKeys.books.state(bookId) })
  const previous = queryClient.getQueryData<BookUserState>(queryKeys.books.state(bookId))
  mergeBookState(queryClient, bookId, patch)
  return { previous }
}

function rollback(queryClient: QueryClient, bookId: number, context: RollbackContext | undefined) {
  if (context) {
    queryClient.setQueryData(queryKeys.books.state(bookId), context.previous)
  }
}

/** Spec §5.3: setting a rating atomically clears Not Interested. */
export function useSetRatingMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (rating: number) => booksApi.setRating(bookId, rating),
    onMutate: (rating) => optimisticallyPatch(queryClient, bookId, { rating, not_interested: false }),
    onError: (_error, _rating, context) => rollback(queryClient, bookId, context),
    onSuccess: (result) => mergeBookState(queryClient, bookId, result),
  })
}

export function useRemoveRatingMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.removeRating(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { rating: null }),
    onError: (_error, _vars, context) => rollback(queryClient, bookId, context),
  })
}

/** Spec §5.3: setting Not Interested atomically clears any rating. */
export function useSetNotInterestedMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.setNotInterested(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { not_interested: true, rating: null }),
    onError: (_error, _vars, context) => rollback(queryClient, bookId, context),
    onSuccess: (result) => mergeBookState(queryClient, bookId, result),
  })
}

export function useRemoveNotInterestedMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => booksApi.removeNotInterested(bookId),
    onMutate: () => optimisticallyPatch(queryClient, bookId, { not_interested: false }),
    onError: (_error, _vars, context) => rollback(queryClient, bookId, context),
  })
}

/** Full-replace sync (spec §9.2) — always sent with the complete desired
 * shelf-id set, matching what `api/books.ts::syncBookShelves` sends. */
export function useSyncShelvesMutation(bookId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (shelfIds: string[]) => booksApi.syncBookShelves(bookId, shelfIds),
    onMutate: (shelfIds) => optimisticallyPatch(queryClient, bookId, { shelf_ids: shelfIds }),
    onError: (_error, _vars, context) => rollback(queryClient, bookId, context),
    onSuccess: (shelfIds) => mergeBookState(queryClient, bookId, { shelf_ids: shelfIds }),
  })
}
