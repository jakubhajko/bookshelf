import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { AuthProvider } from './AuthProvider'
import { GuestOnly } from './GuestOnly'

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<p>home page</p>} />
            <Route element={<GuestOnly />}>
              <Route path="/login" element={<p>login page</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('GuestOnly', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('redirects an already-authenticated visitor home', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })

    renderAt('/login')

    await waitFor(() => expect(screen.getByText('home page')).toBeInTheDocument())
  })

  it('renders the guest route for an unauthenticated visitor', async () => {
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue(null)

    renderAt('/login')

    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
  })
})
