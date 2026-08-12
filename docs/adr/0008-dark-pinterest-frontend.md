# ADR-0008: Dark-first, Pinterest-inspired, image-led frontend

## Status

Accepted (approved in `APP_SPECIFICATION.md` §12, §20 before implementation started).

## Context

Book discovery is a highly visual browsing task (covers, masonry layout,
hover-revealed actions). The product has one target aesthetic from the start
— dark, minimalist, content-dense — and no requirement for a light theme in
version one, but design tokens should not make a future light theme
structurally painful.

## Decision

React + TypeScript + Vite, Tailwind CSS driven by design tokens (background,
surface, text, border, accent, radii, sidebar, top bar), React Router for
routing, TanStack Query for all server state (no Redux, no separate global
client-state store), a minimal `AuthProvider` for identity, and accessible
headless UI primitives for interactive controls (shelf selector, modals,
star rating) rather than hand-rolled unstyled `<div>` widgets. The shell is a
fixed narrow left rail (Home/Shelves/Rated) plus sticky top bar on desktop,
bottom navigation on mobile. First version ships dark-only; tokens are
structured so a light theme is a values swap, not a rewrite.

## Alternatives considered

- **Redux (or another global store) for client state** — explicitly out of
  scope; spec §12.11 says "No Redux," and TanStack Query already owns server
  state, leaving little that needs a global client store beyond local UI
  state and auth.
- **CSS-in-JS or a component library's own theming system** — rejected in
  favor of Tailwind + tokens, matching the explicit tech choice in spec §3.2
  and keeping styling colocated with markup.
- **Build both dark and light themes now** — rejected as premature; spec
  §12.1 explicitly scopes version one to dark-only while asking for
  token-level extensibility, not two finished themes.

## Consequences

- Every new visual surface must be built from the token set, not ad hoc
  colors, or a future light theme becomes a per-component rewrite instead of
  a token swap. The Phase 10 visual pass exercised this: re-theming from
  near-black + rose to charcoal + blue was a values edit in `index.css`
  plus two token additions, with no component restructuring. Those two
  additions — `danger` and `accent-soft` — are load-bearing rather than
  decorative. `danger` exists because errors had been borrowing the accent,
  which only read as "error" while the accent happened to be red; once it
  turned blue, invalid-credential text would have been indistinguishable
  from a link. `accent-soft` exists because the solid accent reaches only
  ~3.3-3.7:1 as text on the dark surfaces, so accent-colored *text* needs a
  lighter tint than accent-colored *fills*. A light theme will need to keep
  both distinctions, in the other direction.
- Accessible headless primitives (focus trap, `Escape` handling, ARIA roles)
  are a Phase 1-onward dependency choice, not something bolted on during the
  Phase 9 accessibility pass — the hardening phase audits and fixes gaps, it
  doesn't retrofit basic keyboard support from zero.
- All server data flows through TanStack Query's cache; optimistic updates
  (rating, rejection, shelf membership) are implemented as query-cache
  mutations with rollback, not local component state that could drift from
  the server.
