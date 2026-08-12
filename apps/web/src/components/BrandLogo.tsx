/**
 * The BookShelf wordmark.
 *
 * `public/logo.png` is the supplied artwork, cropped to its own bounds and
 * with the flat backdrop keyed out — the original was a 2000×2000 square
 * that was mostly empty and carried a baked-in near-black background, so
 * used as-is it would have rendered a postage stamp inside a faintly
 * mismatched dark rectangle. Keyed, it composites on any surface.
 *
 * `width`/`height` are the asset's intrinsic pixels so the browser knows
 * the aspect ratio before the image loads and the rail doesn't reflow;
 * callers size it with a Tailwind class (usually a width).
 */
export function BrandLogo({ className = 'w-24' }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="BookShelf"
      width={998}
      height={421}
      className={`h-auto ${className}`}
    />
  )
}
