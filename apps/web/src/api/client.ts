/**
 * Typed API client generated from the FastAPI OpenAPI schema (spec §16,
 * ADR-0002; `make generate-api-client`), wrapping `openapi-fetch` with the
 * three cross-cutting concerns every call needs:
 *
 * 1. Credentialed requests (`credentials: 'include'`) so the HttpOnly
 *    access/refresh cookies flow (spec §6.4).
 * 2. The readable `csrf_token` cookie mirrored into the `X-CSRF-Token`
 *    header on mutating requests (spec §6.5) — except the three auth routes
 *    that run before any session exists to bind a CSRF token to
 *    (register/login/refresh; see `book_app.modules.auth.dependencies`).
 * 3. Transparent single-flight refresh-and-retry on a 401: the access
 *    token is short-lived (~15 min, spec §6.4) by design, so without this
 *    every API call would start failing partway through an otherwise-active
 *    session.
 */
import createClient, { type Middleware } from 'openapi-fetch'
import { showToast } from '../toast/toastStore'
import type { paths } from './generated/schema'
import { queryClient } from './queryClient'
import { queryKeys } from './queryKeys'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const REFRESH_PATH = '/api/v1/auth/refresh'
const BOOTSTRAP_PATH = '/api/v1/auth/me'
const CSRF_EXEMPT_PATHS = new Set(['/api/v1/auth/register', '/api/v1/auth/login', REFRESH_PATH])
const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export class ApiError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    const path = new URL(request.url).pathname
    if (MUTATING_METHODS.has(request.method) && !CSRF_EXEMPT_PATHS.has(path)) {
      const token = readCookie('csrf_token')
      if (token) {
        request.headers.set('X-CSRF-Token', token)
      }
    }
    return request
  },
}

// Deduplicates concurrent refresh attempts into one in-flight request —
// several queries can 401 at nearly the same moment when an access token
// expires mid-session, and each should await the *same* refresh rather than
// each rotating/racing their own.
let refreshInFlight: Promise<boolean> | null = null

function ensureFreshSession(): Promise<boolean> {
  refreshInFlight ??= fetch(`${API_BASE_URL}${REFRESH_PATH}`, {
    method: 'POST',
    credentials: 'include',
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

// Registered after csrfMiddleware, so the clone it retries with already
// carries the CSRF header that middleware set.
const pendingClones = new Map<string, Request>()

const sessionRefreshMiddleware: Middleware = {
  onRequest({ request, id }) {
    pendingClones.set(id, request.clone())
    return request
  },
  async onResponse({ request, response, id }) {
    const clone = pendingClones.get(id)
    pendingClones.delete(id)

    if (response.status !== 401) return undefined
    const path = new URL(request.url).pathname
    if (CSRF_EXEMPT_PATHS.has(path) || !clone) return undefined

    const refreshed = await ensureFreshSession()
    if (refreshed) return fetch(clone)

    // Refresh genuinely failed. `/auth/me`'s own 401 is the ordinary "not
    // logged in yet" bootstrap signal (already handled by
    // `fetchCurrentUser` returning `null`) — everything else in this app
    // only ever runs after `RequireAuth` has already confirmed a session
    // exists, so a 401-after-failed-refresh anywhere else means the
    // session just died mid-use (spec §15: "login redirect after refresh
    // failure"). Clearing the cached user here is what actually triggers
    // the redirect — `RequireAuth` reacts to it, nothing here navigates
    // directly.
    if (path !== BOOTSTRAP_PATH) {
      queryClient.setQueryData(queryKeys.auth.me, null)
      showToast('Your session expired. Please log in again.', 'error')
    }
    return undefined
  },
}

export const apiClient = createClient<paths>({
  baseUrl: API_BASE_URL,
  credentials: 'include',
})
apiClient.use(csrfMiddleware, sessionRefreshMiddleware)

interface ErrorEnvelope {
  error?: { message?: string; code?: string }
}

/**
 * Converts openapi-fetch's `{data, error}` result into throw-on-error
 * ergonomics (spec §9.8's envelope), matching what TanStack Query's
 * `queryFn`/`mutationFn` expect: resolve with data, reject with an `Error`.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined) {
    const envelope = result.error as ErrorEnvelope
    const message = envelope?.error?.message ?? result.response.statusText
    const code = envelope?.error?.code
    throw new ApiError(result.response.status, message, code)
  }
  return result.data as T
}
