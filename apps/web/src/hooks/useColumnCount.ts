import { useEffect, useState } from 'react'

/**
 * Column counts for the responsive masonry grid (spec §12.5). Spec gives
 * ranges, not exact breakpoints ("wide desktop 7-8; desktop 5-6; tablet
 * 3-4; mobile 2; narrow 1-2") — this picks one concrete value per range and
 * one concrete pixel breakpoint per tier, a genuinely underspecified detail
 * documented here and in docs/implementation/plan.md's risk log. Pixel
 * breakpoints line up with Tailwind's default `md`/`lg`/`2xl` so the grid's
 * tiers match every other responsive class in the app.
 */
const TIERS: readonly [minWidth: number, columns: number][] = [
  [1536, 8], // wide desktop (Tailwind 2xl)
  [1024, 6], // desktop (Tailwind lg)
  [768, 4], // tablet (Tailwind md)
  [480, 2], // mobile
]
const NARROW_COLUMNS = 1

function columnsForWidth(width: number): number {
  const tier = TIERS.find(([minWidth]) => width >= minWidth)
  return tier ? tier[1] : NARROW_COLUMNS
}

export function useColumnCount(): number {
  const [columns, setColumns] = useState(() => columnsForWidth(window.innerWidth))

  useEffect(() => {
    function handleResize() {
      setColumns(columnsForWidth(window.innerWidth))
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return columns
}
