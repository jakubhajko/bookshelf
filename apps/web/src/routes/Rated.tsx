import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { queryKeys } from '../api/queryKeys'
import * as ratingsApi from '../api/ratings'
import type { RatingsSort } from '../api/ratings'
import { BookMasonryGrid, BookMasonrySkeleton } from '../components/BookMasonryGrid'
import { useSeedRatingsIntoBookState } from '../hooks/useBookState'
import { useInfiniteScrollSentinel } from '../hooks/useInfiniteScrollSentinel'

const SORT_OPTIONS: { value: RatingsSort; label: string }[] = [
  { value: 'recent', label: 'Recent' },
  { value: 'highest', label: 'Highest' },
  { value: 'lowest', label: 'Lowest' },
  { value: 'title', label: 'Title' },
  { value: 'author', label: 'Author' },
]

const RATING_STEPS = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/** Grid of rated books, sort + rating-range/genre filters (spec §12.9). */
export function RatedPage() {
  const [sort, setSort] = useState<RatingsSort>('recent')
  const [minRating, setMinRating] = useState<number | null>(null)
  const [maxRating, setMaxRating] = useState<number | null>(null)
  const [genre, setGenre] = useState('')
  const appliedGenre = genre.trim() || null

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useInfiniteQuery({
      queryKey: queryKeys.ratings.list({ sort, minRating, maxRating, genre: appliedGenre }),
      queryFn: ({ pageParam }) =>
        ratingsApi.listRatings({
          sort,
          minRating,
          maxRating,
          genre: appliedGenre,
          cursor: pageParam,
        }),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_cursor ?? null,
    })

  const sentinelRef = useInfiniteScrollSentinel(
    () => void fetchNextPage(),
    !hasNextPage || isFetchingNextPage,
  )

  const items = data?.pages.flatMap((page) => page.items) ?? []
  useSeedRatingsIntoBookState(items)

  return (
    <div className="p-4 sm:p-6">
      <h1 className="text-xl font-semibold text-text">Rated books</h1>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <fieldset>
          <legend className="mb-1 block text-xs font-medium text-text-muted">Sort</legend>
          <div className="flex gap-1">
            {SORT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setSort(option.value)}
                aria-pressed={sort === option.value}
                className={`rounded-full px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-accent ${
                  sort === option.value
                    ? 'bg-accent text-accent-text'
                    : 'border border-border bg-surface text-text hover:bg-surface-hover'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div>
          <label htmlFor="rated-min-rating" className="mb-1 block text-xs font-medium text-text-muted">
            Min rating
          </label>
          <select
            id="rated-min-rating"
            value={minRating ?? ''}
            onChange={(event) => setMinRating(event.target.value ? Number(event.target.value) : null)}
            className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="">Any</option>
            {RATING_STEPS.map((step) => (
              <option key={step} value={step}>
                {step}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="rated-max-rating" className="mb-1 block text-xs font-medium text-text-muted">
            Max rating
          </label>
          <select
            id="rated-max-rating"
            value={maxRating ?? ''}
            onChange={(event) => setMaxRating(event.target.value ? Number(event.target.value) : null)}
            className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="">Any</option>
            {RATING_STEPS.map((step) => (
              <option key={step} value={step}>
                {step}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="rated-genre" className="mb-1 block text-xs font-medium text-text-muted">
            Genre
          </label>
          <input
            id="rated-genre"
            type="text"
            value={genre}
            onChange={(event) => setGenre(event.target.value)}
            placeholder="e.g. fantasy"
            className="w-32 rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>
      </div>

      <div className="mt-6">
        {isLoading && <BookMasonrySkeleton />}

        {isError && !isLoading && (
          <div className="py-16 text-center">
            <p className="text-sm text-text-muted">Couldn&apos;t load your rated books.</p>
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
          <p className="py-16 text-center text-sm text-text-muted">
            No rated books match these filters yet.
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
