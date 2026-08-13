import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as booksApi from '../api/books'
import * as searchApi from '../api/search'
import * as submittedSearch from '../api/submittedSearch'
import { SearchBar } from './SearchBar'

/**
 * Recommender Phase R1: search instrumentation (rec-spec §4.4, ADR-0015).
 *
 * The load-bearing rule is negative — the debounced suggestions dropdown
 * must record *nothing*. `GET /search/books` backs both the dropdown and
 * the results page, so a careless implementation logs a "search" on every
 * keystroke and fills the table with prefixes of what the reader meant.
 */

const SUGGESTION = {
  book_id: 1,
  work_id: 'w1',
  title: 'Dune',
  primary_author_name: 'Frank Herbert',
  cover_object_key: null,
  user_state: { rating: null, not_interested: false, shelf_ids: [] },
}

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

describe('SearchBar instrumentation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    submittedSearch.resetSubmittedSearch()
  })

  it('records nothing while typing — suggestions are not searches', async () => {
    const user = userEvent.setup()
    const record = vi.spyOn(submittedSearch, 'recordSubmittedSearch')
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [SUGGESTION],
      next_cursor: null,
    })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'Dune')

    // Wait for the debounce to fire and the suggestion to actually render,
    // so this asserts "suggestions ran and still logged nothing" rather
    // than "nothing happened yet".
    expect(await screen.findByText('Dune')).toBeInTheDocument()
    expect(record).not.toHaveBeenCalled()
  })

  it('records the query when the search is submitted', async () => {
    const user = userEvent.setup()
    const record = vi.spyOn(submittedSearch, 'recordSubmittedSearch').mockImplementation(() => {})
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({ items: [], next_cursor: null })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'dune{Enter}')

    await waitFor(() => expect(record).toHaveBeenCalledWith('dune'))
    expect(await screen.findByText('search results page')).toBeInTheDocument()
  })

  it('records a recent-search chip as a submitted search too', async () => {
    const user = userEvent.setup()
    localStorage.setItem('bookshelf:recent-searches', JSON.stringify(['hyperion']))
    const record = vi.spyOn(submittedSearch, 'recordSubmittedSearch').mockImplementation(() => {})

    renderBar()
    await user.click(screen.getByLabelText('Search books'))
    await user.click(await screen.findByRole('button', { name: /hyperion/ }))

    await waitFor(() => expect(record).toHaveBeenCalledWith('hyperion'))
  })

  it('records an open when a suggestion is clicked through to a book', async () => {
    const user = userEvent.setup()
    const recordOpen = vi.spyOn(booksApi, 'recordBookOpened').mockImplementation(() => {})
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [SUGGESTION],
      next_cursor: null,
    })

    renderBar()
    await user.type(screen.getByLabelText('Search books'), 'Dune')
    await user.click(await screen.findByText('Dune'))

    // Attributed to the search surface and the suggestion's position, but
    // with no `search_query_id`: picking a suggestion isn't submitting a
    // search, so there is no committed query to point at.
    expect(recordOpen).toHaveBeenCalledWith(1, { surface: 'search', rank_position: 0 })
  })
})
