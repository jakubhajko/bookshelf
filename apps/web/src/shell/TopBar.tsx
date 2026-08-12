import { AvatarMenu } from './AvatarMenu'
import { SearchBar } from './SearchBar'

/** Sticky top bar: full-width search field + avatar menu (spec §12.2).
 *
 * No bottom divider and no fill of its own — it sits at the page
 * background and is separated from the feed by spacing alone. Horizontal
 * padding matches the feed's own `px-4 sm:px-6` so the search field lines
 * up with the first grid column instead of being indented past it. */
export function TopBar() {
  return (
    <header className="sticky top-0 z-10 flex items-center gap-3 bg-topbar px-4 py-3 sm:px-6">
      <SearchBar />
      <AvatarMenu />
    </header>
  )
}
