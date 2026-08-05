import { Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { AvatarMenu } from './AvatarMenu'

/** Sticky top bar: large search field + avatar menu (spec §12.2). The
 * search *page* is a Phase 8 placeholder for now — this only owns getting
 * a query into the URL, which is real regardless of what renders there. */
export function TopBar() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') ?? '')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) {
      void navigate(`/search?q=${encodeURIComponent(trimmed)}`)
    }
  }

  return (
    <header className="sticky top-0 z-10 flex items-center gap-4 border-b border-border bg-topbar px-4 py-3 md:pl-24">
      <form onSubmit={handleSubmit} role="search" className="flex-1">
        <label htmlFor="site-search" className="sr-only">
          Search books
        </label>
        <div className="relative max-w-xl">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-text-muted"
          />
          <input
            id="site-search"
            type="search"
            placeholder="Search books or authors"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-full rounded-full border border-border bg-surface py-2 pr-4 pl-10 text-sm text-text placeholder:text-text-muted focus:ring-2 focus:ring-accent focus:outline-none"
          />
        </div>
      </form>
      <AvatarMenu />
    </header>
  )
}
