/**
 * Same-origin reverse proxy: `/api/*` on the Pages domain -> the Cloud Run API.
 *
 * Why this exists
 * ---------------
 * The frontend authenticates with cookies (`credentials: 'include'`, plus a
 * readable `csrf_token` mirrored into `X-CSRF-Token`). Served from
 * `*.pages.dev` and calling `*.run.app` directly, those are **third-party**
 * cookies — two different registrable domains. Safari has blocked third-party
 * cookies outright since 13.1, and Chrome is phasing them out, so login would
 * return 200 and then silently not work: the cookie is set, dropped by the
 * browser, and every following request is unauthenticated.
 *
 * Routing the API through the Pages origin makes the cookies first-party, so
 * they work in every browser. It also removes CORS from the picture entirely —
 * same origin, no preflights, no `CORS_ALLOW_ORIGINS` to keep in sync — and
 * lets the cookies tighten from `SameSite=none` to `SameSite=lax`.
 *
 * The alternative is a custom domain (`app.example.com` + `api.example.com`),
 * which is the better answer for a real product and needs no proxy. This is
 * the free one.
 *
 * Configuration: `API_ORIGIN` is a Pages environment variable holding the
 * Cloud Run service URL. It is not a secret — it is a public URL — but it does
 * differ per environment, which is exactly what env vars are for.
 */

interface Env {
  API_ORIGIN?: string
}

interface PagesContext {
  request: Request
  env: Env
}

/** Methods that cannot carry a request body (fetch rejects one outright). */
const BODYLESS_METHODS = new Set(['GET', 'HEAD'])

export async function onRequest(context: PagesContext): Promise<Response> {
  const { request, env } = context
  const apiOrigin = env.API_ORIGIN

  if (!apiOrigin) {
    // Loud, not silent: a proxy with nowhere to proxy to would otherwise look
    // like an application error rather than a missing deployment variable.
    return new Response(
      JSON.stringify({
        error: {
          code: 'PROXY_MISCONFIGURED',
          message: 'API_ORIGIN is not set on this Pages deployment.',
        },
      }),
      { status: 500, headers: { 'content-type': 'application/json' } },
    )
  }

  const incoming = new URL(request.url)
  const target = new URL(incoming.pathname + incoming.search, apiOrigin)

  const headers = new Headers(request.headers)
  // `Host` must describe the upstream, not the proxy; fetch sets it correctly
  // once removed. Everything else — Cookie, X-CSRF-Token, Content-Type — is
  // forwarded untouched, which is what makes the session work.
  headers.delete('host')

  const upstream = await fetch(target.toString(), {
    method: request.method,
    headers,
    body: BODYLESS_METHODS.has(request.method) ? undefined : request.body,
    // Deliberately NOT following redirects. `GET /api/v1/covers/{key}` answers
    // 307 to the public R2 bucket; following it here would stream ~102k cover
    // images through this worker instead of letting the browser fetch them
    // straight from the CDN. Passing the 307 through is the entire point of
    // that route.
    redirect: 'manual',
  })

  // Copying the Response this way preserves the status line and *all* headers,
  // including repeated `Set-Cookie` entries — a plain object spread would
  // collapse the three session cookies into one.
  return new Response(upstream.body, upstream)
}
