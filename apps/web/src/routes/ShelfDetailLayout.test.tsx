import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as shelvesApi from '../api/shelves'
import type { Shelf } from '../api/shelves'
import { ShelfDetailLayout } from './ShelfDetailLayout'

const NOW = '2026-01-01T00:00:00Z'
const SHELF: Shelf = {
  id: 's1',
  name: 'Sci-Fi',
  description: 'Space and robots',
  book_count: 3,
  cover_object_keys: [],
  created_at: NOW,
  updated_at: NOW,
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/shelves" element={<p>shelves overview</p>} />
          <Route path="/shelves/:shelfId" element={<ShelfDetailLayout />}>
            <Route path="books" element={<p>books content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ShelfDetailLayout', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(shelvesApi, 'getShelf').mockResolvedValue(SHELF)
  })

  it('renders the shelf header above its contents (spec §12.8)', async () => {
    renderAt('/shelves/s1/books')

    expect(await screen.findByRole('heading', { name: 'Sci-Fi' })).toBeInTheDocument()
    expect(screen.getByText('Space and robots')).toBeInTheDocument()
    expect(screen.getByText('3 books')).toBeInTheDocument()
    expect(screen.getByText('books content')).toBeInTheDocument()
  })

  it('no longer offers Discover as a tab — it is the lens view now', async () => {
    renderAt('/shelves/s1/books')
    await screen.findByRole('heading', { name: 'Sci-Fi' })

    expect(screen.queryByRole('link', { name: 'Discover' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Books' })).not.toBeInTheDocument()
  })

  it('renames the shelf', async () => {
    const user = userEvent.setup()
    vi.spyOn(shelvesApi, 'updateShelf').mockResolvedValue({ ...SHELF, name: 'Space Opera' })
    renderAt('/shelves/s1/books')
    await screen.findByRole('heading', { name: 'Sci-Fi' })

    await user.click(screen.getByRole('button', { name: 'Edit shelf' }))
    const nameField = screen.getByLabelText('Name')
    await user.clear(nameField)
    await user.type(nameField, 'Space Opera')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(shelvesApi.updateShelf).toHaveBeenCalledWith('s1', {
      name: 'Space Opera',
      description: 'Space and robots',
    }))
    expect(await screen.findByRole('heading', { name: 'Space Opera' })).toBeInTheDocument()
  })

  it('deletes the shelf after confirmation', async () => {
    const user = userEvent.setup()
    vi.spyOn(shelvesApi, 'deleteShelf').mockResolvedValue(undefined)
    renderAt('/shelves/s1/books')
    await screen.findByRole('heading', { name: 'Sci-Fi' })

    await user.click(screen.getByRole('button', { name: 'Delete shelf' }))
    await user.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(shelvesApi.deleteShelf).toHaveBeenCalledWith('s1'))
    expect(await screen.findByText('shelves overview')).toBeInTheDocument()
  })
})
