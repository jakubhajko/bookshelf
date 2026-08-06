import { ErrorBoundary } from 'react-error-boundary'
import { Outlet, useLocation } from 'react-router'
import { RouteErrorFallback } from '../components/ErrorFallback'
import { BottomNav } from './BottomNav'
import { LeftRail } from './LeftRail'
import { TopBar } from './TopBar'

/** Desktop: fixed left rail + sticky top bar + scrollable content (spec
 * §12.2). Mobile: bottom nav instead of the rail. Only rendered for
 * authenticated routes — see RequireAuth in the router.
 *
 * The routed content is wrapped in its own error boundary (spec §15:
 * "route errors") — a crash in, say, Search shouldn't take down
 * navigation along with it. `resetKeys={[pathname]}` clears a stuck error
 * automatically the moment the visitor navigates to a *different* route,
 * without needing them to find and click "Try again" first. */
export function AppShell() {
  const { pathname } = useLocation()

  return (
    <div className="min-h-screen bg-background text-text">
      <LeftRail />
      <div className="flex flex-col md:pl-20">
        <TopBar />
        <main className="flex-1 pb-16 md:pb-0">
          <ErrorBoundary FallbackComponent={RouteErrorFallback} resetKeys={[pathname]}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <BottomNav />
    </div>
  )
}
