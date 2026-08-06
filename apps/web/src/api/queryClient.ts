import { QueryClient } from '@tanstack/react-query'

/**
 * A plain, importable singleton — not just reachable via `useQueryClient()`
 * inside a component. `api/client.ts`'s session-refresh-failure handler
 * needs to clear the auth cache from *outside* the React tree (spec §15:
 * "login redirect after refresh failure"), the same reason
 * `toast/toastStore.ts` isn't a React context either.
 */
export const queryClient = new QueryClient()
