import type { Location } from 'react-router'

/** Location `state` shape used by the book-detail modal-route pattern
 * (spec §12.7: "Desktop route-backed modal over prior page"). Storing the
 * page that was showing *before* `/books/:bookId` was pushed lets `App.tsx`
 * render `/books/:bookId` as a `Dialog` over that page instead of
 * navigating away from it — see `App.tsx` for the two-`<Routes>` setup. */
export interface ModalLocationState {
  backgroundLocation?: Location
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
