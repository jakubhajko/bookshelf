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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

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


@router.get("/{object_key}")
def get_cover(
    object_key: str, storage: LocalFileStorage = Depends(get_cover_storage)
) -> FileResponse:
    try:
        path = storage.resolve(object_key)
    except UnsafeObjectKeyError as exc:
        raise CoverNotFoundError from exc
    if not path.is_file():
        raise CoverNotFoundError
    # Dataset contract (spec §7.3): every cover is a `.jpg` — a fixed,
    # documented content type, not a guess (no `mimetypes` dependency needed).
    return FileResponse(path, media_type="image/jpeg")
