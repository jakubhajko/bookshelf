import { Home, Library, Star } from 'lucide-react'
import type { ComponentType } from 'react'

export interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>
}

/** Left rail / bottom nav items (spec §12.2): "exactly Home, Shelves, Rated". */
export const navItems: NavItem[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/shelves', label: 'Shelves', icon: Library },
  { to: '/rated', label: 'Rated', icon: Star },
]
