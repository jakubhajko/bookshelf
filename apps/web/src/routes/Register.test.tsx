import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { ApiError } from '../api/client'
import { AuthProvider } from '../auth/AuthProvider'
import { RegisterPage } from './Register'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/register']}>
        <AuthProvider>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/login" element={<p>login page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const PASSWORD = 'correct horse battery staple'

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue(null)
  })

  it('registers then navigates to /login', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'register').mockResolvedValue({ id: '1', username: 'kubo' })

    renderPage()

    await user.type(screen.getByLabelText('Username'), 'kubo')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.type(screen.getByLabelText('Confirm password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
  })

  it('shows the server error message on failure', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'register').mockRejectedValue(
      new ApiError(409, 'That username is taken.', 'USERNAME_TAKEN'),
    )

    renderPage()

    await user.type(screen.getByLabelText('Username'), 'kubo')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.type(screen.getByLabelText('Confirm password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('That username is taken.'),
    )
  })
})
