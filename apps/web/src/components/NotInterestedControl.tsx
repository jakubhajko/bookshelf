import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { EyeOff } from 'lucide-react'
import { useState } from 'react'

interface NotInterestedControlProps {
  notInterested: boolean
  hasRating: boolean
  onSetNotInterested: () => void
  onRemoveNotInterested: () => void
  disabled?: boolean
}

/**
 * Spec §12.7: "Not Interested confirms if clearing a rating and never
 * removes shelves." The "never removes shelves" half is a backend
 * guarantee (spec §5.3's atomic state transitions), not something this
 * control enforces — it's surfaced in the confirmation copy so the user
 * isn't left guessing what else the action affects.
 */
export function NotInterestedControl({
  notInterested,
  hasRating,
  onSetNotInterested,
  onRemoveNotInterested,
  disabled,
}: NotInterestedControlProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)

  if (notInterested) {
    return (
      <button
        type="button"
        onClick={onRemoveNotInterested}
        disabled={disabled}
        aria-pressed="true"
        className="flex items-center gap-2 rounded-md border border-accent bg-accent/10 px-3 py-2 text-sm text-accent focus:outline-none focus:ring-2 focus:ring-accent"
      >
        <EyeOff aria-hidden className="h-4 w-4" />
        Not interested
      </button>
    )
  }

  function handleClick() {
    if (hasRating) {
      setConfirmOpen(true)
    } else {
      onSetNotInterested()
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        aria-pressed="false"
        className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text hover:bg-surface-hover focus:outline-none focus:ring-2 focus:ring-accent"
      >
        <EyeOff aria-hidden className="h-4 w-4" />
        Not interested
      </button>

      <AlertDialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="fixed inset-0 z-30 bg-black/60" />
          <AlertDialog.Content className="fixed top-1/2 left-1/2 z-30 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-6 focus:outline-none">
            <AlertDialog.Title className="text-base font-semibold text-text">
              Clear your rating?
            </AlertDialog.Title>
            <AlertDialog.Description className="mt-2 text-sm text-text-muted">
              Marking this book Not Interested clears your current rating. Shelves it&apos;s
              saved to are not affected.
            </AlertDialog.Description>
            <div className="mt-6 flex justify-end gap-3">
              <AlertDialog.Cancel asChild>
                <button
                  type="button"
                  className="rounded-md px-3 py-2 text-sm text-text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
                >
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  type="button"
                  onClick={onSetNotInterested}
                  className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-text hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent"
                >
                  Clear rating
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </>
  )
}
