import { Bookmark } from 'lucide-react'
import { useState, type MouseEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import type { RecommendationBookItem } from '../api/recommendations'
import { useBookState, useSyncShelvesMutation } from '../hooks/useBookState'
import { useLastUsedShelf } from '../hooks/useLastUsedShelf'
import { resolveBackgroundLocation } from '../routing/modalNavigation'
import { BookCover } from './BookCover'
import { ShelfSelectorPopover } from './ShelfSelectorPopover'

interface BookCardProps {
  book: RecommendationBookItem
}

const OVERLAY_VISIBILITY =
  'opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100'

/**
 * Cover + title/author + hover overlay (spec §12.6). The overlay defaults
 * to visible below the `md` breakpoint and hover-gated at `md` and up —
 * "touch controls remain usable without hover" (spec §12.6), and touch
 * devices are, imperfectly but reasonably, approximated by narrow
 * viewports here rather than feature-detecting touch support directly.
 */
export function BookCard({ book }: BookCardProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { shelf_ids: shelfIds } = useBookState(book.book_id)
  const syncShelves = useSyncShelvesMutation(book.book_id)
  const [lastUsedShelfId] = useLastUsedShelf()
  const [shelfSelectorOpen, setShelfSelectorOpen] = useState(false)
  const saved = shelfIds.length > 0

  function openDetail() {
    void navigate(`/books/${book.book_id}`, {
      state: { backgroundLocation: resolveBackgroundLocation(location) },
    })
  }

  function handleSaveClick(event: MouseEvent) {
    event.stopPropagation()
    if (saved) {
      // Already saved somewhere — reviewing/editing which shelves is the
      // selector's job; a bare click here shouldn't silently unsave.
      setShelfSelectorOpen(true)
      return
    }
    if (lastUsedShelfId) {
      syncShelves.mutate([...shelfIds, lastUsedShelfId])
    } else {
      // No shelf established yet this session — nothing to quick-save to,
      // so fall through to the same picker the shelf-selector button opens.
      setShelfSelectorOpen(true)
    }
  }

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={openDetail}
        className="block w-full rounded-md text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <BookCover
          objectKey={book.cover_object_key}
          title={book.title}
          author={book.primary_author_name}
        />
        <h3 className="mt-2 line-clamp-2 text-sm font-medium text-text">{book.title}</h3>
        {book.primary_author_name && (
          <p className="line-clamp-1 text-xs text-text-muted">{book.primary_author_name}</p>
        )}
      </button>

      <div className={`absolute top-2 left-2 ${OVERLAY_VISIBILITY}`}>
        <ShelfSelectorPopover
          bookId={book.book_id}
          open={shelfSelectorOpen}
          onOpenChange={setShelfSelectorOpen}
        />
      </div>

      <div className={`absolute top-2 right-2 ${OVERLAY_VISIBILITY}`}>
        <button
          type="button"
          onClick={handleSaveClick}
          aria-pressed={saved}
          className={`flex h-8 items-center gap-1 rounded-full px-3 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-accent ${
            saved ? 'bg-accent text-accent-text' : 'bg-surface/90 text-text hover:bg-surface-hover'
          }`}
        >
          <Bookmark aria-hidden className="h-3.5 w-3.5" fill={saved ? 'currentColor' : 'none'} />
          {saved ? 'Saved' : 'Save'}
        </button>
      </div>
    </div>
  )
}
