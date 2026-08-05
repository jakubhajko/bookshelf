import { useParams } from 'react-router'
import { ComingSoon } from '../components/ComingSoon'

export function ShelfBooksPage() {
  const { shelfId } = useParams()

  return (
    <ComingSoon
      title="Shelf books"
      description={`The Books tab for shelf ${shelfId} lands in Phase 8.`}
    />
  )
}
