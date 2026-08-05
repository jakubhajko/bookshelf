import { useParams } from 'react-router'
import { ComingSoon } from '../components/ComingSoon'

export function ShelfDiscoverPage() {
  const { shelfId } = useParams()

  return (
    <ComingSoon
      title="Shelf discover"
      description={`Shelf-lens recommendations for shelf ${shelfId} land in Phase 8.`}
    />
  )
}
