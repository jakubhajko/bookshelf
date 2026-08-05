import { API_BASE_URL } from './client'

/**
 * The one URL-building helper in the app (spec §20: "do not construct
 * cover paths in frontend"). This doesn't construct a *path* — it appends
 * an opaque, backend-issued key to a fixed, backend-owned route
 * (`core/covers.py`, ADR-0011); nothing here knows about file extensions,
 * local disk layout, or any future S3 key scheme, and that boundary is the
 * whole point. `null` in, `null` out: `has_cover=false` books render a
 * placeholder (spec §12.5), never a request to a route that can't exist.
 */
export function coverUrl(objectKey: string | null): string | null {
  if (!objectKey) return null
  return `${API_BASE_URL}/api/v1/covers/${encodeURIComponent(objectKey)}`
}
