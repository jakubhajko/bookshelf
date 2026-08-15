import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { queryKeys } from '../api/queryKeys'
import * as searchApi from '../api/search'
import * as tasteSeedsApi from '../api/tasteSeeds'
import { BookCover } from '../components/BookCover'

/** rec-spec §6 "encourage roughly 3-10 selections" — encouragement only.
 * The endpoint sets no minimum and neither does this page: the primary
 * action is always enabled, because a reader who picked two books has told
 * us more than one who abandoned onboarding rather than pick a third. */
const SUGGESTED_MIN = 3
const SEARCH_LIMIT = 24

/**
 * Cold-start taste selection (rec-spec §6, ADR-0019).
 *
 * A skippable multi-select over book search. What it produces is *taste
 * seeds*, which ADR-0019 is emphatic are their own kind of evidence: not
 * ratings, because the reader has not claimed to have read anything, and
 * not shelf saves, because they have not filed anything. That distinction
 * is the reason this page exists rather than asking new readers to rate
 * five books, which would put five false "I have read this" claims into
 * their profile on their first minute in the product.
 *
 * Verified live in R8: five seeds and nothing else change 11 of 12 Home
 * results, so completing this genuinely personalizes the feed immediately.
 */
export function OnboardingPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [selected, setSelected] = useState<Map<number, string>>(new Map())

  // Existing seeds, so returning here shows what was already chosen rather
  // than an empty page that would silently replace them on save.
  const existing = useQuery({
    queryKey: queryKeys.tasteSeeds.list,
    queryFn: tasteSeedsApi.listTasteSeeds,
  })

  useEffect(() => {
    if (!existing.data) return
    setSelected(
      new Map(existing.data.items.map((item) => [item.book_id, item.title] as const)),
    )
  }, [existing.data])

  const results = useQuery({
    queryKey: queryKeys.search.results(submitted),
    queryFn: () => searchApi.searchBooks(submitted, { limit: SEARCH_LIMIT }),
    enabled: submitted.length > 0,
  })

  const save = useMutation({
    mutationFn: (bookIds: number[]) => tasteSeedsApi.syncTasteSeeds(bookIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tasteSeeds.list })
      // The feed is the whole point of having done this, so it must not be
      // served from a cache built before the reader had any taste.
      await queryClient.invalidateQueries({ queryKey: queryKeys.recommendations.home })
      await navigate('/')
    },
  })

  const toggle = (bookId: number, title: string) => {
    setSelected((current) => {
      const next = new Map(current)
      if (next.has(bookId)) next.delete(bookId)
      else next.set(bookId, title)
      return next
    })
  }

  const count = selected.size
  const items = results.data?.items ?? []

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold text-text">What do you like reading?</h1>
      <p className="mt-2 max-w-2xl text-sm text-text-muted">
        Pick a few books you enjoy and we&apos;ll use them to start your recommendations.
        You can skip this and it will still work — your shelves and ratings tell us just as
        much.
      </p>

      <form
        className="mt-6 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setSubmitted(query.trim())
        }}
      >
        <label htmlFor="onboarding-search" className="sr-only">
          Search for books or authors
        </label>
        <input
          id="onboarding-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search for a book or author"
          className="min-w-0 flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent"
        />
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text focus:outline-none focus:ring-2 focus:ring-accent"
        >
          Search
        </button>
      </form>

      <section aria-live="polite" className="mt-8">
        {submitted.length === 0 && (
          <p className="py-12 text-center text-sm text-text-muted">
            Search above to find books you like.
          </p>
        )}

        {submitted.length > 0 && results.isLoading && (
          <p className="py-12 text-center text-sm text-text-muted">Searching…</p>
        )}

        {submitted.length > 0 && results.isError && !results.isLoading && (
          <div className="py-12 text-center">
            <p className="text-sm text-text-muted">Couldn&apos;t load search results.</p>
            <button
              type="button"
              onClick={() => void results.refetch()}
              className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
            >
              Retry
            </button>
          </div>
        )}

        {submitted.length > 0 && !results.isLoading && !results.isError && items.length === 0 && (
          <p className="py-12 text-center text-sm text-text-muted">
            No books found for &ldquo;{submitted}&rdquo;.
          </p>
        )}

        {items.length > 0 && (
          <ul
            aria-label="Search results"
            className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6"
          >
            {items.map((item) => {
              const isSelected = selected.has(item.book_id)
              return (
                <li key={item.book_id}>
                  {/* A real button, not a clickable div: this is the only
                      control on the page and it has to be reachable and
                      operable from the keyboard. `aria-pressed` is what
                      makes the toggle state audible to a screen reader —
                      the ring alone only communicates to people who can
                      see it. */}
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => toggle(item.book_id, item.title)}
                    className={`group w-full rounded-md text-left focus:outline-none focus:ring-2 focus:ring-accent ${
                      isSelected ? 'ring-2 ring-accent' : ''
                    }`}
                  >
                    <BookCover
                      objectKey={item.cover_object_key}
                      title={item.title}
                      author={item.primary_author_name}
                    />
                    <span className="mt-1 line-clamp-2 block text-xs text-text">
                      {item.title}
                    </span>
                    {item.primary_author_name && (
                      <span className="line-clamp-1 block text-xs text-text-muted">
                        {item.primary_author_name}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <div className="sticky bottom-0 mt-10 flex flex-wrap items-center gap-3 border-t border-border bg-background py-4">
        <p className="flex-1 text-sm text-text-muted" role="status">
          {count === 0
            ? 'Nothing selected yet.'
            : `${count} book${count === 1 ? '' : 's'} selected` +
              (count < SUGGESTED_MIN ? ` — ${SUGGESTED_MIN} or more works best.` : '.')}
        </p>

        <button
          type="button"
          onClick={() => void navigate('/')}
          disabled={save.isPending}
          className="rounded-md border border-border px-4 py-2 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
        >
          Skip for now
        </button>
        <button
          type="button"
          onClick={() => save.mutate([...selected.keys()])}
          disabled={save.isPending}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
        >
          {save.isPending ? 'Saving…' : 'Continue'}
        </button>
      </div>

      {save.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Couldn&apos;t save your selection. Please try again.
        </p>
      )}
    </main>
  )
}
