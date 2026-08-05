import { useEffect, useRef } from 'react'

/**
 * A ref to attach to a sentinel element at the bottom of an infinite-scroll
 * list; calls `onIntersect` once it becomes visible, skipped while
 * `disabled` (already fetching, or no next page). Extracted once Home,
 * Shelf-books, Shelf-discover, and Search all needed the identical
 * `IntersectionObserver` wiring.
 */
export function useInfiniteScrollSentinel(onIntersect: () => void, disabled: boolean) {
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !disabled) {
          onIntersect()
        }
      },
      { rootMargin: '400px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [onIntersect, disabled])

  return sentinelRef
}
