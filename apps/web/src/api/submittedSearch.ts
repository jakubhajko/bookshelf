import { useSyncExternalStore } from 'react'
import { getBrowsingSessionId } from './browsingSession'
import { apiClient } from './client'

/**
 * Carries the id of the most recently *submitted* search from the search
 * bar to the results page, so opening a result can be attributed to the
 * search that produced it (rec-spec §4.4).
 *
 * Why a module-level store rather than router state: recording the search
 * is a network round trip, and the reader must not wait for it before
 * navigating. So `SearchBar` fires the write and navigates in the same
 * tick; the id lands here whenever it arrives, and the results page picks
 * it up reactively if it does. If the reader clicks a result before the
 * write completes, the open is simply unattributed — ADR-0015 prefers a
 * missing field to an invented one.
 *
 * Deliberately *not* persisted. A reload or a shared `?q=` link is not a
 * submitted search, and attributing one to a search from an earlier
 * sitting would be a fabricated causal link. Same `useSyncExternalStore`
 * shape as `hooks/useLastUsedShelf.ts`.
 */

interface SubmittedSearch {
  query: string
  searchQueryId: string
}

let current: SubmittedSearch | null = null
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/**
 * Records a committed search and remembers its id for the results page.
 *
 * Called only from the submit path — pressing Enter, or picking a
 * recent-search chip. The debounced suggestions dropdown never calls it,
 * which is the whole point of rec-spec §4.4: the log holds searches a
 * reader meant, not every prefix they typed on the way.
 *
 * Clears any previous id immediately so a new search can never be
 * attributed to the last one while its own write is still in flight.
 */
export function recordSubmittedSearch(query: string): void {
  const trimmed = query.trim()
  if (!trimmed) return

  current = null
  emit()

  void apiClient
    .POST('/api/v1/search/queries', {
      body: {
        query_text: trimmed,
        session_id: getBrowsingSessionId(),
        surface: 'search',
      },
    })
    .then((result) => {
      if (!result.data) return
      current = { query: trimmed, searchQueryId: result.data.id }
      emit()
    })
    .catch(() => {
      /* best-effort: a failed analytics write must not break search */
    })
}

function getSnapshot(): SubmittedSearch | null {
  return current
}

/** The search-query id for `query`, if this session submitted exactly that
 * search and the write has landed. Matching on the query text keeps a
 * stale id from being attached to a different search's results. */
export function useSubmittedSearchQueryId(query: string): string | undefined {
  const submitted = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  return submitted && submitted.query === query.trim() ? submitted.searchQueryId : undefined
}

/** Test seam only. */
export function resetSubmittedSearch(): void {
  current = null
  emit()
}
