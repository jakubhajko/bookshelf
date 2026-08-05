import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type RatedBookItem = components['schemas']['RatedBookItem']
export type RatingsSort = components['schemas']['RatingsSort']
export type RatedBooksPage = components['schemas']['Page_RatedBookItem_']

interface ListRatingsParams {
  sort?: RatingsSort
  minRating?: number | null
  maxRating?: number | null
  genre?: string | null
  cursor?: string | null
  limit?: number
}

export async function listRatings(params: ListRatingsParams = {}): Promise<RatedBooksPage> {
  const result = await apiClient.GET('/api/v1/me/ratings', {
    params: {
      query: {
        sort: params.sort,
        min_rating: params.minRating ?? undefined,
        max_rating: params.maxRating ?? undefined,
        genre: params.genre ?? undefined,
        cursor: params.cursor ?? undefined,
        limit: params.limit,
      },
    },
  })
  return unwrap(result)
}
