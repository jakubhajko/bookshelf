import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from './api/auth'
import type { BookDetail } from './api/books'
import * as booksApi from './api/books'
import type { RecommendationPage } from './api/recommendations'
import * as recommendationsApi from './api/recommendations'
import * as shelvesApi from './api/shelves'
import { AppRoutes } from './App'
import { AuthProvider } from './auth/AuthProvider'

const EMPTY_PAGE: RecommendationPage = {
  request_id: 'r1',
  surface: 'home',
  model_version: 'v1',
  items: [],
  next_cursor: null,
}

const BOOK: BookDetail = {
  id: 1,
  work_id: 'w1',
  title: 'The Detail Book',
  title_without_series: null,
  description: null,
  has_description: false,
  primary_author_name: 'Test Author',
  authors: [],
  top_genre: null,
  genres: [],
  series_data: null,
  average_rating: null,
  ratings_count: null,
  text_reviews_count: null,
  num_pages: null,
  publication_year: null,
  publisher: null,
  language_code: null,
  format: null,
  is_ebook: null,
  cover_object_key: null,
  has_cover: false,
  user_state: { rating: null, not_interested: false, shelf_ids: [] },
}

function renderAt(initialEntry: { pathname: string; state?: unknown }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('book detail routing (spec §12.7: route-backed modal vs. direct page)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([])
    vi.spyOn(recommendationsApi, 'getHomeRecommendations').mockResolvedValue(EMPTY_PAGE)
    vi.spyOn(recommendationsApi, 'getSimilarRecommendations').mockResolvedValue(EMPTY_PAGE)
    vi.spyOn(booksApi, 'getBookDetail').mockResolvedValue(BOOK)
  })

  it('renders the full page, no dialog, when navigated to directly', async () => {
    renderAt({ pathname: '/books/1' })

    expect(
      await screen.findByRole('heading', { name: 'The Detail Book', level: 1 }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders a modal over the background page when opened in-app', async () => {
    renderAt({
      pathname: '/books/1',
      state: {
        backgroundLocation: { pathname: '/', search: '', hash: '', state: null, key: 'default' },
      },
    })

    const dialog = await screen.findByRole('dialog')
    expect(
      await within(dialog).findByRole('heading', { name: 'The Detail Book', level: 1 }),
    ).toBeInTheDocument()

    // The background page (Home) is still mounted underneath the modal.
    await waitFor(() => expect(screen.getByText('Nothing to show yet.')).toBeInTheDocument())
  })
})
