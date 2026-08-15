import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from './AuthContext'

/** Wraps /register and /login — an already-authenticated visitor is sent
 * home instead of seeing an auth form again.
 *
 * It has to agree with `Login`'s own post-login navigation about *where*,
 * because the two race: logging in sets `user`, which re-renders this
 * guard, and whichever redirect lands first wins. They both read the same
 * `onboard` flag so the outcome is the same either way — without that, a
 * newly-registered reader was sent to Home roughly whenever this guard
 * won, which is how the R8 onboarding redirect silently did nothing in a
 * real browser while passing every jsdom test. */
export function GuestOnly() {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return null
  if (user) {
    const onboard = (location.state as { onboard?: boolean } | null)?.onboard
    return <Navigate to={onboard ? '/welcome' : '/'} replace />
  }
  return <Outlet />
}
