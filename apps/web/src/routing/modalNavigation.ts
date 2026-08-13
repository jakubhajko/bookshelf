import { useLocation, type Location } from 'react-router'
import type { InteractionAttribution } from '../api/attribution'

/** Location `state` shape used by the book-detail modal-route pattern
 * (spec §12.7: "Desktop route-backed modal over prior page"). Storing the
 * page that was showing *before* `/books/:bookId` was pushed lets `App.tsx`
 * render `/books/:bookId` as a `Dialog` over that page instead of
 * navigating away from it — see `App.tsx` for the two-`<Routes>` setup. */
export interface ModalLocationState {
  backgroundLocation?: Location
  /** How this detail view was reached (rec-spec §4.3). Carried so an
   * action taken *on* the detail page still records the recommendation
   * that led there — rec-spec §4.3 asks for attribution to propagate into
   * a "recommendation-opened detail view", not just the card click.
   *
   * Location state is the right carrier precisely because it expires the
   * way attribution should: it belongs to this history entry, so it
   * survives back/forward to the same page and vanishes the moment the
   * reader navigates somewhere unrelated. Nothing has to remember to clear
   * it, which is how stale attribution normally happens.
   */
  attribution?: InteractionAttribution
}

/**
 * The page to return to when a route-backed modal closes. Not just
 * `location` itself — if the visitor is already inside a modal (e.g. they
 * clicked a similar-book card from within the detail modal), `location`
 * *is* the current modal's URL, so the background has to come from its own
 * state instead, keeping a chain of modal navigations collapsed onto the
 * one real page underneath rather than stacking.
 */
export function resolveBackgroundLocation(location: Location): Location {
  const state = location.state as ModalLocationState | null
  return state?.backgroundLocation ?? location
}

/**
 * The attribution this detail view was opened with, if any. Returns
 * `undefined` for a direct URL visit, a reload, or a bookmark — all of
 * which genuinely have no origin to report (ADR-0015).
 */
export function useOpenAttribution(): InteractionAttribution | undefined {
  const location = useLocation()
  const state = location.state as ModalLocationState | null
  return state?.attribution
}
