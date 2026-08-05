import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, KeyRound, LogOut, User } from 'lucide-react'
import { useNavigate } from 'react-router'
import { useAuth } from '../auth/AuthContext'

const itemClass =
  'flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-text outline-none data-[highlighted]:bg-surface-hover'

/** Profile menu (spec §12.2): username, account, change password, logout.
 * Radix's DropdownMenu gives focus trap/Escape/keyboard nav for free
 * (ADR-0008: accessible headless primitives, not hand-rolled widgets). */
export function AvatarMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  if (!user) return null

  async function handleLogout() {
    await logout()
    await navigate('/login', { replace: true })
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={`Account menu for ${user.username}`}
          className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <span
            aria-hidden="true"
            className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-text"
          >
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <span className="max-w-24 truncate">{user.username}</span>
          <ChevronDown aria-hidden="true" className="h-4 w-4 text-text-muted" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="min-w-48 rounded-md border border-border bg-surface p-1 shadow-lg"
        >
          <DropdownMenu.Label className="truncate px-2 py-1.5 text-xs text-text-muted">
            {user.username}
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <DropdownMenu.Item onSelect={() => navigate('/account')} className={itemClass}>
            <User aria-hidden="true" className="h-4 w-4" />
            Account
          </DropdownMenu.Item>

          <DropdownMenu.Item onSelect={() => navigate('/account')} className={itemClass}>
            <KeyRound aria-hidden="true" className="h-4 w-4" />
            Change password
          </DropdownMenu.Item>

          <DropdownMenu.Separator className="my-1 h-px bg-border" />

          <DropdownMenu.Item onSelect={handleLogout} className={itemClass}>
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Log out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
