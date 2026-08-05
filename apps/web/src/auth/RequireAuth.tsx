import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from './AuthContext'

/** Wraps protected routes — redirects to /login, remembering where the
 * visitor was headed so a successful login can send them back. */
export function RequireAuth() {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return null
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <Outlet />
}
