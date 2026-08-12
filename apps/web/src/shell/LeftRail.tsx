import { Link, NavLink } from 'react-router'
import { BrandLogo } from '../components/BrandLogo'
import { navItems } from './navigation'

/** Fixed left rail, desktop only (spec §12.2) — mobile uses BottomNav
 * instead. The wordmark sits at the top of the rail rather than in the top
 * bar: that puts it in the page's actual top-left corner, and keeps the
 * search field starting at the same x as the first grid column instead of
 * being pushed right by a logo slot. The rail is sized to fit the wordmark
 * legibly, which is what sets its width. */
export function LeftRail() {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-y-0 left-0 z-20 hidden w-28 flex-col items-center border-r border-border bg-sidebar py-3 md:flex"
    >
      {/* Inside the nav landmark rather than beside it: pulled out, the
        * wordmark was the one piece of the page belonging to no landmark
        * at all, which axe flags (`region`). It links home because that's
        * what people expect of a wordmark, and it adds no destination spec
        * §12.2 doesn't already list — Home is one of its exactly-three. */}
      <Link
        to="/"
        aria-label="BookShelf, home"
        className="mb-4 flex h-11 items-center rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {/* Same width as the nav items below it, so the rail has one left
          * and right edge rather than two. */}
        <BrandLogo className="w-24" />
      </Link>

      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `mt-1 flex w-24 flex-col items-center gap-1 rounded-md py-2 text-xs transition ${
              isActive
                ? 'bg-surface text-text'
                : 'text-text-muted hover:bg-surface hover:text-text'
            }`
          }
        >
          <Icon aria-hidden className="h-5 w-5" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
