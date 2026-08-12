import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'bookshelf:last-used-shelf-id'

/** Session-scoped "last used shelf" for the card Save quick-action (spec
 * §12.6: "remember last-used shelf during session"). `sessionStorage`
 * (cleared when the tab closes) is the closer match to "during session"
 * than plain in-memory state (lost on every unmount) or `localStorage`
 * (would outlive the session entirely).
 *
 * Shared across every subscriber via `useSyncExternalStore` over a
 * module-level listener set — the same plain-store shape `toastStore` uses
 * — rather than each caller holding its own `useState` seeded from
 * `sessionStorage` at mount. Per-instance state made the value stale the
 * moment it was set: every card already on screen kept whatever it read
 * when it mounted, so choosing a shelf on one card left every other card's
 * quick-Save target (and, since it names that shelf, its shelf pill)
 * pointing at the old value until it happened to remount. */

type Listener = () => void
let listeners: Listener[] = []

function subscribe(listener: Listener): () => void {
  listeners = [...listeners, listener]
  return () => {
    listeners = listeners.filter((l) => l !== listener)
  }
}

/** `sessionStorage` itself is the store; no in-module copy to keep in
 * sync. `useSyncExternalStore`'s "return a cached snapshot" rule guards
 * against re-render loops from freshly allocated objects — this returns a
 * string or null, which `Object.is` compares by value, so reading live is
 * both safe and one less thing that can drift (a test or another tab
 * writing the key directly is picked up on the next render). */
function getSnapshot(): string | null {
  return sessionStorage.getItem(STORAGE_KEY)
}

export function useLastUsedShelf() {
  const shelfId = useSyncExternalStore(subscribe, getSnapshot)

  const setShelfId = useCallback((id: string) => {
    sessionStorage.setItem(STORAGE_KEY, id)
    for (const listener of listeners) listener()
  }, [])

  return [shelfId, setShelfId] as const
}
