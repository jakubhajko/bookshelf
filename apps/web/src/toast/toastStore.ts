/**
 * Plain module-level store (spec §15: "mutation toasts") — deliberately
 * not a React context. `api/client.ts`'s session-refresh-failure path
 * needs to show a toast from *outside* any component tree, the same
 * reason `api/queryClient.ts` exports a plain `QueryClient` singleton
 * instead of only being reachable via `useQueryClient()`. `ToastViewport`
 * subscribes via `useSyncExternalStore`; `showToast`/`dismissToast` are
 * the only two things anything else needs to import.
 */

export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastMessage {
  id: string
  title: string
  variant: ToastVariant
}

let toasts: ToastMessage[] = []
type Listener = () => void
let listeners: Listener[] = []

function notify() {
  for (const listener of listeners) listener()
}

export function subscribeToasts(listener: Listener): () => void {
  listeners = [...listeners, listener]
  return () => {
    listeners = listeners.filter((l) => l !== listener)
  }
}

export function getToastSnapshot(): ToastMessage[] {
  return toasts
}

export function dismissToast(id: string): void {
  toasts = toasts.filter((t) => t.id !== id)
  notify()
}

export function showToast(title: string, variant: ToastVariant = 'info'): void {
  const id = crypto.randomUUID()
  toasts = [...toasts, { id, title, variant }]
  notify()
}
