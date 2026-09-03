"""Cover image serving (spec §7.3, §14 "safe local cover paths", §20 "do not
construct cover paths in frontend").

Not a domain module (no service/repository/models, same reasoning as
``core/health.py``) — this is infrastructure, not one of spec §4.1's module
list. Deliberately unauthenticated, unlike every other route in this app:
cover art is public (same bytes regardless of who asks, ultimately sourced
from Goodreads/Open Library per ``data/README.md``), a browser `<img>` tag
never gets the frontend API client's session-refresh-and-retry treatment
(``apps/web/src/api/client.ts`` only wraps ``openapi-fetch`` calls), and the
short-lived access token (~15 minutes, spec §6.4) would otherwise turn every
cover into a broken image partway through an ordinary browsing session. Path
safety is enforced independently of authentication via
``LocalFileStorage.resolve`` (Phase 2), which is the actual security
boundary here.

Local backend only — spec §17 plans ``covers -> S3/CloudFront`` for AWS,
which would change this route to a redirect to a signed/public CloudFront
URL instead of streaming bytes. Either way the frontend contract stays
``GET /api/v1/covers/{object_key}``, so that swap needs no frontend change.
See ADR-0011.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse

from book_app.core.exceptions import CoverNotFoundError
from book_app.shared.storage.base import UnsafeObjectKeyError
from book_app.shared.storage.local import LocalFileStorage

router = APIRouter(prefix="/covers", tags=["covers"])

_REPO_ROOT = Path(__file__).resolve().parents[5]


def resolve_cover_storage_root(configured_path: Path) -> Path:
    """Same reasoning, same pattern, as
    ``modules/recommendations/artifact_paths.py``'s ``resolve_artifact_root``:
    ``Settings.cover_storage_local_path`` defaults to a bare relative path
    (``data/processed/covers``), and where that resolves depends entirely
    on the process's current working directory — ``apps/api/`` for `make
    dev-api` (its own ``cd apps/api &&``), the repo root for a plain
    ``python -m`` invocation, a Docker ``WORKDIR`` in production. Anchoring
    at the repo root instead makes every entrypoint agree on the same
    directory regardless of invocation style. Found by live-smoke-testing
    this route with `make dev-api`'s own launch convention — it 404'd on a
    cover verified to exist on disk, since `LocalFileStorage` was looking
    under `apps/api/data/processed/covers/` instead.
    """
    if configured_path.is_absolute():
        return configured_path
    return (_REPO_ROOT / configured_path).resolve()


def get_cover_storage(request: Request) -> LocalFileStorage:
    storage: LocalFileStorage = request.app.state.cover_storage
    return storage


#: A day. Long enough that a browser re-visiting the app does not re-ask the
#: API for a redirect it already has; short enough that repointing
#: ``cover_storage_public_base_url`` takes effect without a cache-busting
#: scheme. Cover bytes themselves are immutable — the CDN caches those.
_REDIRECT_CACHE_SECONDS = 86_400


def _public_cover_url(base_url: str, object_key: str) -> str:
    """Build the public URL for a cover, refusing anything but a plain name.

    ``LocalFileStorage.resolve`` guards the local backend by checking the
    resolved path stays under the storage root — a filesystem concept that has
    no meaning for an object store, where the key is one flat string. The
    equivalent guard here is that the key must be a plain filename: no
    separators, no ``.`` or ``..``. FastAPI's path converter already refuses a
    key containing ``/``, so this is defence in depth rather than the only
    check, and it keeps the two backends refusing the *same* inputs.
    """
    if not object_key or "/" in object_key or "\\" in object_key or object_key in {".", ".."}:
        raise UnsafeObjectKeyError(f"unsafe cover object key: {object_key!r}")
    return f"{base_url.rstrip('/')}/{quote(object_key)}"


# `response_model=None`: the return type is a union of two Response classes,
# which FastAPI would otherwise try to turn into a Pydantic response model.
# Neither branch returns JSON — one streams a file, the other redirects.
@router.get("/{object_key}", response_model=None)
def get_cover(
    object_key: str,
    request: Request,
    storage: LocalFileStorage = Depends(get_cover_storage),
) -> FileResponse | RedirectResponse:
    """Serve a cover, or point the browser at whoever does.

    The route contract is identical either way — ``GET /api/v1/covers/{key}``
    — which is what lets storage move without touching the frontend (spec §20
    forbids the frontend constructing cover paths, precisely so this stays
    swappable).

    With ``cover_storage_backend='s3'`` the API answers with a redirect rather
    than bytes. That is the whole point: 1.1 GB of images across ~102k files
    is served by a CDN with free egress instead of by a container that is
    billed per second and scales to zero.
    """
    settings = request.app.state.settings
    if settings.cover_storage_backend == "s3":
        base_url = settings.cover_storage_public_base_url
        if not base_url:  # pragma: no cover - Settings validation forbids this
            raise CoverNotFoundError
        try:
            url = _public_cover_url(base_url, object_key)
        except UnsafeObjectKeyError as exc:
            raise CoverNotFoundError from exc
        # 307 rather than 301: the mapping from key to origin is configuration,
        # not a permanent fact about the resource, and a 301 would be cached by
        # browsers essentially forever — including through a bucket change.
        return RedirectResponse(
            url,
            status_code=307,
            headers={"Cache-Control": f"public, max-age={_REDIRECT_CACHE_SECONDS}"},
        )

    try:
        path = storage.resolve(object_key)
    except UnsafeObjectKeyError as exc:
        raise CoverNotFoundError from exc
    if not path.is_file():
        raise CoverNotFoundError
    # Dataset contract (spec §7.3): every cover is a `.jpg` — a fixed,
    # documented content type, not a guess (no `mimetypes` dependency needed).
    return FileResponse(path, media_type="image/jpeg")
