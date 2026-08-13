import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { SurfaceAttribution } from '../api/attribution'
import { queryKeys } from '../api/queryKeys'
import * as recommendationsApi from '../api/recommendations'
import * as shelvesApi from '../api/shelves'
import { BookMasonryGrid, BookMasonrySkeleton } from '../components/BookMasonryGrid'
import { ShelfLensRow } from '../components/ShelfLensRow'
import { useInfiniteScrollSentinel } from '../hooks/useInfiniteScrollSentinel'
import { useScrollRestoration } from '../hooks/useScrollRestoration'

const GUIDANCE_DISMISSED_KEY = 'bookshelf:home-guidance-dismissed'

/** Spec §12.4: "New users receive fallback feed and a subtle guidance
 * message. No forced onboarding." — dismissible (never blocks the feed)
 * and shown while the visitor has no shelves yet, a cheap proxy for "new"
 * that doesn't need a dedicated ratings fetch just to render a hint. */
function GuidanceBanner({ hasShelves }: { hasShelves: boolean }) {
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(GUIDANCE_DISMISSED_KEY) === '1',
  )

  if (dismissed || hasShelves) return null

  function dismiss() {
    localStorage.setItem(GUIDANCE_DISMISSED_KEY, '1')
    setDismissed(true)
  }

  return (
    <div className="mx-4 mt-4 flex items-start justify-between gap-4 rounded-md border border-border bg-surface px-4 py-3 text-sm text-text-muted sm:mx-6">
      <p>Rate books or save them to shelves and your home feed will get sharper.</p>
      <button
        type="button"
        onClick={dismiss}
        className="shrink-0 text-text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Dismiss
      </button>
    </div>
  )
}

/** Masonry home feed (spec §12.4). Cursor-paginated via `useInfiniteQuery`
 * against the same persisted batch (ADR-0007) — an `IntersectionObserver`
 * sentinel triggers the next page, never a scroll-position calculation. */
export function HomePage() {
  useScrollRestoration('home')
  const { data: shelves = [] } = useQuery({
    queryKey: queryKeys.shelves.list,
    queryFn: shelvesApi.listShelves,
    staleTime: 30_000,
  })

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: queryKeys.recommendations.home,
      queryFn: ({ pageParam }) => recommendationsApi.getHomeRecommendations({ cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor,
    })

  const sentinelRef = useInfiniteScrollSentinel(
    () => void fetchNextPage(),
    !hasNextPage || isFetchingNextPage,
  )

  const items = data?.pages.flatMap((page) => page.items) ?? []

  // Every page of this feed reads the *same* persisted batch (ADR-0007) —
  // a cursor encodes the request id, so later pages come back carrying the
  // first one's. One request id therefore attributes every item here, and
  // each card contributes its own `rank` (rec-spec §4.3).
  const attribution: SurfaceAttribution = {
    surface: 'home',
    recommendation_request_id: data?.pages[0]?.request_id,
  }

  return (
    <div className="pb-10">
      <ShelfLensRow />
      <GuidanceBanner hasShelves={shelves.length > 0} />

      <div className="px-4 pt-4 sm:px-6">
        {isLoading && <BookMasonrySkeleton />}

        {isError && !isLoading && (
          <div className="py-16 text-center">
            <p className="text-sm text-text-muted">Couldn&apos;t load your feed.</p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Retry
            </button>
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div className="py-16 text-center">
            <p className="text-sm text-text-muted">Nothing to show yet.</p>
          </div>
        )}

        {!isLoading && items.length > 0 && (
          <BookMasonryGrid items={items} attribution={attribution} />
        )}

        <div ref={sentinelRef} className="h-1" />
        {isFetchingNextPage && (
          <p className="py-4 text-center text-sm text-text-muted">Loading more…</p>
        )}
      </div>
    </div>
  )
}
