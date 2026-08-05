"""Tests for the opaque keyset-pagination cursor codec
(``shared/pagination/``, used by GET /me/ratings and GET /shelves/{id}/books)."""

from __future__ import annotations

import base64

import pytest

from book_app.shared.pagination import InvalidCursorError, decode_cursor, encode_cursor


def test_round_trip_preserves_payload() -> None:
    payload = {"k": "some value", "book_id": 42}
    assert decode_cursor(encode_cursor(payload)) == payload


def test_round_trip_preserves_nested_and_numeric_types() -> None:
    payload = {"k": 4.5, "book_id": 1, "nested": {"a": [1, 2, 3]}}
    assert decode_cursor(encode_cursor(payload)) == payload


def test_encoded_cursor_is_url_safe() -> None:
    payload = {"k": "value/with+special=chars", "book_id": 1}
    cursor = encode_cursor(payload)
    assert "/" not in cursor
    assert "+" not in cursor


@pytest.mark.parametrize(
    "garbage",
    ["not-valid-base64!!", "not-json", "####", "", base64.urlsafe_b64encode(b"[1, 2, 3]").decode()],
)
def test_garbage_input_raises_invalid_cursor_error(garbage: str) -> None:
    """Covers undecodable base64, non-JSON payloads, and valid JSON that
    isn't a dict (a cursor must always be a JSON object, not e.g. a list)."""
    with pytest.raises(InvalidCursorError):
        decode_cursor(garbage)


def test_encode_is_deterministic_for_the_same_payload() -> None:
    """sort_keys=True in the encoder means dict key order never changes the
    resulting cursor string — relevant since callers build the payload dict
    with keyword-ish literals whose insertion order isn't guaranteed to
    match across call sites."""
    payload_one = {"k": 1, "book_id": 2}
    payload_two = {"book_id": 2, "k": 1}
    assert encode_cursor(payload_one) == encode_cursor(payload_two)
