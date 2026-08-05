import { Star } from 'lucide-react'
import { useId, useState } from 'react'

interface RatingStarsProps {
  value: number | null
  onRate: (value: number) => void
  onRemove: () => void
  disabled?: boolean
}

/**
 * Five stars, ten accessible half-step values, remove action (spec §12.7).
 * Built from native `<input type="radio">` elements sharing one `name` —
 * the browser gives roving-tabindex arrow-key navigation and Space/click
 * selection for free that way (ADR-0008: accessible primitives over
 * hand-rolled widgets), so there's no custom keyboard handling here at all.
 * Each star is two stacked half-width radio controls (left = X.5, right =
 * X.0); the visible star glyphs are purely decorative (`aria-hidden`), with
 * the real accessible name ("4 stars", "4.5 stars", ...) on each control's
 * visually-hidden label text.
 */
export function RatingStars({ value, onRate, onRemove, disabled }: RatingStarsProps) {
  const [hoverValue, setHoverValue] = useState<number | null>(null)
  const name = useId()
  const displayValue = hoverValue ?? value ?? 0

  return (
    <div>
      <div
        role="radiogroup"
        aria-label="Your rating"
        className="inline-flex gap-0.5"
        onMouseLeave={() => setHoverValue(null)}
      >
        {Array.from({ length: 5 }, (_, starIndex) => {
          const halfValue = starIndex + 0.5
          const fullValue = starIndex + 1
          const filled = displayValue >= fullValue ? 'full' : displayValue >= halfValue ? 'half' : 'none'

          return (
            <span key={starIndex} className="relative inline-block h-7 w-7">
              <Star aria-hidden className="absolute inset-0 h-7 w-7 text-border" />
              {filled !== 'none' && (
                <Star
                  aria-hidden
                  fill="currentColor"
                  className="absolute inset-0 h-7 w-7 text-accent"
                  style={filled === 'half' ? { clipPath: 'inset(0 50% 0 0)' } : undefined}
                />
              )}

              <label className="absolute inset-y-0 left-0 block h-full w-1/2 cursor-pointer">
                <input
                  type="radio"
                  name={name}
                  checked={value === halfValue}
                  disabled={disabled}
                  onChange={() => onRate(halfValue)}
                  onFocus={() => setHoverValue(halfValue)}
                  onBlur={() => setHoverValue(null)}
                  className="sr-only"
                />
                <span className="sr-only">{halfValue} stars</span>
              </label>
              <label className="absolute inset-y-0 right-0 block h-full w-1/2 cursor-pointer">
                <input
                  type="radio"
                  name={name}
                  checked={value === fullValue}
                  disabled={disabled}
                  onChange={() => onRate(fullValue)}
                  onFocus={() => setHoverValue(fullValue)}
                  onBlur={() => setHoverValue(null)}
                  className="sr-only"
                />
                <span className="sr-only">{fullValue === 1 ? '1 star' : `${fullValue} stars`}</span>
              </label>
            </span>
          )
        })}
      </div>

      {value !== null && (
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="mt-1 block text-xs text-text-muted underline hover:text-text"
        >
          Remove rating
        </button>
      )}
    </div>
  )
}
