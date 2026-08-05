/** Loading placeholder matching `BookCard`'s rough shape (spec §12.4:
 * "skeletons"). `animate-pulse` is neutralized globally for
 * `prefers-reduced-motion` by `index.css`'s base layer (spec §12.12). */
export function CardSkeleton() {
  return (
    <div className="animate-pulse">
      <div className="aspect-[2/3] w-full rounded-md bg-surface" />
      <div className="mt-2 h-4 w-3/4 rounded bg-surface" />
      <div className="mt-1 h-3 w-1/2 rounded bg-surface" />
    </div>
  )
}
