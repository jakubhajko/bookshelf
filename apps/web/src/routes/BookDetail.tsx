import { useParams } from 'react-router'
import { ComingSoon } from '../components/ComingSoon'

export function BookDetailPage() {
  const { bookId } = useParams()

  return (
    <ComingSoon
      title={`Book #${bookId}`}
      description="Cover, description, ratings, shelf controls, and the similar-books grid land in Phase 7."
    />
  )
}
