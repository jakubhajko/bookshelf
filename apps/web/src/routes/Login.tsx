import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { TextField } from '../components/TextField'

interface LoginLocationState {
  from?: { pathname: string }
  justRegistered?: boolean
  /** Set by `Register` so a brand-new reader lands on taste selection
   * instead of an unpersonalized Home. Only ever set on the hop straight
   * from registration, so returning readers are never sent back through
   * onboarding — and `from` still wins, because someone deep-linked to a
   * page and bounced to login wanted *that* page. */
  onboard?: boolean
}

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state ?? {}) as LoginLocationState

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login({ username, password })
      const next = state.from?.pathname ?? (state.onboard ? '/welcome' : '/')
      await navigate(next, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8">
        <h1 className="text-xl font-semibold text-text">Log in</h1>

        {state.justRegistered && (
          <p className="mt-4 rounded-md border border-border bg-background px-3 py-2 text-sm text-text-muted">
            Account created. Log in to continue.
          </p>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
          <TextField
            id="username"
            label="Username"
            type="text"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <TextField
            id="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-accent px-4 py-2 font-medium text-accent-text transition hover:bg-accent-hover disabled:opacity-60"
          >
            {isSubmitting ? 'Logging in…' : 'Log in'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-text-muted">
          Don&apos;t have an account?{' '}
          <Link to="/register" className="text-accent-soft hover:underline">
            Register
          </Link>
        </p>
      </div>
    </main>
  )
}
