import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type Shelf = components['schemas']['ShelfPublic']

export async function listShelves(): Promise<Shelf[]> {
  const result = await apiClient.GET('/api/v1/shelves')
  return unwrap(result)
}

export async function createShelf(name: string): Promise<Shelf> {
  const result = await apiClient.POST('/api/v1/shelves', { body: { name } })
  return unwrap(result)
}
