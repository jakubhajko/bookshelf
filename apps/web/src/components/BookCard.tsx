import { EyeOff } from 'lucide-react'
import { useState, type MouseEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useBookState, useSyncShelvesMutation } from '../hooks/useBookState'
import { useLastUsedShelf } from '../hooks/useLastUsedShelf'
import { resolveBackgroundLocation } from '../routing/modalNavigation'
import { BookCover } from './BookCover'
import { RatingDisplay } from './RatingDisplay'
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

/** No `transition-opacity` here, deliberately. A fade leaves the overlay
 * sitting at partial opacity for the length of the transition, and a
 * partially transparent control is a genuinely less legible one — the
 * accent-filled Save button blends down to ~3.5:1 against the page
 * mid-fade, from 4.60:1 at rest, which the e2e axe scan catches whenever
 * the pointer happens to rest on a card. Revealing instantly keeps the
 * only rendered state the legible one, and matches the brief's "avoid
 * unnecessary animation". Opacity (not `visibility`/`hidden`) remains the
 * mechanism so the buttons stay focusable and keyboard-reachable while
 * hidden — that's what `group-focus-within` reveals them for. */
const OVERLAY_VISIBILITY =
  'opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100'

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
        {/* Persistent (not hover-gated) state markers (spec §12.6) — passive
          * info, not controls. Home/Similar cards never show either (spec
          * §5.5 guarantees Neutral/unsaved), but Search/Rated/Shelf-books
          * results can arrive already rated or Not Interested.
          *
          * "Not interested" overlays the cover, and is positioned against
          * *it* rather than the card: anchored to the card it sat at the
          * bottom of the whole thing, on top of the title and author. The
          * rating isn't an overlay at all — see below. */}
        <div className="relative">
          <BookCover
            objectKey={book.cover_object_key}
            title={book.title}
            author={book.primary_author_name}
          />
          {notInterested && (
            <span className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-1 rounded-full bg-background/85 px-2 py-1 text-xs text-text-muted">
              <EyeOff aria-hidden className="h-3 w-3" />
              Not interested
            </span>
          )}
        </div>

        {/* Below the cover, above the title: the rating is the first thing
          * worth knowing about a book you've already read, and stars carry
          * that without being read. */}
        {!notInterested && rating !== null && <RatingDisplay value={rating} className="mt-2" />}

        <h3 className="mt-1.5 line-clamp-2 text-sm font-medium text-text">{book.title}</h3>
        {book.primary_author_name && (
          <p className="line-clamp-1 text-xs text-text-muted">{book.primary_author_name}</p>
        )}
      </button>

      {/* Shelf pill and Save share one row rather than being pinned to
        * opposite corners independently: on a narrow column the two would
        * otherwise overlap, and as flex siblings the shelf name truncates
        * instead while Save keeps its full width. */}
      <div
        className={`absolute inset-x-2 top-2 flex items-center justify-between gap-1.5 ${OVERLAY_VISIBILITY}`}
      >
        <ShelfSelectorPopover
          bookId={book.book_id}
          defaultShelfId={defaultShelfId}
          open={shelfSelectorOpen}
          onOpenChange={setShelfSelectorOpen}
        />

        {/* The one place the accent carries real weight: a solid, compact
          * pill that stays legible over any cover. Once saved it steps back
          * to a neutral dark fill — the action is done, and leaving it
          * accent-colored would keep shouting on every card the visitor has
          * already dealt with. Focus ring is `ring-text`, since an accent
          * ring on an accent fill would be invisible. */}
        <button
          type="button"
          onClick={handleSaveClick}
          aria-pressed={saved}
          className={`flex h-8 shrink-0 items-center rounded-full px-3 text-sm font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-text ${
            saved
              ? 'bg-background/85 text-text hover:bg-background'
              : 'bg-accent text-accent-text hover:bg-accent-hover active:bg-accent-active'
          }`}
        >
          {saved ? 'Saved' : 'Save'}
        </button>
      </div>
    </div>
  )
}
