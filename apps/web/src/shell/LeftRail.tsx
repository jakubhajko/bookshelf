import { NavLink } from 'react-router'
import { navItems } from './navigation'

/** Fixed narrow left rail, desktop only (spec §12.2) — mobile uses BottomNav instead. */
export function LeftRail() {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-y-0 left-0 z-20 hidden w-20 flex-col items-center gap-1 border-r border-border bg-sidebar py-4 md:flex"
    >
      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `flex w-16 flex-col items-center gap-1 rounded-md py-2 text-xs transition ${
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
