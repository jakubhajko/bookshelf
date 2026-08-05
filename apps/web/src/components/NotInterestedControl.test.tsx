import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { NotInterestedControl } from './NotInterestedControl'

describe('NotInterestedControl', () => {
  it('acts immediately when there is no rating to lose', async () => {
    const user = userEvent.setup()
    const onSetNotInterested = vi.fn()
    render(
      <NotInterestedControl
        notInterested={false}
        hasRating={false}
        onSetNotInterested={onSetNotInterested}
        onRemoveNotInterested={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Not interested' }))

    expect(onSetNotInterested).toHaveBeenCalledOnce()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('confirms before clearing an existing rating (spec §12.7)', async () => {
    const user = userEvent.setup()
    const onSetNotInterested = vi.fn()
    render(
      <NotInterestedControl
        notInterested={false}
        hasRating
        onSetNotInterested={onSetNotInterested}
        onRemoveNotInterested={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Not interested' }))
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    expect(onSetNotInterested).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Clear rating' }))
    expect(onSetNotInterested).toHaveBeenCalledOnce()
  })

  it('lets the confirmation be cancelled without acting', async () => {
    const user = userEvent.setup()
    const onSetNotInterested = vi.fn()
    render(
      <NotInterestedControl
        notInterested={false}
        hasRating
        onSetNotInterested={onSetNotInterested}
        onRemoveNotInterested={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Not interested' }))
    await screen.findByRole('alertdialog')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onSetNotInterested).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('offers to remove Not Interested once set, with no confirmation needed', async () => {
    const user = userEvent.setup()
    const onRemoveNotInterested = vi.fn()
    render(
      <NotInterestedControl
        notInterested
        hasRating={false}
        onSetNotInterested={vi.fn()}
        onRemoveNotInterested={onRemoveNotInterested}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Not interested' }))

    expect(onRemoveNotInterested).toHaveBeenCalledOnce()
  })
})
