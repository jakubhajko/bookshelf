/**
 * Short-lived browsing session (rec-spec §4.1, ADR-0015).
 *
 * A correlator for "one sitting" — the unit a future session-aware
 * recommender reasons over. Deliberately **not** the authentication `sid`:
 * that cookie lasts 30 days, which is the wrong granularity for session
 * recency, and it's a security credential that has no business being
 * copied into analytics attribution.
 *
 * `sessionStorage`, not `localStorage`, so each tab gets its own session —
 * two tabs open on different topics are genuinely two browsing sessions,
 * and `localStorage` would merge them into one incoherent stream.
 *
 * A plain module rather than a hook: attribution is attached inside
 * `api/*.ts` call sites and event helpers, most of which aren't React
 * components. Same reasoning as `toast/toastStore.ts`.
 */

const STORAGE_KEY = 'bookshelf:browsing-session'

/** rec-spec §4.1: "Rotate after approximately 30 minutes of inactivity." */
export const SESSION_IDLE_TIMEOUT_MS = 30 * 60 * 1000

interface StoredSession {
  id: string
  lastActiveAt: number
}

function readStored(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      typeof (parsed as StoredSession).id === 'string' &&
      typeof (parsed as StoredSession).lastActiveAt === 'number'
    ) {
      return parsed as StoredSession
    }
    return null
  } catch {
    // Private-mode storage denial, a quota error, or hand-corrupted JSON.
    // A missing browsing session degrades attribution; it must never break
    // the action the caller was actually trying to perform.
    return null
  }
}

function write(session: StoredSession): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // See readStored: best-effort by design.
  }
}

/**
 * The current browsing-session id, rotating it first if the last activity
 * was longer ago than the idle timeout. Calling this *is* the activity
 * signal — every attributed action touches the timestamp, so a session
 * stays alive as long as the reader keeps doing things and expires on a
 * genuine gap rather than on wall-clock age.
 *
 * `now` is injectable purely so the rotation rule is testable without
 * fake timers or a 30-minute test.
 */
export function getBrowsingSessionId(now: number = Date.now()): string {
  const stored = readStored()
  if (stored && now - stored.lastActiveAt <= SESSION_IDLE_TIMEOUT_MS) {
    write({ id: stored.id, lastActiveAt: now })
    return stored.id
  }
  const session = { id: crypto.randomUUID(), lastActiveAt: now }
  write(session)
  return session.id
}

/** Test seam only — exported so tests can start from a known-empty state
 * without reaching into the storage key string themselves. */
export function clearBrowsingSession(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // See readStored.
  }
}
