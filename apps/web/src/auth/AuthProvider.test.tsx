import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { useAuth } from './AuthContext'
import { AuthProvider } from './AuthProvider'

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  )
}

function Probe() {
  const { user, isLoading, logout } = useAuth()
  if (isLoading) return <p>loading</p>
  return (
    <div>
      <p data-testid="username">{user ? user.username : 'anonymous'}</p>
      <button type="button" onClick={() => void logout()}>
        Log out
      </button>
    </div>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('bootstraps to the current user when a session exists', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })

    renderWithProviders(<Probe />)

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('kubo'))
  })

  it('bootstraps to anonymous when there is no session', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue(null)

    renderWithProviders(<Probe />)

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('anonymous'))
  })

  it('clears the user on logout', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })
    vi.spyOn(authApi, 'logout').mockResolvedValue(undefined)

    renderWithProviders(<Probe />)
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('kubo'))

    await user.click(screen.getByRole('button', { name: 'Log out' }))

    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('anonymous'))
  })
})
