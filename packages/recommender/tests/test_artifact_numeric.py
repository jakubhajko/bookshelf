"""Numeric artifact primitives: no pickle, deterministic bytes, validated
string columns (ADR-0014)."""

from __future__ import annotations

import pickle
import zipfile
from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts.numeric import (
    decode_strings,
    encode_strings,
    load_array,
    load_arrays,
    require_float_array,
    require_int_array,
    require_string_column,
    save_array,
    save_arrays,
    sha256_file,
    string_column_arrays,
)
from book_recommender.exceptions import IncompatibleArtifactError


def test_array_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "scores.npy"
    save_array(path, np.array([3.0, 2.0, 1.0]))
    assert load_array(path).tolist() == [3.0, 2.0, 1.0]


def test_array_can_be_memory_mapped(tmp_path: Path) -> None:
    path = tmp_path / "big.npy"
    save_array(path, np.arange(1000, dtype=np.int64))
    mapped = load_array(path, mmap=True)
    assert int(mapped[999]) == 999


def test_missing_array_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    with pytest.raises(IncompatibleArtifactError):
        load_array(tmp_path / "absent.npy")


def test_arrays_round_trip_by_name(tmp_path: Path) -> None:
    path = tmp_path / "bundle.npz"
    save_arrays(path, {"a": np.array([1, 2]), "b": np.array([3.5])})
    loaded = load_arrays(path)
    assert loaded["a"].tolist() == [1, 2]
    assert loaded["b"].tolist() == [3.5]


def test_identical_input_produces_byte_identical_bundles(tmp_path: Path) -> None:
    """rec-spec §28's "deterministic artifact build given same input/config".

    ``np.savez`` stamps each zip member with the wall clock, so this fails
    against stock NumPy serialization — which is exactly why
    ``save_arrays`` writes the container itself.
    """
    arrays = {"scores": np.linspace(1.0, 0.0, 500), "ids": np.arange(500, dtype=np.int64)}
    first, second = tmp_path / "a.npz", tmp_path / "b.npz"
    save_arrays(first, arrays)
    save_arrays(second, arrays)
    assert first.read_bytes() == second.read_bytes()
    assert sha256_file(first) == sha256_file(second)


def test_bundle_member_order_does_not_depend_on_insertion_order(tmp_path: Path) -> None:
    first, second = tmp_path / "a.npz", tmp_path / "b.npz"
    save_arrays(first, {"x": np.array([1]), "y": np.array([2])})
    save_arrays(second, {"y": np.array([2]), "x": np.array([1])})
    assert first.read_bytes() == second.read_bytes()


def test_corrupt_bundle_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    path = tmp_path / "bundle.npz"
    path.write_bytes(b"not a zip file at all")
    with pytest.raises(IncompatibleArtifactError):
        load_arrays(path)


def test_pickled_payload_is_refused(tmp_path: Path) -> None:
    """A ``.npz`` whose member is a pickled object must not be unpickled on
    load — that would make an artifact directory an arbitrary-code-execution
    vector."""
    path = tmp_path / "evil.npz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.npy", pickle.dumps({"anything": "at all"}))
    with pytest.raises(IncompatibleArtifactError):
        load_arrays(path)


def test_string_column_round_trips_including_non_ascii() -> None:
    values = ["Dune", "Kraljevstvo Nebesko", "日本語のタイトル", "", "Ünicode"]
    offsets, blob = encode_strings(values)
    assert decode_strings(offsets, blob) == tuple(values)


def test_string_column_of_empty_sequence_round_trips() -> None:
    offsets, blob = encode_strings([])
    assert decode_strings(offsets, blob) == ()


def test_truncated_string_blob_is_rejected() -> None:
    offsets, blob = encode_strings(["alpha", "beta"])
    with pytest.raises(IncompatibleArtifactError, match="do not span the blob"):
        decode_strings(offsets, blob[:-2])


def test_non_monotonic_string_offsets_are_rejected() -> None:
    offsets, blob = encode_strings(["alpha", "beta", "gamma"])
    scrambled = offsets.copy()
    scrambled[1], scrambled[2] = scrambled[2], scrambled[1]
    with pytest.raises(IncompatibleArtifactError, match="not monotonic"):
        decode_strings(scrambled, blob)


def test_require_int_array_rejects_a_float_column() -> None:
    with pytest.raises(IncompatibleArtifactError, match="1-D integer array"):
        require_int_array({"ids": np.array([1.0, 2.0])}, "ids")


def test_require_float_array_rejects_a_2d_column() -> None:
    with pytest.raises(IncompatibleArtifactError, match="1-D float array"):
        require_float_array({"scores": np.zeros((2, 2))}, "scores")


def test_require_column_reports_what_the_bundle_actually_has() -> None:
    with pytest.raises(IncompatibleArtifactError, match="has: a, b"):
        require_int_array({"a": np.array([1]), "b": np.array([2])}, "missing")


def test_require_column_enforces_expected_size() -> None:
    with pytest.raises(IncompatibleArtifactError, match="has 2 entries, expected 3"):
        require_int_array({"ids": np.array([1, 2])}, "ids", expected_size=3)


def test_string_column_helpers_are_inverses() -> None:
    arrays = string_column_arrays("title", ["a", "bb", "ccc"])
    assert require_string_column(arrays, "title", expected_size=3) == ("a", "bb", "ccc")
