import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import {
  recordSubmittedSearch,
  resetSubmittedSearch,
  useSubmittedSearchQueryId,
} from './submittedSearch'

/**
 * Recommender Phase R1: carrying `search_query_id` from the submit site to
 * the results page (rec-spec §4.4).
 *
 * The failure this guards against is attributing an open to the *wrong*
 * search — a fabricated causal link is worse than a missing one
 * (ADR-0015).
 */

const QUERY_ID = 'ffffffff-1111-2222-3333-444444444444'

function mockRecordSucceeds(id = QUERY_ID) {
  return vi.spyOn(apiClient, 'POST').mockResolvedValue({
    data: { id, query_text: 'dune', occurred_at: new Date().toISOString() },
    // openapi-fetch's response envelope; only `data` is read here.
    error: undefined,
    response: new Response(),
  } as never)
}

describe('submitted search attribution', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    resetSubmittedSearch()
  })

  it('exposes the id to the matching query once the write lands', async () => {
    mockRecordSucceeds()
    const { result } = renderHook(() => useSubmittedSearchQueryId('dune'))

    expect(result.current).toBeUndefined()
    recordSubmittedSearch('dune')

    await waitFor(() => expect(result.current).toBe(QUERY_ID))
  })

  it('does not attribute a different query to that id', async () => {
    mockRecordSucceeds()
    const { result } = renderHook(() => useSubmittedSearchQueryId('hyperion'))

    recordSubmittedSearch('dune')

    // Give the write time to land, then confirm it still isn't claimed by
    // the unrelated query.
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(result.current).toBeUndefined()
  })

  it('clears the previous id immediately when a new search is submitted', async () => {
    mockRecordSucceeds()
    const { result } = renderHook(() => useSubmittedSearchQueryId('dune'))
    recordSubmittedSearch('dune')
    await waitFor(() => expect(result.current).toBe(QUERY_ID))

    // A second search must not leave the first one's id attributable while
    // its own write is still in flight.
    vi.spyOn(apiClient, 'POST').mockReturnValue(new Promise(() => {}) as never)
    recordSubmittedSearch('hyperion')

    await waitFor(() => expect(result.current).toBeUndefined())
  })

  it('ignores blank submissions', () => {
    const post = mockRecordSucceeds()
    recordSubmittedSearch('   ')
    expect(post).not.toHaveBeenCalled()
  })

  it('survives a failed write without throwing', async () => {
    vi.spyOn(apiClient, 'POST').mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useSubmittedSearchQueryId('dune'))

    expect(() => recordSubmittedSearch('dune')).not.toThrow()
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(result.current).toBeUndefined()
  })

  it('sends the browsing session with the submitted search', async () => {
    const post = mockRecordSucceeds()
    recordSubmittedSearch('dune')

    await waitFor(() => expect(post).toHaveBeenCalled())
    const body = post.mock.calls[0]?.[1] as { body: Record<string, unknown> }
    expect(body.body.query_text).toBe('dune')
    expect(body.body.session_id).toEqual(expect.any(String))
    expect(body.body.surface).toBe('search')
  })
})
