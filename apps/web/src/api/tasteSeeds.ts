import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type TasteSeedItem = components['schemas']['TasteSeedItem']
export type TasteSeedsResponse = components['schemas']['TasteSeedsResponse']
export type TasteSeedSource = components['schemas']['TasteSeedSource']

export async function listTasteSeeds(): Promise<TasteSeedsResponse> {
  const result = await apiClient.GET('/api/v1/me/taste-seeds')
  return unwrap(result)
}

/**
 * Replace the reader's taste seeds with `bookIds` (rec-spec §6).
 *
 * A full replace rather than a delta, matching the endpoint: onboarding is
 * a multi-select confirmed once, so sending the complete desired set makes
 * a retry after a dropped connection idempotent instead of doubling up.
 *
 * An empty list is valid and means "clear them" — rec-spec §6 sets no
 * minimum, and a reader who deselects everything has expressed something,
 * not made a mistake to guard against.
 */
export async function syncTasteSeeds(
  bookIds: number[],
  source: TasteSeedSource = 'onboarding',
): Promise<TasteSeedsResponse> {
  const result = await apiClient.PUT('/api/v1/me/taste-seeds', {
    body: { book_ids: bookIds, source },
  })
  return unwrap(result)
}
