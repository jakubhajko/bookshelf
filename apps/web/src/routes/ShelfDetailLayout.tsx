import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { queryKeys } from '../api/queryKeys'
import * as shelvesApi from '../api/shelves'
import type { Shelf } from '../api/shelves'
import { TextField } from '../components/TextField'
import { showToast } from '../toast/toastStore'
import { NotFoundPage } from './NotFound'

const TAB_CLASS = ({ isActive }: { isActive: boolean }) =>
  `border-b-2 px-1 pb-2 text-sm font-medium ${
    isActive ? 'border-accent text-text' : 'border-transparent text-text-muted hover:text-text'
  }`

function EditShelfForm({ shelf, onDone }: { shelf: Shelf; onDone: () => void }) {
  const [name, setName] = useState(shelf.name)
  const [description, setDescription] = useState(shelf.description ?? '')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const updateShelf = useMutation({
    mutationFn: () =>
      shelvesApi.updateShelf(shelf.id, { name: name.trim(), description: description.trim() || null }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.shelves.detail(shelf.id), updated)
      queryClient.setQueryData<Shelf[]>(queryKeys.shelves.list, (current) =>
        current?.map((s) => (s.id === updated.id ? updated : s)),
      )
      onDone()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not save changes.'),
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (name.trim()) updateShelf.mutate()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <TextField
        id="shelf-name"
        label="Name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
      />
      <div>
        <label htmlFor="shelf-description" className="block text-sm text-text-muted">
          Description
        </label>
        <textarea
          id="shelf-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          rows={2}
          className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent"
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-accent">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!name.trim() || updateShelf.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-text hover:bg-accent-hover disabled:opacity-60"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md px-3 py-1.5 text-sm text-text-muted hover:text-text"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function DeleteShelfButton({ shelf }: { shelf: Shelf }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const deleteShelf = useMutation({
    mutationFn: () => shelvesApi.deleteShelf(shelf.id),
    onSuccess: () => {
      queryClient.setQueryData<Shelf[]>(queryKeys.shelves.list, (current) =>
        current?.filter((s) => s.id !== shelf.id),
      )
      showToast(`Deleted "${shelf.name}".`, 'success')
      void navigate('/shelves', { replace: true })
    },
    // Unlike rename (which has an inline `role="alert"` in EditShelfForm),
    // nothing else here would tell the visitor a failed delete didn't
    // happen — the confirmation dialog just closes either way.
    onError: (err) =>
      showToast(err instanceof ApiError ? err.message : 'Could not delete shelf.', 'error'),
  })

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button
          type="button"
          aria-label="Delete shelf"
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <Trash2 aria-hidden className="h-4 w-4" />
        </button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-30 bg-black/60" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-30 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-6 focus:outline-none">
          <AlertDialog.Title className="text-base font-semibold text-text">
            Delete &ldquo;{shelf.name}&rdquo;?
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-text-muted">
            This removes the shelf and its memberships. Ratings, Not Interested marks, and other
            shelves are not affected (spec §5.4).
          </AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <button
                type="button"
                className="rounded-md px-3 py-2 text-sm text-text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
              >
                Cancel
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                onClick={() => deleteShelf.mutate()}
                className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-text hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent"
              >
                Delete
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}

/** Shared header (name/description, rename/delete, spec §12.8) + Books/
 * Discover tabs for one shelf, wrapping both via a nested route so neither
 * duplicates the fetch or the chrome. */
export function ShelfDetailLayout() {
  const { shelfId } = useParams()
  const [editing, setEditing] = useState(false)
  const {
    data: shelf,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: queryKeys.shelves.detail(shelfId ?? ''),
    queryFn: () => shelvesApi.getShelf(shelfId ?? ''),
    enabled: Boolean(shelfId),
  })

  if (!shelfId) return <NotFoundPage />

  if (isLoading) {
    return <p className="p-6 text-sm text-text-muted">Loading…</p>
  }

  if (isError || !shelf) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-text-muted">Couldn&apos;t load this shelf.</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6">
      {editing ? (
        <EditShelfForm shelf={shelf} onDone={() => setEditing(false)} />
      ) : (
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-text">{shelf.name}</h1>
            {shelf.description && <p className="mt-1 text-sm text-text-muted">{shelf.description}</p>}
            <p className="mt-1 text-xs text-text-muted">
              {shelf.book_count} {shelf.book_count === 1 ? 'book' : 'books'}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              aria-label="Edit shelf"
              onClick={() => setEditing(true)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <Pencil aria-hidden className="h-4 w-4" />
            </button>
            <DeleteShelfButton shelf={shelf} />
          </div>
        </div>
      )}

      <nav aria-label="Shelf sections" className="mt-6 flex gap-6 border-b border-border">
        <NavLink to={`/shelves/${shelfId}/books`} className={TAB_CLASS}>
          Books
        </NavLink>
        <NavLink to={`/shelves/${shelfId}/discover`} className={TAB_CLASS}>
          Discover
        </NavLink>
      </nav>

      <div className="mt-6">
        <Outlet />
      </div>
    </div>
  )
}
