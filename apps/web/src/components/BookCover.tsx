import { useState } from 'react'
import { coverUrl } from '../api/covers'

interface BookCoverProps {
  objectKey: string | null
  title: string
  author: string | null
}

/** Preserves the real cover's aspect ratio (spec §12.5) — no forced crop;
 * variable height per card is what makes the grid a masonry layout at all.
 * Missing or failed-to-load covers fall back to a fixed-ratio title/author
 * placeholder tile (spec §12.5's other half of that same sentence). */
export function BookCover({ objectKey, title, author }: BookCoverProps) {
  const url = coverUrl(objectKey)
  const [failed, setFailed] = useState(false)

  if (!url || failed) {
    return (
      <div className="flex aspect-[2/3] w-full flex-col items-center justify-center gap-1 rounded-md bg-surface p-3 text-center">
        <span className="line-clamp-3 text-sm font-medium text-text">{title}</span>
        {author && <span className="line-clamp-1 text-xs text-text-muted">{author}</span>}
      </div>
    )
  }

  return (
    <img
      src={url}
      alt={`Cover of ${title}${author ? ` by ${author}` : ''}`}
      className="w-full rounded-md bg-surface"
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}
