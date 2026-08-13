import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as booksApi from '../api/books'
import * as shelvesApi from '../api/shelves'
import { ShelfSelectorPopover } from './ShelfSelectorPopover'

const NOW = '2026-01-01T00:00:00Z'
const SHELVES: shelvesApi.Shelf[] = [
  {
    id: 's1',
    name: 'To Read',
    description: null,
    book_count: 0,
    cover_object_keys: [],
    created_at: NOW,
    updated_at: NOW,
  },
  {
    id: 's2',
    name: 'Favorites',
    description: null,
    book_count: 0,
    cover_object_keys: [],
    created_at: NOW,
    updated_at: NOW,
  },
]

function renderPopover() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ShelfSelectorPopover bookId={1} />
    </QueryClientProvider>,
  )
}

describe('ShelfSelectorPopover', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(shelvesApi, 'listShelves').mockResolvedValue(SHELVES)
  })

  it('opens to show a searchable, multi-select list of shelves', async () => {
    const user = userEvent.setup()
    renderPopover()

    await user.click(screen.getByRole('button', { name: /^Add to shelf/ }))

    expect(await screen.findByRole('checkbox', { name: 'To Read' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Favorites' })).toBeInTheDocument()
  })

  it('filters shelves as the search text changes', async () => {
    const user = userEvent.setup()
    renderPopover()
    await user.click(screen.getByRole('button', { name: /^Add to shelf/ }))
    await screen.findByRole('checkbox', { name: 'To Read' })

    await user.type(screen.getByPlaceholderText('Search or create a shelf'), 'Fav')

    expect(screen.queryByRole('checkbox', { name: 'To Read' })).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Favorites' })).toBeInTheDocument()
  })

  it('checking a shelf syncs it onto the book', async () => {
    const user = userEvent.setup()
    vi.spyOn(booksApi, 'syncBookShelves').mockResolvedValue(['s1'])
    renderPopover()
    await user.click(screen.getByRole('button', { name: /^Add to shelf/ }))

    await user.click(await screen.findByRole('checkbox', { name: 'To Read' }))

    // Third argument is attribution (rec-spec §4.3) — `undefined` here
    // because this popover is rendered without a surface context, which is
    // the "origin unknown" case ADR-0015 requires to keep working.
    await waitFor(() =>
      expect(booksApi.syncBookShelves).toHaveBeenCalledWith(1, ['s1'], undefined),
    )
  })

  it('offers to create a shelf that does not exist yet, then saves the book to it', async () => {
    const user = userEvent.setup()
    vi.spyOn(shelvesApi, 'createShelf').mockResolvedValue({
      id: 's3',
      name: 'Sci-Fi',
      description: null,
      book_count: 0,
      cover_object_keys: [],
      created_at: NOW,
      updated_at: NOW,
    })
    vi.spyOn(booksApi, 'syncBookShelves').mockResolvedValue(['s3'])
    renderPopover()
    await user.click(screen.getByRole('button', { name: /^Add to shelf/ }))
    await screen.findByRole('checkbox', { name: 'To Read' })

    await user.type(screen.getByPlaceholderText('Search or create a shelf'), 'Sci-Fi')
    await user.click(screen.getByRole('button', { name: /Create.*Sci-Fi/ }))

    await waitFor(() => expect(shelvesApi.createShelf).toHaveBeenCalledWith('Sci-Fi'))
    await waitFor(() =>
      expect(booksApi.syncBookShelves).toHaveBeenCalledWith(1, ['s3'], undefined),
    )
  })

  it('does not offer to create a shelf that already exists (case-insensitive)', async () => {
    const user = userEvent.setup()
    renderPopover()
    await user.click(screen.getByRole('button', { name: /^Add to shelf/ }))
    await screen.findByRole('checkbox', { name: 'To Read' })

    await user.type(screen.getByPlaceholderText('Search or create a shelf'), 'to read')

    expect(screen.queryByRole('button', { name: /Create/ })).not.toBeInTheDocument()
  })
})
