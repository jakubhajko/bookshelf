import { useQuery } from '@tanstack/react-query'
import { fetchLiveness } from '../api/health'

/**
 * Phase 1 smoke page: proves the frontend can reach the backend through
 * TanStack Query and CORS is configured correctly. The masonry home feed
 * (spec §12.4) replaces this in Phase 7.
 */
export function HomePage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health', 'live'],
    queryFn: fetchLiveness,
  })

  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-950 text-neutral-100">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Book Discovery</h1>
        <p data-testid="backend-status" className="mt-2 text-neutral-400">
          {isPending && 'Checking backend…'}
          {isError && 'Backend unreachable'}
          {data && `Backend: ${data.status}`}
        </p>
      </div>
    </main>
  )
}
