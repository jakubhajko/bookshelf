import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import * as authApi from '../api/auth'
import { queryKeys } from '../api/queryKeys'
import { AuthContext } from './AuthContext'

/**
 * Minimal AuthProvider (spec §12.11) — bootstraps the current user once via
 * `GET /auth/me` and keeps it in the TanStack Query cache (ADR-0008: "all
 * server data flows through TanStack Query's cache"). `staleTime: Infinity`
 * because nothing *external* changes this value — only login/logout/the
 * session-refresh middleware do, and each of those updates the cache
 * directly rather than relying on a background refetch.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data: user, isLoading } = useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: authApi.fetchCurrentUser,
    staleTime: Infinity,
    retry: false,
  })

  async function login(input: { username: string; password: string }) {
    const loggedInUser = await authApi.login(input)
    queryClient.setQueryData(queryKeys.auth.me, loggedInUser)
    return loggedInUser
  }

  async function register(input: {
    username: string
    password: string
    passwordConfirmation: string
  }) {
    // Registration alone doesn't establish a session (spec §13.5 lists
    // register/login as separate steps) — the register page navigates to
    // /login itself afterward, so nothing here touches the auth cache.
    return authApi.register(input)
  }

  async function logout() {
    await authApi.logout()
    queryClient.setQueryData(queryKeys.auth.me, null)
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
