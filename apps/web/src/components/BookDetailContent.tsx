import { useQuery } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import * as recommendationsApi from '../api/recommendations'
import { queryKeys } from '../api/queryKeys'
import {
  useBookDetailQuery,
  useBookState,
  useRemoveNotInterestedMutation,
  useRemoveRatingMutation,
  useSetNotInterestedMutation,
  useSetRatingMutation,
} from '../hooks/useBookState'
import { BookCover } from './BookCover'
import { BookMasonryGrid } from './BookMasonryGrid'
import { NotInterestedControl } from './NotInterestedControl'
import { RatingStars } from './RatingStars'
import { ShelfSelectorPopover } from './ShelfSelectorPopover'

function MetadataFacts({
  publicationYear,
  numPages,
  publisher,
  languageCode,
  format,
}: {
  publicationYear: number | null
  numPages: number | null
  publisher: string | null
  languageCode: string | null
  format: string | null
}) {
  const facts = [
    publicationYear ? String(publicationYear) : null,
    format,
    numPages ? `${numPages} pages` : null,
    publisher,
    languageCode ? languageCode.toUpperCase() : null,
  ].filter((fact): fact is string => Boolean(fact))

  if (facts.length === 0) return null

  return (
    <p className="mt-2 text-sm text-text-muted">
      {facts.map((fact, index) => (
        <span key={fact}>
          {index > 0 && ' · '}
          {fact}
        </span>
      ))}
    </p>
  )
}

function SimilarBooksSection({ bookId }: { bookId: number }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.recommendations.similar(bookId),
    queryFn: () => recommendationsApi.getSimilarRecommendations(bookId, { limit: 12 }),
  })

  return (
    <section className="mt-10">
      <h2 className="text-base font-semibold text-text">Similar books</h2>
      {isLoading && <p className="mt-3 text-sm text-text-muted">Loading…</p>}
      {isError && <p className="mt-3 text-sm text-text-muted">Couldn&apos;t load similar books.</p>}
      {data && data.items.length === 0 && (
        <p className="mt-3 text-sm text-text-muted">No similar books yet.</p>
      )}
      {data && data.items.length > 0 && (
        <div className="mt-3">
          {/* Capped: this strip lives inside the detail dialog, roughly a
            * third of the viewport wide, so the full-width tier's column
            * count would shrink these covers to thumbnails. */}
          <BookMasonryGrid items={data.items} maxColumns={4} />
        </div>
      )}
    </section>
  )
}

/**
 * Book detail content (spec §12.7) — shared between the full-page route and
 * the route-backed modal, which differ only in surrounding chrome (see
 * `routes/BookDetail.tsx` / `routes/BookDetailModal.tsx`).
 */
export function BookDetailContent({ bookId }: { bookId: number }) {
  const { data: book, isLoading, isError, refetch } = useBookDetailQuery(bookId)
  const userState = useBookState(bookId)
  const setRating = useSetRatingMutation(bookId)
  const removeRating = useRemoveRatingMutation(bookId)
  const setNotInterested = useSetNotInterestedMutation(bookId)
  const removeNotInterested = useRemoveNotInterestedMutation(bookId)

  if (isLoading) {
    return (
      <div className="animate-pulse p-6">
        <div className="aspect-[2/3] w-40 rounded-md bg-surface" />
        <div className="mt-4 h-6 w-2/3 rounded bg-surface" />
        <div className="mt-2 h-4 w-1/3 rounded bg-surface" />
      </div>
    )
  }

  if (isError || !book) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-text-muted">Couldn&apos;t load this book.</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
        >
          Retry
        </button>
      </div>
    )
  }

  const authorNames = book.authors.length > 0 ? book.authors.map((a) => a.name).join(', ') : book.primary_author_name

  return (
    <div className="p-6">
      <div className="flex flex-col gap-6 sm:flex-row">
        <div className="w-40 shrink-0">
          <BookCover
            objectKey={book.cover_object_key}
            title={book.title}
            author={book.primary_author_name}
          />
        </div>

        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-text">{book.title}</h1>
          {authorNames && <p className="mt-1 text-sm text-text-muted">{authorNames}</p>}

          <MetadataFacts
            publicationYear={book.publication_year}
            numPages={book.num_pages}
            publisher={book.publisher}
            languageCode={book.language_code}
            format={book.format}
          />

          {book.genres.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {book.genres.map((genre) => (
                <span
                  key={genre}
                  className="rounded-full border border-border px-2.5 py-0.5 text-xs text-text-muted"
                >
                  {genre}
                </span>
              ))}
            </div>
          )}

          {book.average_rating !== null && (
            <p className="mt-3 flex items-center gap-1.5 text-sm text-text-muted">
              <Star aria-hidden fill="currentColor" className="h-4 w-4" />
              {book.average_rating.toFixed(2)}
              {book.ratings_count !== null && ` (${book.ratings_count.toLocaleString()} ratings)`}
            </p>
          )}

          {book.description && (
            <p className="mt-4 whitespace-pre-line text-sm text-text">{book.description}</p>
          )}

          <div className="mt-6 flex flex-wrap items-start gap-6">
            <div>
              <span className="mb-1 block text-xs font-medium text-text-muted">Your rating</span>
              <RatingStars
                value={userState.rating}
                onRate={(value) => setRating.mutate(value)}
                onRemove={() => removeRating.mutate()}
                disabled={setRating.isPending || removeRating.isPending}
              />
            </div>

            <div>
              <span className="mb-1 block text-xs font-medium text-text-muted">Shelves</span>
              <ShelfSelectorPopover bookId={bookId} variant="full" />
            </div>

            <div>
              <span className="mb-1 block text-xs font-medium text-text-muted">&nbsp;</span>
              <NotInterestedControl
                notInterested={userState.not_interested}
                hasRating={userState.rating !== null}
                onSetNotInterested={() => setNotInterested.mutate()}
                onRemoveNotInterested={() => removeNotInterested.mutate()}
                disabled={setNotInterested.isPending || removeNotInterested.isPending}
              />
            </div>
          </div>
        </div>
      </div>

      <SimilarBooksSection bookId={bookId} />
    </div>
  )
}
