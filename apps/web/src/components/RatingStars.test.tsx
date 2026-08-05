import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RatingStars } from './RatingStars'

describe('RatingStars', () => {
  it('renders ten accessible half-step radio controls', () => {
    render(<RatingStars value={null} onRate={vi.fn()} onRemove={vi.fn()} />)

    expect(screen.getByRole('radio', { name: '0.5 stars' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '1 star' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '4.5 stars' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '5 stars' })).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(10)
  })

  it('calls onRate with the clicked half-step value', async () => {
    const user = userEvent.setup()
    const onRate = vi.fn()
    render(<RatingStars value={null} onRate={onRate} onRemove={vi.fn()} />)

    await user.click(screen.getByRole('radio', { name: '3.5 stars' }))

    expect(onRate).toHaveBeenCalledWith(3.5)
  })

  it('marks the current value as checked', () => {
    render(<RatingStars value={4} onRate={vi.fn()} onRemove={vi.fn()} />)

    expect(screen.getByRole('radio', { name: '4 stars' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '3.5 stars' })).not.toBeChecked()
  })

  it('only offers a remove action once rated, and calls onRemove', async () => {
    const user = userEvent.setup()
    const onRemove = vi.fn()
    const { rerender } = render(<RatingStars value={null} onRate={vi.fn()} onRemove={onRemove} />)
    expect(screen.queryByRole('button', { name: 'Remove rating' })).not.toBeInTheDocument()

    rerender(<RatingStars value={4} onRate={vi.fn()} onRemove={onRemove} />)
    await user.click(screen.getByRole('button', { name: 'Remove rating' }))

    expect(onRemove).toHaveBeenCalledOnce()
  })
})
