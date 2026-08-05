import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type RecommendationBookItem = components['schemas']['RecommendationBookItem']
export type RecommendationPage = components['schemas']['RecommendationPageResponse']

interface PageParams {
  limit?: number
  cursor?: string | null
  /** Book ids already rendered this browsing session (spec §5.5's "already
   * returned in the current feed session"), joined server-side into the
   * `exclude` query param — see `recommendations/api.py::_parse_exclude`. */
  exclude?: readonly number[]
}

function toQuery({ limit, cursor, exclude }: PageParams) {
  return {
    limit,
    cursor: cursor ?? undefined,
    exclude: exclude && exclude.length > 0 ? exclude.join(',') : undefined,
  }
}

export async function getHomeRecommendations(params: PageParams = {}): Promise<RecommendationPage> {
  const result = await apiClient.GET('/api/v1/recommendations/home', {
    params: { query: toQuery(params) },
  })
  return unwrap(result)
}

export async function getSimilarRecommendations(
  bookId: number,
  params: PageParams = {},
): Promise<RecommendationPage> {
  const result = await apiClient.GET('/api/v1/recommendations/books/{book_id}/similar', {
    params: { path: { book_id: bookId }, query: toQuery(params) },
  })
  return unwrap(result)
}
