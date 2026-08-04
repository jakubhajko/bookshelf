# ADR-0004: Cookie-based sessions with DB-backed refresh and explicit CSRF protection

## Status

Accepted (approved in `APP_SPECIFICATION.md` §6.4–§6.6, §20 before implementation started).

## Context

The frontend and API are same-site (or configured as trusted cross-origin
during local dev) and the product has no need for third-party API consumers
in version one. Tokens must not be readable by frontend JavaScript exposed to
XSS, and revocation (logout, session cleanup) must be possible without
waiting for token expiry.

## Decision

Short-lived JWT access tokens (~15 min) plus revocable, database-backed
refresh sessions (`auth_sessions`, ~30 days), both delivered as HttpOnly
cookies (Secure in production, `SameSite=Lax` unless a reviewed deployment
need changes it). Only refresh token *hashes* are stored, never raw tokens.
Because cookies are used instead of an `Authorization` header, CSRF is
mitigated explicitly: a readable, session-bound CSRF token that the frontend
echoes back as `X-CSRF-Token` on every mutating request, verified
server-side — CORS configuration is not relied on as the CSRF defense.

## Alternatives considered

- **JWT in `localStorage`, sent via `Authorization` header** — explicitly
  rejected by spec §20 ("Do not store JWTs in localStorage"). Vulnerable to
  exfiltration via any XSS, and offers no revocation without a blocklist.
- **CORS-only CSRF defense (no explicit token)** — rejected; spec §6.5 is
  explicit ("Do not rely on CORS alone"), and CORS misconfiguration or a
  future relaxed-origin requirement would silently reopen CSRF.
- **Stateless refresh (long-lived JWT, no DB row)** — rejected; makes
  "logout revokes only the current session" (spec §6.1) impossible without a
  revocation list, which is effectively the `auth_sessions` table anyway.

## Consequences

- Every mutating endpoint needs CSRF-token verification wired through
  `core/dependencies.py`, not just auth endpoints.
- Refresh-session storage means a cleanup job/CLI (`cleanup_sessions`) is
  required to bound table growth from expired sessions — already scheduled
  in spec §11's CLI command list.
- Cross-origin local development (frontend on Vite's dev server, API on
  FastAPI's) needs exact, credentialed CORS configuration
  (`allow_credentials=True` with an explicit origin list, never `*`).
