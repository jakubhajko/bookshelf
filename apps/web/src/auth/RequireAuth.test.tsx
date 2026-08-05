import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { AuthProvider } from './AuthProvider'
import { RequireAuth } from './RequireAuth'

function LoginStub() {
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } } | null)?.from
  return <p>login page{from ? ` from ${from.pathname}` : ''}</p>
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginStub />} />
            <Route element={<RequireAuth />}>
              <Route path="/shelves" element={<p>shelves page</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RequireAuth', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('redirects an unauthenticated visitor to /login, remembering the origin', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue(null)

    renderAt('/shelves')

    await waitFor(() =>
      expect(screen.getByText('login page from /shelves')).toBeInTheDocument(),
    )
  })

  it('renders the protected route for an authenticated visitor', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })

    renderAt('/shelves')

    await waitFor(() => expect(screen.getByText('shelves page')).toBeInTheDocument())
  })
})
