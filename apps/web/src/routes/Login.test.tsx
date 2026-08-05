import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { ApiError } from '../api/client'
import { AuthProvider } from '../auth/AuthProvider'
import { LoginPage } from './Login'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<p>home page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue(null)
  })

  it('logs in then navigates home', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'login').mockResolvedValue({ id: '1', username: 'kubo' })

    renderPage()

    await user.type(screen.getByLabelText('Username'), 'kubo')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    await waitFor(() => expect(screen.getByText('home page')).toBeInTheDocument())
  })

  it('shows the server error message on invalid credentials', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new ApiError(401, 'Invalid username or password.', 'INVALID_CREDENTIALS'),
    )

    renderPage()

    await user.type(screen.getByLabelText('Username'), 'kubo')
    await user.type(screen.getByLabelText('Password'), 'wrong password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid username or password.'),
    )
  })
})
