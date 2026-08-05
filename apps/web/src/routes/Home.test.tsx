import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HomePage } from './Home'

describe('HomePage', () => {
  it('renders the Phase 7 placeholder', () => {
    render(<HomePage />)
    expect(screen.getByRole('heading', { name: 'Your home feed' })).toBeInTheDocument()
  })
})
