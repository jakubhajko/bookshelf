import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'

function LensLink({
  to,
  active,
  children,
}: {
  to: string
  active: boolean
  children: ReactNode
}) {
  return (
    <Link
      to={to}
      aria-current={active ? 'page' : undefined}
      className={`shrink-0 border-b-2 pb-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        active
          ? 'border-accent font-semibold text-text'
          : 'border-transparent font-medium text-text-muted hover:text-text focus-visible:text-text'
      }`}
    >
      {children}
    </Link>
  )
}

/**
 * "All" + the visitor's shelves, as feed lenses (spec §12.4's "For You +
 * user shelves"; the first entry reads All here). Shared by Home and each
 * shelf's lens view so the row stays put while switching between them —
 * picking a shelf swaps the feed underneath rather than navigating away
 * into a separate section.
 *
 * Real `<Link>`s rather than buttons calling `navigate`: these *are*
 * navigations, so middle-click, cmd-click and "open in new tab" should all
 * work, and the active one carries `aria-current="page"`.
 *
 * Styled as plain labels with an underlined active entry rather than
 * filled chips: the row is navigation, not a set of controls competing
 * with the covers below it, and it shares the underline treatment with
 * `ShelfDetailLayout`'s heading.
 */
export function ShelfLensRow({ activeShelfId }: { activeShelfId?: string }) {
  const { data: shelves = [] } = useQuery({
    queryKey: queryKeys.shelves.list,
    queryFn: shelvesApi.listShelves,
    staleTime: 30_000,
  })

  // A lone "All" with nothing to switch between is noise, so the row stays
  // hidden until the visitor has at least one shelf.
  if (shelves.length === 0) return null

  return (
    <nav
      aria-label="Feed lens"
      className="flex gap-6 overflow-x-auto px-4 pt-1 pb-1 text-sm sm:px-6"
    >
      <LensLink to="/" active={!activeShelfId}>
        All
      </LensLink>
      {shelves.map((shelf) => (
        <LensLink
          key={shelf.id}
          to={`/shelves/${shelf.id}/discover`}
          active={shelf.id === activeShelfId}
        >
          {shelf.name}
        </LensLink>
      ))}
    </nav>
  )
}
