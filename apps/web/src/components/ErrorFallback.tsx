import type { FallbackProps } from 'react-error-boundary'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'An unexpected error occurred.'
}

/** Root error boundary's fallback (spec §15: "root boundary") — a crash
 * this high up means React itself may be in a broken state, so the
 * recovery action is a real browser reload, not just clearing the
 * boundary's internal state. */
export function RootErrorFallback({ error }: FallbackProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <h1 className="text-lg font-semibold text-text">Something went wrong</h1>
      <p className="mt-2 max-w-sm text-sm text-text-muted">{errorMessage(error)}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-4 rounded-md border border-border px-4 py-2 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Reload page
      </button>
    </div>
  )
}

/** Per-route error boundary's fallback (spec §15: "route errors") — the
 * shell (nav rail, top bar) stays mounted and usable around this, so
 * retrying in place (or just navigating elsewhere) is a real fix, not
 * just a placebo — `AppShell.tsx` also keys this boundary's `resetKeys`
 * off the current path, so navigating to a new route clears a stuck error
 * from the previous one automatically. */
export function RouteErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
      <h1 className="text-lg font-semibold text-text">Something went wrong</h1>
      <p className="mt-2 max-w-sm text-sm text-text-muted">{errorMessage(error)}</p>
      <button
        type="button"
        onClick={resetErrorBoundary}
        className="mt-4 rounded-md border border-border px-4 py-2 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Try again
      </button>
    </div>
  )
}
