import { useParams } from 'react-router'
import { BookDetailContent } from '../components/BookDetailContent'
import { NotFoundPage } from './NotFound'

/** Direct-route full page (spec §12.7: "Direct route renders full page").
 * The same content also renders inside `BookDetailModal` when reached via
 * in-app navigation from a card — see `routing/modalNavigation.ts`. */
export function BookDetailPage() {
  const { bookId } = useParams()
  const numericId = Number(bookId)

  if (!bookId || !Number.isInteger(numericId)) {
    return <NotFoundPage />
  }

  return (
    <div className="mx-auto max-w-3xl">
      <BookDetailContent bookId={numericId} />
    </div>
  )
}
