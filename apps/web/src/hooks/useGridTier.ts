import { useEffect, useState } from 'react'

export interface GridTier {
  /** How many books are on screen. */
  columns: number
  /** How large they are: the share of the row's width (percent) given over
   * to gutters in total, split evenly across the `columns - 1` gaps. A card
   * ends up at `(100 - gutterShare) / columns` percent of the row. */
  gutterShare: number
}

/**
 * Responsive masonry tiers (spec §12.5). Spec gives ranges, not exact
 * breakpoints ("wide desktop 7-8; desktop 5-6; tablet 3-4; mobile 2; narrow
 * 1-2") — this picks one concrete value per range and one concrete pixel
 * breakpoint per tier, a genuinely underspecified detail documented here
 * and in docs/implementation/plan.md's risk log. Pixel breakpoints line up
 * with Tailwind's default `md`/`lg`/`2xl` so the grid's tiers match every
 * other responsive class in the app.
 *
 * The two numbers are independent dials: **columns decide how many books
 * are visible, `gutterShare` decides how large they are.** Both are per
 * tier because they have to be — column counts are integers, so a uniform
 * change in cover size across tiers can only come from the gutter. Wide
 * desktop carries the larger gutter share purely because it also dropped a
 * column (8 → 7); without it, losing that column would have made its
 * covers ~14% larger rather than the ~8% every tier actually gets.
 */
const TIERS: readonly [minWidth: number, tier: GridTier][] = [
  [1536, { columns: 7, gutterShare: 29.1 }], // wide desktop (Tailwind 2xl)
  [1024, { columns: 6, gutterShare: 19 }], // desktop (Tailwind lg)
  [768, { columns: 4, gutterShare: 19 }], // tablet (Tailwind md)
  [480, { columns: 2, gutterShare: 19 }], // mobile
]
// A single column has no gutters to share out.
const NARROW_TIER: GridTier = { columns: 1, gutterShare: 0 }

function tierForWidth(width: number): GridTier {
  const tier = TIERS.find(([minWidth]) => width >= minWidth)
  return tier ? tier[1] : NARROW_TIER
}

export function useGridTier(): GridTier {
  const [tier, setTier] = useState(() => tierForWidth(window.innerWidth))

  useEffect(() => {
    function handleResize() {
      setTier(tierForWidth(window.innerWidth))
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return tier
}
