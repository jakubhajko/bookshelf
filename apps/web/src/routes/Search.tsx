import { useSearchParams } from 'react-router'
import { ComingSoon } from '../components/ComingSoon'

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const query = searchParams.get('q')

  return (
    <ComingSoon
      title={query ? `Search results for "${query}"` : 'Search'}
      description="Debounced suggestions, masonry results, and state badges land in Phase 8."
    />
  )
}
