"""CLI: inspect a reader's semantic profile (rec-spec §13).

    make inspect-recommender-profile USERNAME=demo_reader
    make inspect-recommender-profile USERNAME=demo_reader ARGS=--json

rec-spec §13 makes this a required feature rather than a debugging
convenience: inferred interests must be human-inspectable, and the
inspection "must reuse the **same profiling code** used by the live
recommender. Do not create a second debug-only clustering implementation."

It does, structurally: this file builds the same ``UserContext`` the
recommendation service builds, hands it to the same
``build_semantic_profile``, and prints what comes back. There is no
clustering logic here to drift.

No raw vectors are printed (rec-spec §13). The output is ids, words and
counts.
"""

from __future__ import annotations

import argparse
import json
import sys

from book_recommender.artifacts import load_content_artifact, load_item_metadata_artifact
from book_recommender.exceptions import IncompatibleArtifactError
from book_recommender.profiling import ProfileSummary, build_semantic_profile, summarize
from sqlalchemy import select
from sqlalchemy.orm import Session

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging
from book_app.modules.recommendations.artifact_paths import (
    build_artifact_storage,
    read_catalog_snapshot,
)
from book_app.modules.recommendations.context_builder import build_user_context
from book_app.modules.shelves.models import Shelf
from book_app.modules.users.models import User


def _shelf_names(session: Session, user_id: object) -> dict[str, str]:
    stmt = select(Shelf.id, Shelf.name).where(Shelf.user_id == user_id)
    return {str(shelf_id): name for shelf_id, name in session.execute(stmt)}


def _render(summary: ProfileSummary, *, profile_version: str, username: str) -> str:
    lines = [
        f"Profile for {username}",
        f"  profile_version : {profile_version}",
        f"  strategy        : {summary.strategy}",
        f"  evidence items  : {summary.evidence_count}",
    ]
    lines += [f"  note            : {note}" for note in summary.notes]

    lines += ["", f"Inferred interests ({len(summary.interests)}):"]
    if not summary.interests:
        lines.append("  (none — not enough positive evidence)")
    for interest in summary.interests:
        lines.append(f"  [{interest.interest_id}] {interest.label}")
        lines.append(
            f"      weight {interest.weight:.1f} · {interest.member_count} book(s) · "
            f"coherence {interest.coherence:.2f}"
        )
        lines.append(
            f"      representative: #{interest.representative_book_id} "
            f"{interest.representative_title!r}"
        )
        if interest.top_terms:
            lines.append(f"      top terms : {', '.join(interest.top_terms)}")
        if interest.top_genres:
            lines.append(f"      top genres: {', '.join(interest.top_genres)}")
        lines.append(f"      why       : {interest.evidence_summary}")
        lines.append(f"      members   : {list(interest.member_book_ids)}")

    lines += ["", f"Explicit shelves ({len(summary.shelves)}):"]
    if not summary.shelves:
        lines.append("  (none)")
    for shelf in summary.shelves:
        lines.append(f"  {shelf.shelf_name or shelf.shelf_id}: {shelf.label}")
        lines.append(
            f"      {shelf.member_count} book(s) · representative "
            f"#{shelf.representative_book_id} {shelf.representative_title!r}"
        )
        if shelf.top_terms:
            lines.append(f"      top terms : {', '.join(shelf.top_terms)}")

    if summary.unembedded_book_ids:
        lines += ["", f"Books without embeddings: {list(summary.unembedded_book_ids)}"]
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a user's semantic interest profile.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    storage = build_artifact_storage(settings)

    try:
        with session_factory() as session:
            user = session.scalar(select(User).where(User.username == args.username))
            if user is None:
                print(f"error: no user named {args.username!r}", file=sys.stderr)
                return 1

            catalog = read_catalog_snapshot(session)
            try:
                embeddings = load_content_artifact(storage, catalog=catalog)
                metadata = load_item_metadata_artifact(storage, catalog=catalog)
            except IncompatibleArtifactError as exc:
                print(
                    f"error: semantic profiling needs the content and item-metadata "
                    f"artifacts ({exc}). Run 'make build-content' and "
                    f"'make build-item-metadata'.",
                    file=sys.stderr,
                )
                return 1

            context = build_user_context(session, user_id=user.id)
            names = _shelf_names(session, user.id)

        profile = build_semantic_profile(context, embeddings)
        summary = summarize(profile, metadata, shelf_names=names)
    finally:
        engine.dispose()

    if args.json:
        print(
            json.dumps(
                {
                    "username": args.username,
                    "profile_version": context.profile_version,
                    **summary.as_dict(),
                },
                indent=2,
            )
        )
    else:
        print(_render(summary, profile_version=context.profile_version, username=args.username))
    return 0


if __name__ == "__main__":
    sys.exit(main())
