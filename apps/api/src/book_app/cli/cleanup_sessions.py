"""CLI: delete expired or revoked auth sessions (spec §11: "clean sessions").

    uv run --project apps/api python -m book_app.cli.cleanup_sessions [options]

or via ``make cleanup-sessions``. Bounds ``auth_sessions`` table growth —
nothing else deletes rows from it (revoke just sets ``revoked_at``).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.auth import repository as session_repository

logger = get_logger("book_app.cli.cleanup_sessions")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete expired or revoked auth sessions.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count matching sessions without deleting"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)

    now = datetime.now(UTC)
    try:
        with session_factory() as session, session.begin():
            deleted = session_repository.delete_expired_or_revoked(session, now=now)
            if args.dry_run:
                session.rollback()
    finally:
        engine.dispose()

    mode = "would delete" if args.dry_run else "deleted"
    print(f"cleanup_sessions: {mode} {deleted} expired/revoked session(s)")
    logger.info("cleanup_sessions_completed", deleted=deleted, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
