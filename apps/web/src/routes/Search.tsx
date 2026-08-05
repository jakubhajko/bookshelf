import { useInfiniteQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as searchApi from '../api/search'
import { BookMasonryGrid, BookMasonrySkeleton } from '../components/BookMasonryGrid'
import { useSeedBookStatesFromSearchResults } from '../hooks/useBookState'
import { useInfiniteScrollSentinel } from '../hooks/useInfiniteScrollSentinel'

/** Masonry search results with user-state badges (spec §12.10) — the
 * query lives in the URL (`?q=`), so a shared/reloaded link reproduces
 * the same results. Suggestions/query-entry live in `shell/SearchBar.tsx`;
 * this page only renders what a submitted query found. */
export function SearchPage() {
  const [searchParams] = useSearchParams()
  const query = (searchParams.get('q') ?? '').trim()

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: queryKeys.search.results(query),
      queryFn: ({ pageParam }) => searchApi.searchBooks(query, { cursor: pageParam }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor,
      enabled: query.length > 0,
    })

  const sentinelRef = useInfiniteScrollSentinel(
    () => void fetchNextPage(),
    !hasNextPage || isFetchingNextPage,
  )

  const items = data?.pages.flatMap((page) => page.items) ?? []
  useSeedBookStatesFromSearchResults(items)

  return (
    <div className="p-4 sm:p-6">
      <h1 className="text-xl font-semibold text-text">
        {query ? (
          <>
            Results for &ldquo;{query}&rdquo;
          </>
        ) : (
          'Search'
        )}
      </h1>

      <div className="mt-6">
        {query.length === 0 && (
          <p className="py-16 text-center text-sm text-text-muted">
            Search for books or authors above.
          </p>
        )}

        {query.length > 0 && isLoading && <BookMasonrySkeleton />}

        {query.length > 0 && isError && !isLoading && (
          <div className="py-16 text-center">
            <p className="text-sm text-text-muted">Couldn&apos;t load search results.</p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Retry
            </button>
          </div>
        )}

        {query.length > 0 && !isLoading && !isError && items.length === 0 && (
          <p className="py-16 text-center text-sm text-text-muted">
            No books found for &ldquo;{query}&rdquo;.
          </p>
        )}

        {!isLoading && items.length > 0 && <BookMasonryGrid items={items} />}

        <div ref={sentinelRef} className="h-1" />
        {isFetchingNextPage && (
          <p className="py-4 text-center text-sm text-text-muted">Loading more…</p>
        )}
      </div>
    </div>
  )
}
