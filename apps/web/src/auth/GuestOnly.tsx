import { Navigate, Outlet } from 'react-router'
import { useAuth } from './AuthContext'

/** Wraps /register and /login — an already-authenticated visitor is sent
 * home instead of seeing an auth form again. */
export function GuestOnly() {
  const { user, isLoading } = useAuth()

  if (isLoading) return null
  if (user) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
