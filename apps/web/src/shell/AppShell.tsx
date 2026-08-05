import { Outlet } from 'react-router'
import { BottomNav } from './BottomNav'
import { LeftRail } from './LeftRail'
import { TopBar } from './TopBar'

/** Desktop: fixed left rail + sticky top bar + scrollable content (spec
 * §12.2). Mobile: bottom nav instead of the rail. Only rendered for
 * authenticated routes — see RequireAuth in the router. */
export function AppShell() {
  return (
    <div className="min-h-screen bg-background text-text">
      <LeftRail />
      <div className="flex flex-col md:pl-20">
        <TopBar />
        <main className="flex-1 pb-16 md:pb-0">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  )
}
