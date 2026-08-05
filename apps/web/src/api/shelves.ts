import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type Shelf = components['schemas']['ShelfPublic']
export type ShelfBookItem = components['schemas']['ShelfBookItem']
export type ShelfBooksPage = components['schemas']['Page_ShelfBookItem_']

export async function listShelves(): Promise<Shelf[]> {
  const result = await apiClient.GET('/api/v1/shelves')
  return unwrap(result)
}

export async function createShelf(name: string): Promise<Shelf> {
  const result = await apiClient.POST('/api/v1/shelves', { body: { name } })
  return unwrap(result)
}

export async function getShelf(shelfId: string): Promise<Shelf> {
  const result = await apiClient.GET('/api/v1/shelves/{shelf_id}', {
    params: { path: { shelf_id: shelfId } },
  })
  return unwrap(result)
}

/** PATCH semantics (spec §5.4): only fields actually passed change. */
export async function updateShelf(
  shelfId: string,
  updates: { name?: string; description?: string | null },
): Promise<Shelf> {
  const result = await apiClient.PATCH('/api/v1/shelves/{shelf_id}', {
    params: { path: { shelf_id: shelfId } },
    body: updates,
  })
  return unwrap(result)
}

export async function deleteShelf(shelfId: string): Promise<void> {
  const result = await apiClient.DELETE('/api/v1/shelves/{shelf_id}', {
    params: { path: { shelf_id: shelfId } },
  })
  unwrap(result)
}

export async function listShelfBooks(
  shelfId: string,
  params: { cursor?: string | null; limit?: number } = {},
): Promise<ShelfBooksPage> {
  const result = await apiClient.GET('/api/v1/shelves/{shelf_id}/books', {
    params: {
      path: { shelf_id: shelfId },
      query: { cursor: params.cursor ?? undefined, limit: params.limit },
    },
  })
  return unwrap(result)
}
