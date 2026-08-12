import * as Popover from '@radix-ui/react-popover'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Plus } from 'lucide-react'
import { useState } from 'react'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'
import { useBookState, useSyncShelvesMutation } from '../hooks/useBookState'
import { useLastUsedShelf } from '../hooks/useLastUsedShelf'

interface ShelfSelectorPopoverProps {
  bookId: number
  /** `card`: compact pill for the card hover overlay, naming the shelf in
   * play (spec §12.6). `full`: labeled button for the detail page's shelf
   * controls (spec §12.7). */
  variant?: 'card' | 'full'
  /** Shelf-discover context (spec §12.8) — the shelf the card's Save would
   * default to, and so the one the `card` trigger names when the book
   * isn't on a shelf yet. */
  defaultShelfId?: string
  /** Lets `BookCard`'s separate Save/Saved button open the same popover
   * (clicking "Saved" reviews/edits shelves rather than instantly
   * unsaving) — falls back to internal state when unused, e.g. on the
   * detail page where nothing else needs to open it. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

/** Searchable, multi-select, create-capable shelf picker (spec §12.6).
 * Native checkboxes rather than a custom listbox/combobox — ADR-0008 asks
 * for accessible headless primitives over hand-rolled widgets, and a
 * native `<input type="checkbox">` is more robustly accessible than a
 * hand-rolled multi-select listbox would be; Radix's `Popover` supplies
 * the positioning/dismiss/focus-return behavior around it. */
export function ShelfSelectorPopover({
  bookId,
  variant = 'card',
  defaultShelfId,
  open: controlledOpen,
  onOpenChange,
}: ShelfSelectorPopoverProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = controlledOpen ?? internalOpen
  const setOpen = onOpenChange ?? setInternalOpen

  const [query, setQuery] = useState('')
  const queryClient = useQueryClient()
  const { data: shelves = [] } = useQuery({
    queryKey: queryKeys.shelves.list,
    queryFn: shelvesApi.listShelves,
    staleTime: 30_000,
  })
  const { shelf_ids: shelfIds } = useBookState(bookId)
  const syncShelves = useSyncShelvesMutation(bookId)
  const [lastUsedShelfId, setLastUsedShelfId] = useLastUsedShelf()

  // The shelf the trigger names. A book already on a shelf shows that
  // shelf; otherwise it shows where a quick Save would put it, which is the
  // same shelf `BookCard` would use — so the pill is a truthful preview of
  // the action next to it, not just decoration.
  const namedShelfId = shelfIds[0] ?? defaultShelfId ?? lastUsedShelfId
  const namedShelf = shelves.find((shelf) => shelf.id === namedShelfId)

  const trimmedQuery = query.trim()
  const filtered = trimmedQuery
    ? shelves.filter((shelf) => shelf.name.toLowerCase().includes(trimmedQuery.toLowerCase()))
    : shelves
  const hasExactMatch = shelves.some(
    (shelf) => shelf.name.toLowerCase() === trimmedQuery.toLowerCase(),
  )

  function toggleShelf(shelfId: string) {
    const alreadyIn = shelfIds.includes(shelfId)
    syncShelves.mutate(alreadyIn ? shelfIds.filter((id) => id !== shelfId) : [...shelfIds, shelfId])
    if (!alreadyIn) {
      setLastUsedShelfId(shelfId)
    }
  }

  async function handleCreate() {
    if (!trimmedQuery) return
    const shelf = await shelvesApi.createShelf(trimmedQuery)
    queryClient.setQueryData<shelvesApi.Shelf[]>(queryKeys.shelves.list, (current) => [
      ...(current ?? []),
      shelf,
    ])
    syncShelves.mutate([...shelfIds, shelf.id])
    setLastUsedShelfId(shelf.id)
    setQuery('')
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        {variant === 'card' ? (
          <button
            type="button"
            onClick={(event) => event.stopPropagation()}
            className="flex h-8 min-w-0 items-center gap-0.5 rounded-full bg-background/85 px-2.5 text-sm font-semibold text-text transition-colors hover:bg-background focus:outline-none focus:ring-2 focus:ring-text"
          >
            {/* The visible label is the shelf name, so the accessible name
              * has to contain it too (WCAG 2.5.3) or voice control users
              * couldn't say what they can see. This prefix supplies the
              * action the bare name would otherwise be missing. */}
            <span className="sr-only">Add to shelf{namedShelf ? ': ' : ''}</span>
            {namedShelf ? (
              <>
                <span className="truncate">{namedShelf.name}</span>
                <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0" />
              </>
            ) : (
              // Nothing to name yet (no shelves, nothing saved this
              // session) — the pill falls back to the bare add affordance
              // rather than showing a dropdown arrow pointing at nothing.
              <Plus aria-hidden className="h-4 w-4 shrink-0" />
            )}
          </button>
        ) : (
          <button
            type="button"
            className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <Plus aria-hidden className="h-4 w-4" />
            Add to shelf
          </button>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={8}
          onClick={(event) => event.stopPropagation()}
          className="z-20 w-64 rounded-md border border-border bg-surface p-2 shadow-lg"
        >
          <label htmlFor={`shelf-search-${bookId}`} className="sr-only">
            Search shelves
          </label>
          <input
            id={`shelf-search-${bookId}`}
            type="text"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search or create a shelf"
            className="mb-2 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
          />
          <ul className="max-h-48 overflow-y-auto">
            {filtered.map((shelf) => {
              const checked = shelfIds.includes(shelf.id)
              return (
                <li key={shelf.id}>
                  <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-text hover:bg-surface-hover">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleShelf(shelf.id)}
                      className="h-4 w-4 accent-accent"
                    />
                    <span className="truncate">{shelf.name}</span>
                  </label>
                </li>
              )
            })}
            {filtered.length === 0 && !trimmedQuery && (
              <li className="px-2 py-1.5 text-sm text-text-muted">No shelves yet.</li>
            )}
          </ul>
          {trimmedQuery && !hasExactMatch && (
            <button
              type="button"
              onClick={() => void handleCreate()}
              className="mt-1 flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm text-accent-soft hover:bg-surface-hover"
            >
              <Plus aria-hidden className="h-4 w-4" />
              Create &ldquo;{trimmedQuery}&rdquo;
            </button>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
