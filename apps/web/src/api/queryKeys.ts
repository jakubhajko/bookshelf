/**
 * Centralized TanStack Query keys (spec §12.11). Grows one branch per
 * domain as later phases add queries — keeping them in one place from the
 * start avoids ad hoc, easy-to-typo key arrays scattered across components.
 */
export const queryKeys = {
  auth: {
    me: ['auth', 'me'] as const,
  },
} as const
