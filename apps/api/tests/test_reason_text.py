"""User-facing reason prose (rec-spec §21, spec §10.9).

Codes are the stable contract and this prose is presentational — but
"presentational" does not mean "free". rec-spec §21: "A user-facing reason
must correspond to real evidence, not whichever reason string is
convenient." A wrong string here is a lie told to every reader who sees it.
"""

from __future__ import annotations

import pytest
from book_recommender.contracts.reasons import ReasonCode

from book_app.modules.recommendations.schemas import REASON_TEXT


def test_every_reason_code_has_prose() -> None:
    """A code with no entry would render as a raw enum name in the UI."""
    assert {code.value for code in ReasonCode} == set(REASON_TEXT)


def test_no_two_codes_share_prose() -> None:
    """Two codes rendering identically makes the distinction invisible to
    the reader, which is the same as not having made it."""
    assert len(set(REASON_TEXT.values())) == len(REASON_TEXT)


def test_semantic_matches_do_not_claim_the_reader_searched() -> None:
    """The regression R8's live smoke test caught.

    ``SEMANTIC_QUERY_MATCH`` is emitted when a candidate matches an
    *inferred interest* (rec-spec §12.2). It read "Matches your search",
    so a reader who had done nothing but complete onboarding was told their
    entire Home feed matched a search they never ran — and search has no
    producer in the application at all.
    """
    prose = REASON_TEXT[ReasonCode.SEMANTIC_QUERY_MATCH.value]
    assert "search" not in prose.lower()


@pytest.mark.parametrize(
    ("code", "forbidden"),
    [
        # Each of these claims a specific action. Claiming one the reader
        # did not take is exactly what rec-spec §21 forbids, and taste
        # seeds are neither ratings nor shelf saves (ADR-0019).
        (ReasonCode.POPULAR_WITH_READERS, ("you", "your")),
        (ReasonCode.EXPLORATION, ("saved", "rated", "search")),
        (ReasonCode.SIMILAR_TO_CURRENT_BOOK, ("saved", "rated")),
    ],
)
def test_prose_does_not_claim_evidence_its_code_does_not_carry(
    code: ReasonCode, forbidden: tuple[str, ...]
) -> None:
    words = REASON_TEXT[code.value].lower().split()
    assert not (set(words) & set(forbidden))
