import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as recommendationsApi from '../api/recommendations'
import * as shelvesApi from '../api/shelves'
import { HomePage } from './Home'

const EMPTY_PAGE: recommendationsApi.RecommendationPage = {
  request_id: 'r1',
  surface: 'home',
  model_version: 'v1',
  items: [],
  next_cursor: null,
}

function renderHome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('HomePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([])
  })

  it('shows an empty state when the feed has no items', async () => {
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockResolvedValue(EMPTY_PAGE)

    renderHome()

    expect(await screen.findByText('Nothing to show yet.')).toBeInTheDocument()
  })

  it('shows a retry control when the feed fails to load', async () => {
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockRejectedValue(new Error('boom'))

    renderHome()

    expect(await screen.findByText("Couldn't load your feed.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('renders books returned by the feed', async () => {
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockResolvedValue({
      ...EMPTY_PAGE,
      items: [
        {
          book_id: 1,
          work_id: 'w1',
          title: 'A Great Book',
          primary_author_name: 'An Author',
          // Real key: a null one renders BookCover's title/author
          // placeholder tile, duplicating "A Great Book" as visible text
          // and making a plain getByText ambiguous against the real <h3>.
          cover_object_key: 'cover.jpg',
          rank: 1,
          score: null,
          reason_code: 'POPULAR_WITH_READERS',
          reason_text: 'Popular with readers',
        },
      ],
    })

    renderHome()

    expect(await screen.findByText('A Great Book')).toBeInTheDocument()
  })

  it('shows a subtle guidance message for a visitor with no shelves yet', async () => {
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockResolvedValue(EMPTY_PAGE)

    renderHome()

    expect(
      await screen.findByText(
        'Rate books or save them to shelves and your home feed will get sharper.',
      ),
    ).toBeInTheDocument()
  })

  it('hides the guidance message once the visitor has a shelf', async () => {
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([
      {
        id: 's1',
        name: 'To Read',
        description: null,
        book_count: 0,
        cover_object_keys: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ])
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockResolvedValue(EMPTY_PAGE)

    renderHome()

    await screen.findByText('Nothing to show yet.')
    expect(
      screen.queryByText('Rate books or save them to shelves and your home feed will get sharper.'),
    ).not.toBeInTheDocument()
    expect(screen.getByText('To Read')).toBeInTheDocument()
  })
})
