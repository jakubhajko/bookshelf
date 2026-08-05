import { NavLink } from 'react-router'
import { navItems } from './navigation'

/** Mobile bottom navigation (spec §12.2) — same three destinations as LeftRail. */
export function BottomNav() {
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-sidebar md:hidden"
    >
      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-1 py-2 text-xs ${
              isActive ? 'text-text' : 'text-text-muted'
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
