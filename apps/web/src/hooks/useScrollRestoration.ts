import { useEffect } from 'react'

const STORAGE_PREFIX = 'bookshelf:scroll:'

/**
 * Manual scroll restoration keyed by a caller-supplied id (spec §12.4).
 * React Router's built-in `<ScrollRestoration>` only exists for the
 * data-router API (`createBrowserRouter`); this app uses declarative
 * `<BrowserRouter>` (the modal-route pattern for book detail needs the
 * background page to stay mounted underneath the dialog, which the
 * declarative router does more simply), so this is done by hand instead.
 *
 * Note this only matters for a genuine unmount/remount of the caller (e.g.
 * navigating to Home, away, and back via the nav rail) — opening a book's
 * detail view as a modal never unmounts the page underneath it, so that
 * path preserves scroll position for free, with no help from this hook.
 */
export function useScrollRestoration(key: string) {
  useEffect(() => {
    const saved = sessionStorage.getItem(STORAGE_PREFIX + key)
    if (saved) {
      window.scrollTo(0, Number(saved))
    }

    function handleScroll() {
      sessionStorage.setItem(STORAGE_PREFIX + key, String(window.scrollY))
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [key])
}
