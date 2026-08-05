import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as shelvesApi from '../api/shelves'
import type { Shelf } from '../api/shelves'
import { ShelvesPage } from './Shelves'

const NOW = '2026-01-01T00:00:00Z'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ShelvesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ShelvesPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows an empty state with no shelves yet', async () => {
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([])
    renderPage()

    expect(
      await screen.findByText('No shelves yet — create one above to start organizing books.'),
    ).toBeInTheDocument()
  })

  it('shows a retry control when shelves fail to load', async () => {
    vi.spyOn(shelvesApi, 'listShelves').mockRejectedValue(new Error('boom'))
    renderPage()

    expect(await screen.findByText("Couldn't load your shelves.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('renders existing shelves with a book-count collage card', async () => {
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([
      {
        id: 's1',
        name: 'To Read',
        description: null,
        book_count: 2,
        cover_object_keys: [],
        created_at: NOW,
        updated_at: NOW,
      },
    ])
    renderPage()

    expect(await screen.findByText('To Read')).toBeInTheDocument()
    expect(screen.getByText('2 books')).toBeInTheDocument()
  })

  it('creates a new shelf from the form', async () => {
    const user = userEvent.setup()
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue([])
    const created: Shelf = {
      id: 's2',
      name: 'Favorites',
      description: null,
      book_count: 0,
      cover_object_keys: [],
      created_at: NOW,
      updated_at: NOW,
    }
    vi.spyOn(shelvesApi, 'createShelf').mockResolvedValue(created)
    renderPage()
    await screen.findByText('No shelves yet — create one above to start organizing books.')

    await user.type(screen.getByLabelText('New shelf'), 'Favorites')
    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(shelvesApi.createShelf).toHaveBeenCalledWith('Favorites'))
    expect(await screen.findByText('Favorites')).toBeInTheDocument()
  })
})
