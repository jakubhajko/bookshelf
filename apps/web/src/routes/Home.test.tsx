import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as healthApi from '../api/health'
import { HomePage } from './Home'

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('HomePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows backend status once the health check resolves', async () => {
    vi.spyOn(healthApi, 'fetchLiveness').mockResolvedValue({ status: 'ok' })

    renderWithProviders(<HomePage />)

    await waitFor(() =>
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend: ok'),
    )
  })

  it('shows an error state when the health check fails', async () => {
    vi.spyOn(healthApi, 'fetchLiveness').mockRejectedValue(new Error('network error'))

    renderWithProviders(<HomePage />)

    await waitFor(() =>
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend unreachable'),
    )
  })
})
