import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { dismissToast, getToastSnapshot, showToast } from './toastStore'
import { ToastViewport } from './ToastViewport'

describe('ToastViewport', () => {
  beforeEach(() => {
    for (const toast of getToastSnapshot()) dismissToast(toast.id)
  })

  it('renders a toast raised via showToast (spec §12.12: mutation announcements)', async () => {
    render(<ToastViewport />)

    showToast('Book saved to shelf', 'success')

    expect(await screen.findByText('Book saved to shelf')).toBeInTheDocument()
  })

  it('removes a toast from the store when its close button is clicked', async () => {
    const user = userEvent.setup()
    render(<ToastViewport />)
    showToast('Dismiss me')
    await screen.findByText('Dismiss me')

    await user.click(screen.getByRole('button', { name: 'Dismiss' }))

    await waitFor(() => expect(getToastSnapshot()).toHaveLength(0))
  })

  it('renders multiple toasts at once', async () => {
    render(<ToastViewport />)

    showToast('First message')
    showToast('Second message')

    expect(await screen.findByText('First message')).toBeInTheDocument()
    expect(screen.getByText('Second message')).toBeInTheDocument()
  })
})
