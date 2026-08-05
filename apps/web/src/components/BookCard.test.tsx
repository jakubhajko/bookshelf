import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as booksApi from '../api/books'
import type { RecommendationBookItem } from '../api/recommendations'
import { BookCard } from './BookCard'

const BOOK: RecommendationBookItem = {
  book_id: 42,
  work_id: 'w42',
  title: 'The Optimistic Test',
  primary_author_name: 'Jane Author',
  // A real key so BookCover renders an <img> (alt text only) instead of
  // its title/author placeholder tile — jsdom never fires the <img>'s
  // load/error events on its own, so it stays in that state throughout.
  // A null key here would make "The Optimistic Test" appear twice (the
  // placeholder tile duplicates the title/author as visible text) and
  // make the text-content assertions below ambiguous.
  cover_object_key: 'cover.jpg',
  rank: 1,
  score: null,
  reason_code: 'POPULAR_WITH_READERS',
  reason_text: 'Popular with readers',
}

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BookCard book={BOOK} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('BookCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('shows the title and author', () => {
    renderCard()

    expect(screen.getByText('The Optimistic Test')).toBeInTheDocument()
    expect(screen.getByText('Jane Author')).toBeInTheDocument()
  })

  it('starts unsaved (spec §5.5: home feed books are never already saved)', () => {
    renderCard()

    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('optimistically flips to Saved, then rolls back if the save request fails', async () => {
    sessionStorage.setItem('bookshelf:last-used-shelf-id', 's1')
    const user = userEvent.setup()
    let rejectSync!: (reason: unknown) => void
    vi.spyOn(booksApi, 'syncBookShelves').mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectSync = reject
      }),
    )

    renderCard()
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Optimistic: the badge flips before the request has settled at all.
    expect(await screen.findByRole('button', { name: 'Saved' })).toBeInTheDocument()

    rejectSync(new Error('network error'))

    // Rollback: reverts once the request is known to have failed.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument())
  })
})
