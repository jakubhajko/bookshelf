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

/** Public half-star value (0.5-5.0, spec §9.2) — the backend converts to
 * the internal 1-10 integer scale, the frontend never does. */
export async function setRating(bookId: number, rating: number): Promise<PreferenceState> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/rating', {
    params: { path: { book_id: bookId } },
    body: { rating },
  })
  return unwrap(result)
}

export async function removeRating(bookId: number): Promise<void> {
  const result = await apiClient.DELETE('/api/v1/books/{book_id}/rating', {
    params: { path: { book_id: bookId } },
  })
  unwrap(result)
}

export async function setNotInterested(bookId: number): Promise<PreferenceState> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/not-interested', {
    params: { path: { book_id: bookId } },
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
 * sent as the full desired set, never an add/remove delta. */
export async function syncBookShelves(bookId: number, shelfIds: string[]): Promise<string[]> {
  const result = await apiClient.PUT('/api/v1/books/{book_id}/shelves', {
    params: { path: { book_id: bookId } },
    body: { shelf_ids: shelfIds },
  })
  return unwrap(result).shelf_ids
}
