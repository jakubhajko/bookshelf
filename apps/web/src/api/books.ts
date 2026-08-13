import { type InteractionAttribution, withBrowsingSession } from './attribution'
import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type BookDetail = components['schemas']['BookDetail']
export type BookUserState = components['schemas']['BookUserState']
export type PreferenceState = components['schemas']['PreferenceState']

export async function getBookDetail(bookId: number): Promise<BookDetail> {
  const result = await apiClient.GET('/api/v1/books/{book_id}', {
    params: { path: { book_id: bookId } },
  })
  return unwrap(result)
}

/**
 * Records an intentional open of a book's detail view (rec-spec §4.2).
 *
 * Fire-and-forget on purpose: the caller navigates immediately without
 * awaiting this, and a rejection here is swallowed rather than surfaced.
 * An analytics write must never cost the reader a navigation, and there is
 * nothing useful to tell them if it fails. `GET /books/{id}` stays pure —
 * this is the *only* thing that records an open (ADR-0015).
 */
export function recordBookOpened(bookId: number, attribution?: InteractionAttribution): void {
  void apiClient
    .POST('/api/v1/books/{book_id}/opened', {
      params: { path: { book_id: bookId } },
      body: { attribution: withBrowsingSession(attribution) },
    })
    .catch(() => {
      /* best-effort: never block or surface */
    })
}

/** Public half-star value (0.5-5.0, spec §9.2) — the backend converts to
 * the internal 1-10 integer scale, the frontend never does. */
export async function setRating(
  bookId: number,
  rating: number,
  attribution?: InteractionAttribution,
): Promise<PreferenceState> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/rating', {
    params: { path: { book_id: bookId } },
    body: { rating, attribution: withBrowsingSession(attribution) },
  })
  return unwrap(result)
}

export async function removeRating(bookId: number): Promise<void> {
  const result = await apiClient.DELETE('/api/v1/books/{book_id}/rating', {
    params: { path: { book_id: bookId } },
  })
  unwrap(result)
}

export async function setNotInterested(
  bookId: number,
  attribution?: InteractionAttribution,
): Promise<PreferenceState> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/not-interested', {
    params: { path: { book_id: bookId } },
    body: { attribution: withBrowsingSession(attribution) },
  })
  return unwrap(result)
}

export async function removeNotInterested(bookId: number): Promise<void> {
  const result = await apiClient.DELETE('/api/v1/books/{book_id}/not-interested', {
    params: { path: { book_id: bookId } },
  })
  unwrap(result)
}

/** Atomically replaces this book's shelf memberships (spec §9.2) — always
 * sent as the full desired set, never an add/remove delta. Attribution
 * stamps `shelf_books.source_surface` on newly-added memberships as well
 * as the save event (rec-spec §4.3). */
export async function syncBookShelves(
  bookId: number,
  shelfIds: string[],
  attribution?: InteractionAttribution,
): Promise<string[]> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/shelves', {
    params: { path: { book_id: bookId } },
    body: { shelf_ids: shelfIds, attribution: withBrowsingSession(attribution) },
  })
  return unwrap(result).shelf_ids
}
