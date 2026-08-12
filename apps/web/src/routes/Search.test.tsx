import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as searchApi from '../api/search'
import { SearchPage } from './Search'

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('prompts for a query when none is in the URL', () => {
    renderAt('/search')
    expect(screen.getByText('Search for books or authors above.')).toBeInTheDocument()
  })

  it('shows an empty state when nothing matches', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({ items: [], next_cursor: null })
    renderAt('/search?q=zzznomatch')

    expect(await screen.findByText(/No books found for.*zzznomatch/)).toBeInTheDocument()
  })

  it('shows a retry control when the search request fails', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockRejectedValue(new Error('boom'))
    renderAt('/search?q=dune')

    expect(await screen.findByText("Couldn't load search results.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('renders results with an accurate rating (spec §9.6: prior states stay visible)', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [
        {
          book_id: 1,
          work_id: 'w1',
          title: 'Already Rated Book',
          primary_author_name: 'An Author',
          cover_object_key: 'cover.jpg',
          user_state: { rating: 4.5, not_interested: false, shelf_ids: [] },
        },
      ],
      next_cursor: null,
    })
    renderAt('/search?q=rated')

    expect(await screen.findByText('Already Rated Book')).toBeInTheDocument()
    // Shown as stars rather than a numeral, so the half-step has to survive
    // into the accessible name for this to mean anything.
    expect(screen.getByRole('img', { name: 'You rated this 4.5 out of 5' })).toBeInTheDocument()
  })
})
