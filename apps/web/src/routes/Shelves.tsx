import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Library, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../api/client'
import { coverUrl } from '../api/covers'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'
import type { Shelf } from '../api/shelves'
import { TextField } from '../components/TextField'

/** Board-like cover collage (spec §12.8) — up to 4 of the shelf's
 * most-recently-added covers in a 2x2 grid; a shelf icon placeholder if it
 * has none yet. Each thumbnail is `alt=""`: purely decorative, redundant
 * with the shelf name rendered right below. */
function ShelfCollage({ coverObjectKeys }: { coverObjectKeys: string[] }) {
  if (coverObjectKeys.length === 0) {
    return (
      <div className="flex aspect-square w-full items-center justify-center rounded-md bg-surface">
        <Library aria-hidden className="h-8 w-8 text-text-muted" />
      </div>
    )
  }

  return (
    <div className="grid aspect-square w-full grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-md bg-surface">
      {coverObjectKeys.slice(0, 4).map((key) => (
        <img key={key} src={coverUrl(key) ?? undefined} alt="" className="h-full w-full object-cover" />
      ))}
    </div>
  )
}

function CreateShelfForm() {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const createShelf = useMutation({
    mutationFn: (shelfName: string) => shelvesApi.createShelf(shelfName),
    onSuccess: (shelf) => {
      queryClient.setQueryData<Shelf[]>(queryKeys.shelves.list, (current) => [
        shelf,
        ...(current ?? []),
      ])
      setName('')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create shelf.'),
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const trimmed = name.trim()
    if (trimmed) createShelf.mutate(trimmed)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="w-full max-w-xs">
        <TextField
          id="new-shelf-name"
          label="New shelf"
          placeholder="e.g. Weekend reads"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <button
        type="submit"
        disabled={!name.trim() || createShelf.isPending}
        className="flex items-center gap-1.5 rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60"
      >
        <Plus aria-hidden className="h-4 w-4" />
        Create
      </button>
      {error && (
        <p role="alert" className="w-full text-sm text-accent">
          {error}
        </p>
      )}
    </form>
  )
}

/** Shelf overview (spec §12.8): collages + create. Rename/edit
 * description/delete live on the shelf detail page
 * (`routes/ShelfDetailLayout.tsx`), not here. */
export function ShelvesPage() {
  const {
    data: shelves,
    isLoading,
    isError,
    refetch,
  } = useQuery({ queryKey: queryKeys.shelves.list, queryFn: shelvesApi.listShelves })

  return (
    <div className="p-4 sm:p-6">
      <h1 className="text-xl font-semibold text-text">Your shelves</h1>

      <div className="mt-4">
        <CreateShelfForm />
      </div>

      {isLoading && <p className="mt-8 text-sm text-text-muted">Loading…</p>}

      {isError && !isLoading && (
        <div className="mt-8 text-center">
          <p className="text-sm text-text-muted">Couldn&apos;t load your shelves.</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
          >
            Retry
          </button>
        </div>
      )}

      {shelves && shelves.length === 0 && (
        <p className="mt-8 text-sm text-text-muted">
          No shelves yet — create one above to start organizing books.
        </p>
      )}

      {shelves && shelves.length > 0 && (
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {shelves.map((shelf) => (
            <Link
              key={shelf.id}
              to={`/shelves/${shelf.id}/books`}
              className="group rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <ShelfCollage coverObjectKeys={shelf.cover_object_keys} />
              <h2 className="mt-2 line-clamp-1 text-sm font-medium text-text group-hover:underline">
                {shelf.name}
              </h2>
              <p className="text-xs text-text-muted">
                {shelf.book_count} {shelf.book_count === 1 ? 'book' : 'books'}
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
