import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SurfaceAttribution } from '../api/attribution'
import * as booksApi from '../api/books'
import type { RecommendationBookItem } from '../api/recommendations'
import { BookCard } from './BookCard'

/**
 * Recommender Phase R1: recommendation attribution survives the journey
 * from card to action (rec-spec §4.3, ADR-0015).
 *
 * The interesting assertions here are about *what gets sent*, not what
 * renders — the whole point of R1 is that the evidence reaching the
 * database is complete and honest.
 */

const REQUEST_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

const BOOK: RecommendationBookItem = {
  book_id: 42,
  work_id: 'w42',
  title: 'The Attributed Test',
  primary_author_name: 'Jane Author',
  cover_object_key: 'cover.jpg',
  rank: 7,
  score: null,
  reason_code: 'POPULAR_WITH_READERS',
  reason_text: 'Popular with readers',
}

const HOME_ATTRIBUTION: SurfaceAttribution = {
  surface: 'home',
  recommendation_request_id: REQUEST_ID,
}

function renderCard(attribution?: SurfaceAttribution) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BookCard book={BOOK} attribution={attribution} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('BookCard attribution', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('records an intentional open with the surface, request id and rank', async () => {
    const user = userEvent.setup()
    const recordOpen = vi.spyOn(booksApi, 'recordBookOpened').mockImplementation(() => {})

    renderCard(HOME_ATTRIBUTION)
    await user.click(screen.getByRole('button', { name: /The Attributed Test/ }))

    expect(recordOpen).toHaveBeenCalledWith(42, {
      surface: 'home',
      recommendation_request_id: REQUEST_ID,
      rank_position: 7,
    })
  })

  it('records an open with no attribution when the surface knows nothing', () => {
    // ADR-0015: unattributed is a complete record, not a degraded one.
    const recordOpen = vi.spyOn(booksApi, 'recordBookOpened').mockImplementation(() => {})

    renderCard()
    screen.getByRole('button', { name: /The Attributed Test/ }).click()

    expect(recordOpen).toHaveBeenCalledWith(42, { rank_position: 7 })
  })

  it('attaches attribution to a save made from the card', async () => {
    sessionStorage.setItem('bookshelf:last-used-shelf-id', 's1')
    const user = userEvent.setup()
    const sync = vi.spyOn(booksApi, 'syncBookShelves').mockResolvedValue(['s1'])

    renderCard(HOME_ATTRIBUTION)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(sync).toHaveBeenCalledWith(42, ['s1'], {
        surface: 'home',
        recommendation_request_id: REQUEST_ID,
        rank_position: 7,
      }),
    )
  })

  it('carries the attribution into the detail view it navigates to', async () => {
    // rec-spec §4.3 asks attribution to reach a "recommendation-opened
    // detail view", not just the card click — so a rating set on the
    // detail page is still credited to the recommendation that led there.
    const user = userEvent.setup()
    vi.spyOn(booksApi, 'recordBookOpened').mockImplementation(() => {})

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let capturedState: unknown = null
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <BookCard book={BOOK} attribution={HOME_ATTRIBUTION} />
          <StateProbe onState={(state) => (capturedState = state)} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await user.click(screen.getByRole('button', { name: /The Attributed Test/ }))

    await waitFor(() =>
      expect(capturedState).toMatchObject({
        attribution: {
          surface: 'home',
          recommendation_request_id: REQUEST_ID,
          rank_position: 7,
        },
      }),
    )
  })
})

/** Reads the router's current location state so the test can assert on
 * what `BookCard` pushed, without rendering the whole detail route. */
function StateProbe({ onState }: { onState: (state: unknown) => void }) {
  const state = useLocation().state
  onState(state)
  return null
}
