import { useState, type FormEvent } from 'react'
import { changePassword } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { TextField } from '../components/TextField'

export function AccountPage() {
  const { user } = useAuth()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirmation, setNewPasswordConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSuccess(false)
    setIsSubmitting(true)
    try {
      await changePassword({ currentPassword, newPassword, newPasswordConfirmation })
      setSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setNewPasswordConfirmation('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!user) return null

  return (
    <div className="mx-auto max-w-lg px-4 py-10">
      <h1 className="text-xl font-semibold text-text">Account</h1>
      <p className="mt-1 text-sm text-text-muted">Logged in as {user.username}</p>

      <section className="mt-8 rounded-lg border border-border bg-surface p-6">
        <h2 className="text-base font-semibold text-text">Change password</h2>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4" noValidate>
          <TextField
            id="current-password"
            label="Current password"
            type="password"
            autoComplete="current-password"
            required
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
          <TextField
            id="new-password"
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
          <TextField
            id="new-password-confirmation"
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={newPasswordConfirmation}
            onChange={(event) => setNewPasswordConfirmation(event.target.value)}
          />

          {error && (
            <p role="alert" className="text-sm text-accent">
              {error}
            </p>
          )}
          {success && (
            <p role="status" className="text-sm text-text-muted">
              Password updated.
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text transition hover:bg-accent-hover disabled:opacity-60"
          >
            {isSubmitting ? 'Saving…' : 'Update password'}
          </button>
        </form>
      </section>
    </div>
  )
}
