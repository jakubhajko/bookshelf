import { beforeEach, describe, expect, it } from 'vitest'
import {
  SESSION_IDLE_TIMEOUT_MS,
  clearBrowsingSession,
  getBrowsingSessionId,
} from './browsingSession'

/** Browsing-session identity and rotation (rec-spec §4.1, ADR-0015).
 *
 * `now` is injected rather than faked with timers: the rule under test is
 * "rotate after ~30 minutes of *inactivity*", and passing timestamps
 * states that directly instead of simulating half an hour. */
describe('browsing session', () => {
  beforeEach(() => {
    clearBrowsingSession()
  })

  it('generates an id and reuses it within the idle window', () => {
    const start = 1_000_000
    const first = getBrowsingSessionId(start)

    expect(first).toBeTruthy()
    expect(getBrowsingSessionId(start + 60_000)).toBe(first)
    expect(getBrowsingSessionId(start + SESSION_IDLE_TIMEOUT_MS)).toBe(first)
  })

  it('rotates after the idle timeout elapses with no activity', () => {
    const start = 1_000_000
    const first = getBrowsingSessionId(start)

    const second = getBrowsingSessionId(start + SESSION_IDLE_TIMEOUT_MS + 1)

    expect(second).not.toBe(first)
  })

  it('treats each read as activity, so continuous use never rotates', () => {
    // The distinction that makes this an *inactivity* timeout rather than
    // a session lifetime: a reader browsing for hours stays in one
    // session, because every attributed action refreshes the clock.
    const start = 1_000_000
    const first = getBrowsingSessionId(start)

    let now = start
    for (let i = 0; i < 10; i++) {
      now += SESSION_IDLE_TIMEOUT_MS - 1_000
      expect(getBrowsingSessionId(now)).toBe(first)
    }
  })

  it('starts a fresh session when storage is empty', () => {
    const first = getBrowsingSessionId(1_000_000)
    clearBrowsingSession()

    expect(getBrowsingSessionId(1_000_001)).not.toBe(first)
  })

  it('recovers from corrupted storage instead of throwing', () => {
    // Attribution is best-effort: a mangled value must degrade to a new
    // session, never break the action the caller was performing.
    sessionStorage.setItem('bookshelf:browsing-session', 'not json{{')

    expect(() => getBrowsingSessionId(1_000_000)).not.toThrow()
    expect(getBrowsingSessionId(1_000_000)).toBeTruthy()
  })

  it('is not the auth session cookie', () => {
    // rec-spec §4.1 forbids reusing the 30-day auth `sid`. Belt-and-braces
    // check that nothing here reads document.cookie at all.
    document.cookie = 'sid=auth-session-value'
    const id = getBrowsingSessionId(1_000_000)

    expect(id).not.toContain('auth-session-value')
    expect(sessionStorage.getItem('bookshelf:browsing-session')).not.toContain(
      'auth-session-value',
    )
  })
})
