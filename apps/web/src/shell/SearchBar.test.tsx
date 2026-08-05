import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as searchApi from '../api/search'
import { SearchBar } from './SearchBar'

function renderBar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<SearchBar />} />
          <Route path="/search" element={<p>search results page</p>} />
          <Route path="/books/:bookId" element={<p>book detail page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SearchBar', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('shows debounced suggestions while typing', async () => {
    const user = userEvent.setup()
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [
        {
          book_id: 1,
          work_id: 'w1',
          title: 'Dune',
          primary_author_name: 'Frank Herbert',
          cover_object_key: null,
          user_state: { rating: null, not_interested: false, shelf_ids: [] },
        },
      ],
      next_cursor: null,
    })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'Dune')

    await waitFor(() => expect(searchApi.searchBooks).toHaveBeenCalledWith('Dune', { limit: 5 }), {
      timeout: 2000,
    })
    expect(await screen.findByRole('button', { name: /Dune.*Frank Herbert/ })).toBeInTheDocument()
  })

  it('navigates straight to a book when a suggestion is clicked', async () => {
    const user = userEvent.setup()
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [
        {
          book_id: 42,
          work_id: 'w42',
          title: 'Dune',
          primary_author_name: 'Frank Herbert',
          cover_object_key: null,
          user_state: { rating: null, not_interested: false, shelf_ids: [] },
        },
      ],
      next_cursor: null,
    })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'Dune')
    const suggestion = await screen.findByRole('button', { name: /Dune.*Frank Herbert/ })
    await user.click(suggestion)

    expect(await screen.findByText('book detail page')).toBeInTheDocument()
  })

  it('submitting the form navigates to the full results page and records the search', async () => {
    const user = userEvent.setup()
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({ items: [], next_cursor: null })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'Dune{Enter}')

    expect(await screen.findByText('search results page')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('bookshelf:recent-searches') ?? '[]')).toEqual(['Dune'])
  })

  it('shows recent searches when the input is focused and empty', async () => {
    localStorage.setItem('bookshelf:recent-searches', JSON.stringify(['Dune', 'Foundation']))
    const user = userEvent.setup()
    renderBar()

    await user.click(screen.getByLabelText('Search books'))

    expect(await screen.findByText('Recent searches')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dune' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Foundation' })).toBeInTheDocument()
  })
})
