import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ErrorBoundary } from 'react-error-boundary'
import { describe, expect, it, vi } from 'vitest'
import { RootErrorFallback, RouteErrorFallback } from './ErrorFallback'

function Bomb(): never {
  throw new Error('Boom')
}

describe('RootErrorFallback (spec §15: "root boundary")', () => {
  it('shows the error and a reload action', async () => {
    const reloadSpy = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload: reloadSpy })
    const user = userEvent.setup()

    render(
      <ErrorBoundary FallbackComponent={RootErrorFallback}>
        <Bomb />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Boom')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Reload page' }))
    expect(reloadSpy).toHaveBeenCalledOnce()

    vi.unstubAllGlobals()
  })
})

describe('RouteErrorFallback (spec §15: "route errors")', () => {
  it('shows the error and a retry action that resets the boundary', async () => {
    const user = userEvent.setup()
    let shouldThrow = true
    function MaybeBomb() {
      if (shouldThrow) throw new Error('Route crashed')
      return <p>recovered</p>
    }

    render(
      <ErrorBoundary FallbackComponent={RouteErrorFallback}>
        <MaybeBomb />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Route crashed')).toBeInTheDocument()

    shouldThrow = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('recovered')).toBeInTheDocument()
  })
})
