import { useInfiniteQuery } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'
import { BookMasonryGrid, BookMasonrySkeleton } from '../components/BookMasonryGrid'
import { useInfiniteScrollSentinel } from '../hooks/useInfiniteScrollSentinel'

/** Shelf detail's "Books" tab (spec §12.8): every book currently on the
 * shelf, cursor-paginated. Removing a book happens through the same
 * `ShelfSelectorPopover` every card already has (uncheck this shelf) —
 * no separate quick-remove affordance here. */
export function ShelfBooksPage() {
  const { shelfId } = useParams()

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: queryKeys.shelves.books(shelfId ?? ''),
      queryFn: ({ pageParam }) => shelvesApi.listShelfBooks(shelfId ?? '', { cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor ?? null,
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
        <p className="text-sm text-text-muted">Couldn&apos;t load this shelf&apos;s books.</p>
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
    return <p className="py-16 text-center text-sm text-text-muted">No books on this shelf yet.</p>
  }

  return (
    <div>
      <BookMasonryGrid items={items} attribution={{ surface: 'shelf_books' }} />
      <div ref={sentinelRef} className="h-1" />
      {isFetchingNextPage && (
        <p className="py-4 text-center text-sm text-text-muted">Loading more…</p>
      )}
    </div>
  )
}
