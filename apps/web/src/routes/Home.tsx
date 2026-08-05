import { ComingSoon } from '../components/ComingSoon'

/** Phase 1's health-check smoke page lived here; replaced now that real
 * auth/shell exist to prove connectivity. The masonry home feed (spec
 * §12.4) replaces this placeholder in Phase 7. */
export function HomePage() {
  return (
    <ComingSoon
      title="Your home feed"
      description="The masonry home feed, shelf-lens rows, and infinite scroll land in Phase 7."
    />
  )
}
