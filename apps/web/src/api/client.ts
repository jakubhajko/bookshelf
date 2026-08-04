/**
 * Minimal typed fetch wrapper around the API's error envelope (spec §9.8).
 *
 * This is a Phase 1 stand-in — Phase 6 replaces/extends it with a client
 * generated from the FastAPI OpenAPI schema (`make generate-api-client`),
 * per ADR-0002. Kept here now only so the Phase 1 smoke slice
 * (`routes/Home.tsx`) has something real to call instead of hand-rolled
 * fetch calls scattered across components.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ErrorEnvelope {
  error?: { message?: string }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!response.ok) {
    let message = response.statusText
    try {
      const body = (await response.json()) as ErrorEnvelope
      message = body.error?.message ?? message
    } catch {
      // Response body wasn't JSON (e.g. a proxy/network error page) — keep statusText.
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
