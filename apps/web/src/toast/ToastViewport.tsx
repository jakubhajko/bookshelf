import * as Toast from '@radix-ui/react-toast'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { dismissToast, getToastSnapshot, subscribeToasts, type ToastVariant } from './toastStore'

const VARIANT_STYLES: Record<ToastVariant, { border: string; Icon: typeof Info }> = {
  success: { border: 'border-l-emerald-500', Icon: CheckCircle2 },
  error: { border: 'border-l-accent', Icon: XCircle },
  info: { border: 'border-l-border', Icon: Info },
}

/**
 * Renders every active toast (spec §15: "mutation toasts", spec §12.12:
 * "mutation announcements"). Radix's `Toast.Root` owns all the timing —
 * auto-dismiss via its own `duration`, or an explicit `Toast.Close` click
 * — and reports back through `onOpenChange`; this component's only job is
 * removing a toast from the shared store once Radix says it's done with
 * it, and it sets the correct `aria-live` region automatically, so screen
 * readers announce each one without any manual wiring here.
 */
export function ToastViewport() {
  const toasts = useSyncExternalStore(subscribeToasts, getToastSnapshot)

  return (
    <Toast.Provider swipeDirection="right">
      {toasts.map((toast) => {
        const { border, Icon } = VARIANT_STYLES[toast.variant]
        return (
          <Toast.Root
            key={toast.id}
            duration={5000}
            onOpenChange={(open) => {
              if (!open) dismissToast(toast.id)
            }}
            className={`relative flex items-start gap-2 rounded-md border border-border border-l-4 bg-surface p-4 pr-8 shadow-lg ${border}`}
          >
            <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-text-muted" />
            <Toast.Title className="text-sm text-text">{toast.title}</Toast.Title>
            <Toast.Close
              aria-label="Dismiss"
              className="absolute top-3 right-3 text-text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <X aria-hidden className="h-4 w-4" />
            </Toast.Close>
          </Toast.Root>
        )
      })}
      <Toast.Viewport className="fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2 outline-none" />
    </Toast.Provider>
  )
}
