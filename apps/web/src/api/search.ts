import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type SearchResultItem = components['schemas']['SearchResultItem']
export type SearchResultsResponse = components['schemas']['SearchResultsResponse']

interface SearchParams {
  limit?: number
  cursor?: string | null
}

export async function searchBooks(
  query: string,
  params: SearchParams = {},
): Promise<SearchResultsResponse> {
  const result = await apiClient.GET('/api/v1/search/books', {
    params: { query: { q: query, limit: params.limit, cursor: params.cursor ?? undefined } },
  })
  return unwrap(result)
}
