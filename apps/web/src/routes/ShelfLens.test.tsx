import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as recommendationsApi from '../api/recommendations'
import * as shelvesApi from '../api/shelves'
import type { Shelf } from '../api/shelves'
import { ShelfLensPage } from './ShelfLens'

const NOW = '2026-01-01T00:00:00Z'
const SHELF: Shelf = {
  id: 's1',
  name: 'Sci-Fi',
  description: null,
  book_count: 3,
  cover_object_keys: [],
  created_at: NOW,
  updated_at: NOW,
}
const OTHER_SHELF: Shelf = { ...SHELF, id: 's2', name: 'Cookbooks', book_count: 1 }

const EMPTY_PAGE: recommendationsApi.RecommendationPage = {
  request_id: 'r1',
  surface: 'shelf',
  model_version: 'v1',
  items: [],
  next_cursor: null,
}

function renderLens() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/shelves/s1/discover']}>
        <Routes>
          <Route path="/shelves/:shelfId/discover" element={<ShelfLensPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ShelfLensPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([SHELF, OTHER_SHELF])
    vi.spyOn(shelvesApi, 'getShelf').mockResolvedValue(SHELF)
    vi.spyOn(recommendationsApi, 'getShelfRecommendations').mockResolvedValue({
      ...EMPTY_PAGE,
      items: [
        {
          book_id: 1,
          work_id: 'w1',
          title: 'A Recommended Book',
          primary_author_name: 'An Author',
          cover_object_key: 'cover.jpg',
          rank: 1,
          score: null,
          reason_code: 'POPULAR_WITH_READERS',
          reason_text: 'Popular with readers',
        },
      ],
    })
  })

  it('keeps the lens row in place, with this shelf marked as the current one', async () => {
    renderLens()

    const current = await screen.findByRole('link', { name: 'Sci-Fi' })
    expect(current).toHaveAttribute('aria-current', 'page')
    // Switching lens — including back to the unfiltered feed — stays one
    // click away rather than requiring a trip back to Home.
    expect(screen.getByRole('link', { name: 'All' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Cookbooks' })).toBeInTheDocument()
  })

  it('shows the shelf header with a way into the shelf itself', async () => {
    renderLens()

    expect(await screen.findByRole('heading', { level: 1, name: 'Sci-Fi' })).toBeInTheDocument()
    expect(screen.getByText('3 books')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View shelf' })).toHaveAttribute(
      'href',
      '/shelves/s1/books',
    )
  })

  it('renders the shelf-scoped recommendations underneath the header', async () => {
    renderLens()

    expect(await screen.findByText('A Recommended Book')).toBeInTheDocument()
    expect(recommendationsApi.getShelfRecommendations).toHaveBeenCalledWith('s1', {
      cursor: null,
    })
  })

  it('still lets the visitor switch shelves when this one fails to load', async () => {
    vi.spyOn(shelvesApi, 'getShelf').mockRejectedValue(new Error('boom'))
    renderLens()

    expect(await screen.findByText("Couldn't load this shelf.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All' })).toBeInTheDocument()
  })
})
