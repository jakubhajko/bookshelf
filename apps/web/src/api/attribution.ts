import { getBrowsingSessionId } from './browsingSession'
import type { components } from './generated/schema'

/**
 * Where an action came from (rec-spec §4.3, ADR-0015). The generated type,
 * not a hand-written mirror of it — the backend's shared
 * `InteractionAttribution` is the single definition, and this stays in
 * lockstep with it through `make generate-api-client`.
 */
export type InteractionAttribution = components['schemas']['InteractionAttribution']
export type InteractionSurface = components['schemas']['InteractionSurface']

/**
 * What a surface knows *before* it knows which card was acted on. Rank is
 * per-item, so it's supplied separately by whatever renders the item —
 * keeping it out of here means no caller has to build a fresh attribution
 * object per card.
 */
export type SurfaceAttribution = Omit<InteractionAttribution, 'rank_position' | 'session_id'>

/**
 * Stamps the current browsing session onto an attribution at send time.
 *
 * Session id is attached *here* rather than by each surface, for two
 * reasons: reading it is what keeps the session alive (see
 * `browsingSession.ts`), so it has to happen at the moment of the action,
 * not when a component rendered; and no call site can then forget it.
 *
 * Returns `undefined` for a completely empty attribution so the request
 * body omits the field entirely rather than sending an object full of
 * nulls — ADR-0015: absent means "origin unknown", and that should look
 * absent on the wire.
 */
export function withBrowsingSession(
  attribution?: InteractionAttribution,
): InteractionAttribution | undefined {
  const merged: InteractionAttribution = {
    ...attribution,
    session_id: getBrowsingSessionId(),
  }
  return merged
}

/** Combines a surface's shared context with one item's rank. */
export function forRank(
  surface: SurfaceAttribution | undefined,
  rank: number | undefined,
): InteractionAttribution | undefined {
  if (!surface && rank === undefined) return undefined
  return { ...surface, ...(rank === undefined ? {} : { rank_position: rank }) }
}
