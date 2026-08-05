import { useState } from 'react'

const STORAGE_KEY = 'bookshelf:recent-searches'
const MAX_RECENT_SEARCHES = 5

function readRecentSearches(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

/** Client-only "recent searches" (spec §12.10) — most-recent-first,
 * deduplicated case-insensitively, capped at five. No backend concept;
 * the search endpoint itself is stateless per request. */
export function useRecentSearches() {
  const [recentSearches, setRecentSearches] = useState<string[]>(() => readRecentSearches())

  function addRecentSearch(query: string) {
    const trimmed = query.trim()
    if (!trimmed) return
    const next = [
      trimmed,
      ...recentSearches.filter((existing) => existing.toLowerCase() !== trimmed.toLowerCase()),
    ].slice(0, MAX_RECENT_SEARCHES)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    setRecentSearches(next)
  }

  return [recentSearches, addRecentSearch] as const
}
