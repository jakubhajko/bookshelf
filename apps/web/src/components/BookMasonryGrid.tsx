import { useMemo } from 'react'
import { useColumnCount } from '../hooks/useColumnCount'
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
 * index into N column arrays (N from `useColumnCount`), each rendered as
 * its own vertical flex stack — not CSS multi-column layout, which
 * rebalances *every* item into new columns as the list grows and would
 * violate spec §12.4's "stable rendered order" the moment infinite scroll
 * appends a page. Round-robin's column assignment for existing items never
 * changes when new items are appended at the end, and unlike a
 * shortest-column-fill algorithm it doesn't need to measure real image
 * heights to decide placement.
 */
interface BookMasonryGridProps {
  items: BookCardData[]
  /** Forwarded to every card — shelf-discover context (spec §12.8:
   * "defaults Save to current shelf"). */
  defaultShelfId?: string
}

export function BookMasonryGrid({ items, defaultShelfId }: BookMasonryGridProps) {
  const columnCount = useColumnCount()
  const columns = useMemo(() => distributeIntoColumns(items, columnCount), [items, columnCount])

  return (
    <div className="flex gap-4">
      {columns.map((column, columnIndex) => (
        <div key={columnIndex} className="flex flex-1 flex-col gap-4">
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
  const columnCount = useColumnCount()
  const placeholderIds = useMemo(() => Array.from({ length: count }, (_, i) => i), [count])
  const columns = useMemo(
    () => distributeIntoColumns(placeholderIds, columnCount),
    [placeholderIds, columnCount],
  )

  return (
    <div className="flex gap-4" aria-hidden="true">
      {columns.map((column, columnIndex) => (
        <div key={columnIndex} className="flex flex-1 flex-col gap-4">
          {column.map((id) => (
            <CardSkeleton key={id} />
          ))}
        </div>
      ))}
    </div>
  )
}
