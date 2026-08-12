import { Star } from 'lucide-react'

/**
 * Read-only rendering of a rating as five stars, half-steps included (spec
 * §5.1's public 0.5–5.0 scale). The card's answer to "how did I rate this?"
 * at a glance, in place of a numeral that had to be read.
 *
 * Half stars use the same two-stacked-glyphs-plus-`clipPath` technique as
 * the interactive `RatingStars`, so a 3.5 reads identically whether it's
 * being set or just shown.
 */
export function RatingDisplay({ value, className = '' }: { value: number; className?: string }) {
  return (
    <div
      className={`flex gap-0.5 ${className}`}
      role="img"
      aria-label={`You rated this ${value} out of 5`}
    >
      {Array.from({ length: 5 }, (_, starIndex) => {
        const fill =
          value >= starIndex + 1 ? 'full' : value >= starIndex + 0.5 ? 'half' : 'none'

        return (
          <span key={starIndex} className="relative inline-block h-4 w-4">
            <Star aria-hidden className="absolute inset-0 h-4 w-4 text-border" />
            {fill !== 'none' && (
              <Star
                aria-hidden
                fill="currentColor"
                className="absolute inset-0 h-4 w-4 text-accent"
                style={fill === 'half' ? { clipPath: 'inset(0 50% 0 0)' } : undefined}
              />
            )}
          </span>
        )
      })}
    </div>
  )
}
