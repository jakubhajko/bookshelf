import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { TextField } from '../components/TextField'

export function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await register({ username, password, passwordConfirmation })
      // Registration doesn't establish a session (spec §13.5 treats
      // register/login as separate steps) — send them to log in next.
      await navigate('/login', { state: { justRegistered: true, onboard: true } })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-8">
        <h1 className="text-xl font-semibold text-text">Create your account</h1>

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
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <TextField
            id="password-confirmation"
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={passwordConfirmation}
            onChange={(event) => setPasswordConfirmation(event.target.value)}
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
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-text-muted">
          Already have an account?{' '}
          <Link to="/login" className="text-accent-soft hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </main>
  )
}
