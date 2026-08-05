import { apiClient, unwrap } from './client'
import type { components } from './generated/schema'

export type CurrentUser = components['schemas']['UserPublic']

export async function register(input: {
  username: string
  password: string
  passwordConfirmation: string
}): Promise<CurrentUser> {
  const result = await apiClient.POST('/api/v1/auth/register', {
    body: {
      username: input.username,
      password: input.password,
      password_confirmation: input.passwordConfirmation,
    },
  })
  return unwrap(result)
}

export async function login(input: { username: string; password: string }): Promise<CurrentUser> {
  const result = await apiClient.POST('/api/v1/auth/login', {
    body: { username: input.username, password: input.password },
  })
  return unwrap(result)
}

/**
 * `null` means "not logged in" (401), not an error — the session-refresh
 * middleware (`./client.ts`) already tried and failed to recover one before
 * this resolves, so a genuine visitor without a session is the normal case
 * here, not a failure to surface via `isError`.
 */
export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const result = await apiClient.GET('/api/v1/auth/me')
  if (result.response.status === 401) return null
  return unwrap(result)
}

export async function logout(): Promise<void> {
  const result = await apiClient.POST('/api/v1/auth/logout')
  unwrap(result)
}

export async function changePassword(input: {
  currentPassword: string
  newPassword: string
  newPasswordConfirmation: string
}): Promise<void> {
  const result = await apiClient.POST('/api/v1/auth/change-password', {
    body: {
      current_password: input.currentPassword,
      new_password: input.newPassword,
      new_password_confirmation: input.newPasswordConfirmation,
    },
  })
  unwrap(result)
}
