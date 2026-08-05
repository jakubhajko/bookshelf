import { useInfiniteQuery } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as recommendationsApi from '../api/recommendations'
import { BookMasonryGrid, BookMasonrySkeleton } from '../components/BookMasonryGrid'
import { useInfiniteScrollSentinel } from '../hooks/useInfiniteScrollSentinel'

/** Shelf detail's "Discover" tab (spec §12.8): this shelf as a
 * recommendation lens (`GET /recommendations/shelves/{id}`, spec §5.5 —
 * excludes this shelf's own contents but allows books already on *other*
 * shelves). Cards here default their quick-Save to this shelf, not the
 * session's last-used one (spec §12.8's "defaults Save to current
 * shelf"), via `BookMasonryGrid`'s `defaultShelfId`. */
export function ShelfDiscoverPage() {
  const { shelfId } = useParams()

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: queryKeys.recommendations.shelf(shelfId ?? ''),
      queryFn: ({ pageParam }) =>
        recommendationsApi.getShelfRecommendations(shelfId ?? '', { cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor,
      enabled: Boolean(shelfId),
    })

  const sentinelRef = useInfiniteScrollSentinel(
    () => void fetchNextPage(),
    !hasNextPage || isFetchingNextPage,
  )

  const items = data?.pages.flatMap((page) => page.items) ?? []

  if (isLoading) return <BookMasonrySkeleton />

  if (isError) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm text-text-muted">Couldn&apos;t load discover results.</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
        >
          Retry
        </button>
      </div>
    )
  }

  if (items.length === 0) {
    return <p className="py-16 text-center text-sm text-text-muted">Nothing to discover yet.</p>
  }

  return (
    <div>
      <BookMasonryGrid items={items} defaultShelfId={shelfId} />
      <div ref={sentinelRef} className="h-1" />
      {isFetchingNextPage && (
        <p className="py-4 text-center text-sm text-text-muted">Loading more…</p>
      )}
    </div>
  )
}
