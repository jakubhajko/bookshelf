import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as ratingsApi from '../api/ratings'
import { RatedPage } from './Rated'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RatedPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RatedPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('defaults to the recent sort and loads ratings', async () => {
    vi.spyOn(ratingsApi, 'listRatings').mockResolvedValue({ items: [], next_cursor: null })
    renderPage()

    await waitFor(() =>
      expect(ratingsApi.listRatings).toHaveBeenCalledWith(
        expect.objectContaining({ sort: 'recent', minRating: null, maxRating: null, genre: null }),
      ),
    )
    expect(screen.getByRole('button', { name: 'Recent' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('re-fetches with the chosen sort', async () => {
    const user = userEvent.setup()
    vi.spyOn(ratingsApi, 'listRatings').mockResolvedValue({ items: [], next_cursor: null })
    renderPage()
    await waitFor(() => expect(ratingsApi.listRatings).toHaveBeenCalled())

    await user.click(screen.getByRole('button', { name: 'Highest' }))

    await waitFor(() =>
      expect(ratingsApi.listRatings).toHaveBeenCalledWith(
        expect.objectContaining({ sort: 'highest' }),
      ),
    )
  })

  it('re-fetches with a genre filter', async () => {
    const user = userEvent.setup()
    vi.spyOn(ratingsApi, 'listRatings').mockResolvedValue({ items: [], next_cursor: null })
    renderPage()
    await waitFor(() => expect(ratingsApi.listRatings).toHaveBeenCalled())

    await user.type(screen.getByLabelText('Genre'), 'fantasy')

    await waitFor(() =>
      expect(ratingsApi.listRatings).toHaveBeenCalledWith(
        expect.objectContaining({ genre: 'fantasy' }),
      ),
    )
  })

  it('shows an empty state when nothing matches the filters', async () => {
    vi.spyOn(ratingsApi, 'listRatings').mockResolvedValue({ items: [], next_cursor: null })
    renderPage()

    expect(
      await screen.findByText('No rated books match these filters yet.'),
    ).toBeInTheDocument()
  })

  it('renders rated books', async () => {
    vi.spyOn(ratingsApi, 'listRatings').mockResolvedValue({
      items: [
        {
          book_id: 1,
          work_id: 'w1',
          title: 'A Rated Book',
          primary_author_name: 'An Author',
          cover_object_key: 'cover.jpg',
          rating: 4,
          rated_at: '2026-01-01T00:00:00Z',
        },
      ],
      next_cursor: null,
    })
    renderPage()

    expect(await screen.findByText('A Rated Book')).toBeInTheDocument()
  })
})
