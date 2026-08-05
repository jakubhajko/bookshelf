import { AvatarMenu } from './AvatarMenu'
import { SearchBar } from './SearchBar'

/** Sticky top bar: large search field + avatar menu (spec §12.2). */
export function TopBar() {
  return (
    <header className="sticky top-0 z-10 flex items-center gap-4 border-b border-border bg-topbar px-4 py-3 md:pl-24">
      <SearchBar />
      <AvatarMenu />
    </header>
  )
}
