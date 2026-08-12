import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { coverUrl } from '../api/covers'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'
import { ShelfLensRow } from '../components/ShelfLensRow'
import { useScrollRestoration } from '../hooks/useScrollRestoration'
import { NotFoundPage } from './NotFound'
import { ShelfDiscoverFeed } from './ShelfDiscover'

const PREVIEW_COVER_LIMIT = 6

/**
 * One shelf used as a lens on the feed (spec §12.8's shelf discovery).
 *
 * Reached by picking a shelf in the lens row, and deliberately *not* a
 * section you navigate away into: the row stays exactly where it was, the
 * shelf's own header replaces the "All" feed's top, and the shelf-scoped
 * recommendations run underneath. The shelf's actual contents are one
 * click away via "View shelf" (`/shelves/:shelfId/books`) rather than
 * being the landing state — picking a shelf here is an act of browsing,
 * and the books already on it are the one thing the visitor has seen.
 *
 * This replaced a Books/Discover tab pair on the shelf page, which put
 * both behind an extra navigation and made discovery the less obvious
 * half of a shelf.
 */
export function ShelfLensPage() {
  const { shelfId } = useParams()
  useScrollRestoration(`shelf-lens-${shelfId ?? ''}`)

  const {
    data: shelf,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.shelves.detail(shelfId ?? ''),
    queryFn: () => shelvesApi.getShelf(shelfId ?? ''),
    enabled: Boolean(shelfId),
  })

  if (!shelfId) return <NotFoundPage />

  // The lens row renders above every state, including the failed one, so
  // switching lenses stays possible when one shelf won't load.
  return (
    <div className="pb-10">
      <ShelfLensRow activeShelfId={shelfId} />

      {isLoading && <p className="px-4 py-16 text-sm text-text-muted sm:px-6">Loading…</p>}

      {(isError || (!isLoading && !shelf)) && (
        <div className="py-16 text-center">
          <p className="text-sm text-text-muted">Couldn&apos;t load this shelf.</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
          >
            Retry
          </button>
        </div>
      )}

      {shelf && (
        <>
          <header className="flex items-start justify-between gap-6 px-4 pt-6 pb-8 sm:px-6">
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold text-text">{shelf.name}</h1>
              {shelf.description && (
                <p className="mt-1 text-sm text-text-muted">{shelf.description}</p>
              )}
              <p className="mt-1 text-sm text-text-muted">
                {shelf.book_count} {shelf.book_count === 1 ? 'book' : 'books'}
              </p>
              <Link
                to={`/shelves/${shelfId}/books`}
                className="mt-4 inline-flex h-9 items-center rounded-full bg-surface px-4 text-sm font-semibold text-text transition-colors hover:bg-surface-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                View shelf
              </Link>
            </div>

            {/* Decorative (empty `alt`) — the covers repeat what "View
              * shelf" already leads to, and naming six books here would
              * bury the heading and the button under them in a screen
              * reader. Hidden on narrow viewports, where the header would
              * otherwise push the feed off the first screen entirely. */}
            {shelf.cover_object_keys.length > 0 && (
              <ul className="hidden shrink-0 gap-2 md:flex">
                {shelf.cover_object_keys.slice(0, PREVIEW_COVER_LIMIT).map((key) => (
                  <li key={key}>
                    <img
                      src={coverUrl(key) ?? undefined}
                      alt=""
                      loading="lazy"
                      className="h-28 w-20 rounded-md bg-surface object-cover"
                    />
                  </li>
                ))}
              </ul>
            )}
          </header>

          <div className="px-4 sm:px-6">
            <h2 className="mb-4 text-sm font-semibold text-text-muted">
              More like {shelf.name}
            </h2>
            <ShelfDiscoverFeed shelfId={shelfId} />
          </div>
        </>
      )}
    </div>
  )
}
