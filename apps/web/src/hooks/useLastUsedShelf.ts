import { useCallback, useState } from 'react'

const STORAGE_KEY = 'bookshelf:last-used-shelf-id'

/** Session-scoped "last used shelf" for the card Save quick-action (spec
 * §12.6: "remember last-used shelf during session"). `sessionStorage`
 * (cleared when the tab closes) is the closer match to "during session"
 * than plain in-memory state (lost on every unmount) or `localStorage`
 * (would outlive the session entirely). */
export function useLastUsedShelf() {
  const [shelfId, setShelfIdState] = useState<string | null>(() =>
    sessionStorage.getItem(STORAGE_KEY),
  )

  const setShelfId = useCallback((id: string) => {
    sessionStorage.setItem(STORAGE_KEY, id)
    setShelfIdState(id)
  }, [])

  return [shelfId, setShelfId] as const
}
