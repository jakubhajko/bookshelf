import { Bookmark, EyeOff, Star } from 'lucide-react'
import { useState, type MouseEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useBookState, useSyncShelvesMutation } from '../hooks/useBookState'
import { useLastUsedShelf } from '../hooks/useLastUsedShelf'
import { resolveBackgroundLocation } from '../routing/modalNavigation'
import { BookCover } from './BookCover'
import { ShelfSelectorPopover } from './ShelfSelectorPopover'

/** Minimal shape every card-rendering surface's item satisfies —
 * `RecommendationBookItem` (Home/Similar/Shelf-discover) and
 * `SearchResultItem` (Search) both have at least these fields, so either
 * can be passed here directly without a conversion step. */
export interface BookCardData {
  book_id: number
  work_id: string
  title: string
  primary_author_name: string | null
  cover_object_key: string | null
}

interface BookCardProps {
  book: BookCardData
  /** Shelf-discover context (spec §12.8: "defaults Save to current
   * shelf") — takes precedence over the session's last-used shelf for
   * this card's quick-Save action only. Saving here still updates the
   * session's last-used shelf for every other surface, since it *is* now
   * the most recently used one. */
  defaultShelfId?: string
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
export function BookCard({ book, defaultShelfId }: BookCardProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { rating, not_interested: notInterested, shelf_ids: shelfIds } = useBookState(book.book_id)
  const syncShelves = useSyncShelvesMutation(book.book_id)
  const [lastUsedShelfId, setLastUsedShelfId] = useLastUsedShelf()
  const [shelfSelectorOpen, setShelfSelectorOpen] = useState(false)
  const saved = shelfIds.length > 0
  const quickSaveShelfId = defaultShelfId ?? lastUsedShelfId

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
    if (quickSaveShelfId) {
      syncShelves.mutate([...shelfIds, quickSaveShelfId])
      setLastUsedShelfId(quickSaveShelfId)
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

      {/* Persistent (not hover-gated) state badges (spec §12.6) — passive
       * info, not a control, so unlike the overlay above these are always
       * visible. Home/Similar cards never show either (spec §5.5
       * guarantees Neutral/unsaved), but Search/Rated/Shelf-books results
       * can arrive already rated or Not Interested. */}
      {notInterested && (
        <span className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1 rounded-full bg-surface/90 px-2 py-1 text-xs text-text-muted">
          <EyeOff aria-hidden className="h-3 w-3" />
          Not interested
        </span>
      )}
      {!notInterested && rating !== null && (
        <span className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1 rounded-full bg-surface/90 px-2 py-1 text-xs font-medium text-text">
          <Star aria-hidden fill="currentColor" className="h-3 w-3 text-accent" />
          {rating}
        </span>
      )}
    </div>
  )
}
