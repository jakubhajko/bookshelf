import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { AuthProvider } from '../auth/AuthProvider'
import { AvatarMenu } from './AvatarMenu'

function renderMenu() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<AvatarMenu />} />
            <Route path="/login" element={<p>login page</p>} />
            <Route path="/account" element={<p>account page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AvatarMenu', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(authApi, 'fetchCurrentUser').mockResolvedValue({ id: '1', username: 'kubo' })
  })

  it("renders the user's username on the trigger", async () => {
    renderMenu()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Account menu for kubo' })).toBeInTheDocument(),
    )
  })

  it('opens to show account actions', async () => {
    const user = userEvent.setup()
    renderMenu()

    await user.click(await screen.findByRole('button', { name: 'Account menu for kubo' }))

    expect(await screen.findByRole('menuitem', { name: 'Account' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Change password' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Log out' })).toBeInTheDocument()
  })

  it('logs out and navigates to /login', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'logout').mockResolvedValue(undefined)
    renderMenu()

    await user.click(await screen.findByRole('button', { name: 'Account menu for kubo' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Log out' }))

    await waitFor(() => expect(authApi.logout).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
  })
})
