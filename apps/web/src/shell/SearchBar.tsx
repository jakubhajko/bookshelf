import * as Popover from '@radix-ui/react-popover'
import { useQuery } from '@tanstack/react-query'
import { Search as SearchIcon } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as searchApi from '../api/search'
import { useRecentSearches } from '../hooks/useRecentSearches'

const SUGGESTION_LIMIT = 5
const DEBOUNCE_MS = 300

/**
 * Large sticky search bar with debounced suggestions and recent searches
 * (spec §12.10). There's no separate suggestions endpoint (spec §9.6 lists
 * exactly one search route) — suggestions are the same
 * `GET /search/books` called with a small `limit`, exactly what the full
 * results page will call next. Individual title/author suggestions
 * navigate straight to that book; a recent-search chip or a plain Enter
 * navigates to the full results page instead.
 *
 * Built on Radix `Popover.Anchor` (not `Trigger`) — the popover is driven
 * entirely by focus/typing on the input, not a click-to-toggle trigger,
 * and `onOpenAutoFocus` is suppressed so opening it never steals focus
 * away from the input the visitor is typing into.
 */
export function SearchBar() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') ?? '')
  const [debouncedQuery, setDebouncedQuery] = useState(query.trim())
  const [open, setOpen] = useState(false)
  const [recentSearches, addRecentSearch] = useRecentSearches()

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query.trim()), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  const { data } = useQuery({
    queryKey: queryKeys.search.results(`suggest:${debouncedQuery}`),
    queryFn: () => searchApi.searchBooks(debouncedQuery, { limit: SUGGESTION_LIMIT }),
    enabled: debouncedQuery.length > 0,
    staleTime: 30_000,
  })
  const suggestions = debouncedQuery ? (data?.items ?? []) : []
  const trimmedQuery = query.trim()

  function runSearch(rawQuery: string) {
    const trimmed = rawQuery.trim()
    if (!trimmed) return
    addRecentSearch(trimmed)
    setOpen(false)
    void navigate(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    runSearch(query)
  }

  function goToBook(bookId: number) {
    setOpen(false)
    void navigate(`/books/${bookId}`)
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Anchor asChild>
        <form onSubmit={handleSubmit} role="search" className="flex-1">
          <label htmlFor="site-search" className="sr-only">
            Search books
          </label>
          {/* Spans the whole width of its section (spec §12.10: "large").
            * Borderless and unshadowed — it reads as a recessed band in
            * the page rather than a floating box, separated from the
            * background by fill alone. `rounded-lg` against the covers'
            * `rounded-md` isn't the same number, but at this height the
            * two read as the same family. */}
          <div className="relative">
            <SearchIcon
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2 text-text-muted"
            />
            <input
              id="site-search"
              type="search"
              placeholder="Search books or authors"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setOpen(true)
              }}
              onFocus={() => setOpen(true)}
              autoComplete="off"
              className="h-11 w-full rounded-lg bg-surface pr-4 pl-11 text-sm text-text placeholder:text-text-muted focus:ring-2 focus:ring-accent focus:outline-none"
            />
          </div>
        </form>
      </Popover.Anchor>

      <Popover.Portal>
        <Popover.Content
          onOpenAutoFocus={(event) => event.preventDefault()}
          align="start"
          sideOffset={8}
          className="z-20 w-[var(--radix-popover-trigger-width)] rounded-lg border border-border bg-surface p-1 shadow-lg"
        >
          {trimmedQuery.length === 0 && recentSearches.length > 0 && (
            <div>
              <p className="px-3 py-1.5 text-xs font-medium text-text-muted">Recent searches</p>
              {recentSearches.map((recentQuery) => (
                <button
                  key={recentQuery}
                  type="button"
                  onClick={() => runSearch(recentQuery)}
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-sm text-text hover:bg-surface-hover"
                >
                  <SearchIcon aria-hidden className="h-3.5 w-3.5 text-text-muted" />
                  {recentQuery}
                </button>
              ))}
            </div>
          )}

          {trimmedQuery.length > 0 && suggestions.length > 0 && (
            <div>
              {suggestions.map((item) => (
                <button
                  key={item.book_id}
                  type="button"
                  onClick={() => goToBook(item.book_id)}
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-sm text-text hover:bg-surface-hover"
                >
                  <span className="truncate">{item.title}</span>
                  {item.primary_author_name && (
                    <span className="shrink-0 truncate text-xs text-text-muted">
                      {item.primary_author_name}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          {trimmedQuery.length > 0 && debouncedQuery === trimmedQuery && suggestions.length === 0 && (
            <p className="px-3 py-2 text-sm text-text-muted">
              No quick matches — press Enter to see full results.
            </p>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
