/**
 * Centralized TanStack Query keys (spec §12.11). Grows one branch per
 * domain as later phases add queries — keeping them in one place from the
 * start avoids ad hoc, easy-to-typo key arrays scattered across components.
 */
export const queryKeys = {
  auth: {
    me: ['auth', 'me'] as const,
  },
  shelves: {
    list: ['shelves'] as const,
  },
  books: {
    detail: (bookId: number) => ['books', bookId, 'detail'] as const,
    /** This user's rating/not-interested/shelf state for one book — shared
     * cache entry between cards and the detail page (neither the rating nor
     * the shelf-sync response carries the *other* field, spec §9.2's split
     * `PreferenceState`/`ShelfIdsResponse`), updated by whichever mutation
     * ran and read by every surface showing that book. */
    state: (bookId: number) => ['books', bookId, 'state'] as const,
  },
  recommendations: {
    home: ['recommendations', 'home'] as const,
    similar: (bookId: number) => ['recommendations', bookId, 'similar'] as const,
  },
} as const
