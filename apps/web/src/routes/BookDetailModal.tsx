import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useNavigate, useParams } from 'react-router'
import { BookDetailContent } from '../components/BookDetailContent'

/**
 * Desktop route-backed modal over the prior page, mobile full-screen (spec
 * §12.7). Only ever mounted when `App.tsx` found a `backgroundLocation` to
 * render underneath — direct navigation to `/books/:bookId` renders
 * `BookDetailPage` (the plain route) instead. Closing navigates back
 * (`navigate(-1)`) rather than to a fixed path, matching how it was
 * reached — an in-app navigation always pushed exactly one history entry
 * to get here (see `routing/modalNavigation.ts`).
 */
export function BookDetailModal() {
  const { bookId } = useParams()
  const navigate = useNavigate()
  const numericId = Number(bookId)

  function handleOpenChange(open: boolean) {
    if (!open) {
      void navigate(-1)
    }
  }

  if (!bookId || !Number.isInteger(numericId)) {
    return null
  }

  return (
    <Dialog.Root open onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/70" />
        <Dialog.Content className="fixed inset-0 z-30 overflow-y-auto bg-background focus:outline-none sm:inset-x-auto sm:inset-y-6 sm:left-1/2 sm:w-full sm:max-w-2xl sm:-translate-x-1/2 sm:rounded-lg sm:border sm:border-border">
          <Dialog.Title className="sr-only">Book details</Dialog.Title>
          <Dialog.Description className="sr-only">
            Full book details, your rating, shelves, and similar books.
          </Dialog.Description>
          <Dialog.Close
            aria-label="Close"
            className="absolute top-4 right-4 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-surface text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
          >
            <X aria-hidden className="h-5 w-5" />
          </Dialog.Close>
          <BookDetailContent bookId={numericId} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
