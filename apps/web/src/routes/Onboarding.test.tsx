import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as searchApi from '../api/search'
import * as tasteSeedsApi from '../api/tasteSeeds'
import { OnboardingPage } from './Onboarding'

const navigate = vi.fn()
vi.mock('react-router', async () => {
  const actual = await vi.importActual<typeof import('react-router')>('react-router')
  return { ...actual, useNavigate: () => navigate }
})

function book(bookId: number, title: string) {
  return {
    book_id: bookId,
    work_id: `w-${bookId}`,
    title,
    primary_author_name: 'An Author',
    cover_object_key: null,
    user_state: { rating: null, not_interested: false, shelf_ids: [] },
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OnboardingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Render the page and run one search, returning the user-event handle. */
async function renderAndSearch(term = 'dune') {
  const user = userEvent.setup()
  renderPage()
  await user.type(screen.getByLabelText('Search for books or authors'), term)
  await user.click(screen.getByRole('button', { name: 'Search' }))
  return user
}

describe('OnboardingPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    navigate.mockReset()
    vi.spyOn(tasteSeedsApi, 'listTasteSeeds').mockResolvedValue({ items: [] })
  })

  it('prompts before any search has been made', () => {
    renderPage()
    expect(screen.getByText('Search above to find books you like.')).toBeInTheDocument()
    expect(screen.getByText('Nothing selected yet.')).toBeInTheDocument()
  })

  it('selects and deselects a book', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [book(1, 'Dune'), book(2, 'Neuromancer')],
      next_cursor: null,
    })
    const user = await renderAndSearch()

    const dune = await screen.findByRole('button', { name: /Dune/ })
    expect(dune).toHaveAttribute('aria-pressed', 'false')

    await user.click(dune)
    expect(dune).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/1 book selected/)).toBeInTheDocument()

    await user.click(dune)
    expect(dune).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('Nothing selected yet.')).toBeInTheDocument()
  })

  it('is operable from the keyboard alone', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [book(1, 'Dune')],
      next_cursor: null,
    })
    const user = userEvent.setup()
    renderPage()

    await user.tab()
    expect(screen.getByLabelText('Search for books or authors')).toHaveFocus()
    await user.keyboard('dune{Enter}')

    const dune = await screen.findByRole('button', { name: /Dune/ })
    dune.focus()
    await user.keyboard('{Enter}')
    expect(dune).toHaveAttribute('aria-pressed', 'true')
  })

  it('encourages three selections without blocking on it', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [book(1, 'Dune')],
      next_cursor: null,
    })
    vi.spyOn(tasteSeedsApi, 'syncTasteSeeds').mockResolvedValue({ items: [] })
    const user = await renderAndSearch()

    await user.click(await screen.findByRole('button', { name: /Dune/ }))
    expect(screen.getByText(/3 or more works best/)).toBeInTheDocument()

    // rec-spec §6 encourages 3-10 and explicitly does not hard-block below
    // it: one selection is still worth saving.
    const cont = screen.getByRole('button', { name: 'Continue' })
    expect(cont).toBeEnabled()
    await user.click(cont)
    await waitFor(() => expect(tasteSeedsApi.syncTasteSeeds).toHaveBeenCalledWith([1]))
  })

  it('saves the selection and goes to the feed', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({
      items: [book(1, 'Dune'), book(2, 'Neuromancer')],
      next_cursor: null,
    })
    vi.spyOn(tasteSeedsApi, 'syncTasteSeeds').mockResolvedValue({ items: [] })
    const user = await renderAndSearch()

    await user.click(await screen.findByRole('button', { name: /Dune/ }))
    await user.click(await screen.findByRole('button', { name: /Neuromancer/ }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => expect(tasteSeedsApi.syncTasteSeeds).toHaveBeenCalledWith([1, 2]))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/'))
  })

  it('can be skipped without saving anything', async () => {
    const sync = vi.spyOn(tasteSeedsApi, 'syncTasteSeeds')
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Skip for now' }))

    // rec-spec §6: skipping must not be a disguised "save nothing" — a
    // reader who skips has not asked to clear anything.
    expect(sync).not.toHaveBeenCalled()
    expect(navigate).toHaveBeenCalledWith('/')
  })

  it('saves an empty selection only when the reader deliberately continues', async () => {
    vi.spyOn(tasteSeedsApi, 'syncTasteSeeds').mockResolvedValue({ items: [] })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(tasteSeedsApi.syncTasteSeeds).toHaveBeenCalledWith([]))
  })

  it('shows what was already selected on a return visit', async () => {
    vi.spyOn(tasteSeedsApi, 'listTasteSeeds').mockResolvedValue({
      items: [
        {
          book_id: 7,
          work_id: 'w-7',
          title: 'Dune',
          primary_author_name: 'Frank Herbert',
          cover_object_key: null,
          source: 'onboarding',
          selected_at: '2026-08-15T12:00:00Z',
        },
      ],
    })
    renderPage()

    // Without this, continuing from a return visit would silently replace
    // the reader's existing seeds with whatever is on screen.
    await waitFor(() => expect(screen.getByText(/1 book selected/)).toBeInTheDocument())
  })

  it('reports an empty result set', async () => {
    vi.spyOn(searchApi, 'searchBooks').mockResolvedValue({ items: [], next_cursor: null })
    await renderAndSearch('nothingmatchesthis')
    expect(
      await screen.findByText(/No books found for/),
    ).toBeInTheDocument()
  })

  it('offers a retry when search fails', async () => {
    const searchBooks = vi
      .spyOn(searchApi, 'searchBooks')
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue({ items: [book(1, 'Dune')], next_cursor: null })
    const user = await renderAndSearch()

    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(searchBooks).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('button', { name: /Dune/ })).toBeInTheDocument()
  })

  it('surfaces a save failure instead of pretending it worked', async () => {
    vi.spyOn(tasteSeedsApi, 'syncTasteSeeds').mockRejectedValue(new Error('nope'))
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Couldn't save your selection/)
    expect(navigate).not.toHaveBeenCalledWith('/')
  })
})
