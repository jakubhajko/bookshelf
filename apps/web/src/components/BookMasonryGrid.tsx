import { useMemo } from 'react'
import { useGridTier } from '../hooks/useGridTier'
import { BookCard, type BookCardData } from './BookCard'
import { CardSkeleton } from './CardSkeleton'

function distributeIntoColumns<T>(items: T[], columnCount: number): T[][] {
  const columns: T[][] = Array.from({ length: columnCount }, () => [])
  items.forEach((item, index) => {
    columns[index % columnCount]?.push(item)
  })
  return columns
}

/**
 * Responsive masonry (spec §12.5). Items are distributed round-robin by
 * index into N column arrays (N from `useGridTier`), each rendered as
 * its own vertical flex stack — not CSS multi-column layout, which
 * rebalances *every* item into new columns as the list grows and would
 * violate spec §12.4's "stable rendered order" the moment infinite scroll
 * appends a page. Round-robin's column assignment for existing items never
 * changes when new items are appended at the end, and unlike a
 * shortest-column-fill algorithm it doesn't need to measure real image
 * heights to decide placement.
 */

/** Vertical rhythm inside each column. Read alongside the stars and
 * title/author under every cover, this lands close to the horizontal
 * gutter, so the grid reads evenly spaced in both directions. */
const COLUMN_GAP = 'gap-6'

/**
 * The gutter is a percentage of the row rather than a fixed pixel gap,
 * because that's what makes cover size *uniform*: a card always ends up at
 * `(100 - gutterShare) / columns` percent of the row, at every viewport
 * width. A fixed gap can't do that — the same 16px is a large share of a
 * narrow column and a negligible one of a wide column, so covers would
 * shrink at some window sizes and not others. Tier values live in
 * `useGridTier`.
 */
function gutterStyle({ columns, gutterShare }: { columns: number; gutterShare: number }) {
  // A single column has no gaps to distribute — and would divide by zero.
  return columns > 1 ? { columnGap: `${gutterShare / (columns - 1)}%` } : undefined
}

interface BookMasonryGridProps {
  items: BookCardData[]
  /** Forwarded to every card — shelf-discover context (spec §12.8:
   * "defaults Save to current shelf"). */
  defaultShelfId?: string
  /** Upper bound on the viewport-derived column count, for grids that
   * don't span the viewport. `useGridTier` measures `window`, so inside
   * a narrow container — the detail dialog's "Similar books" strip — the
   * viewport tier would otherwise squeeze full-width column counts into a
   * fraction of the width. */
  maxColumns?: number
}

export function BookMasonryGrid({ items, defaultShelfId, maxColumns }: BookMasonryGridProps) {
  const tier = useGridTier()
  const columnCount = Math.min(tier.columns, maxColumns ?? Infinity)
  const columns = useMemo(() => distributeIntoColumns(items, columnCount), [items, columnCount])

  return (
    <div className="flex" style={gutterStyle({ ...tier, columns: columnCount })}>
      {columns.map((column, columnIndex) => (
        <div key={columnIndex} className={`flex flex-1 flex-col ${COLUMN_GAP}`}>
          {column.map((book) => (
            <BookCard key={book.book_id} book={book} defaultShelfId={defaultShelfId} />
          ))}
        </div>
      ))}
    </div>
  )
}

/** Skeleton grid matching the same column distribution, so the real grid
 * doesn't visibly reflow the moment data arrives (spec §12.4). */
export function BookMasonrySkeleton({ count = 12 }: { count?: number }) {
  const tier = useGridTier()
  const placeholderIds = useMemo(() => Array.from({ length: count }, (_, i) => i), [count])
  const columns = useMemo(
    () => distributeIntoColumns(placeholderIds, tier.columns),
    [placeholderIds, tier.columns],
  )

  return (
    <div className="flex" style={gutterStyle(tier)} aria-hidden="true">
      {columns.map((column, columnIndex) => (
        <div key={columnIndex} className={`flex flex-1 flex-col ${COLUMN_GAP}`}>
          {column.map((id) => (
            <CardSkeleton key={id} />
          ))}
        </div>
      ))}
    </div>
  )
}
