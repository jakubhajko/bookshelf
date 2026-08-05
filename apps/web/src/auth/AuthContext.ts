import { createContext, useContext } from 'react'
import type { CurrentUser } from '../api/auth'

export interface AuthContextValue {
  /** `undefined` while the initial bootstrap check is in flight, `null` if not logged in. */
  user: CurrentUser | null | undefined
  isLoading: boolean
  login: (input: { username: string; password: string }) => Promise<CurrentUser>
  register: (input: {
    username: string
    password: string
    passwordConfirmation: string
  }) => Promise<CurrentUser>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
