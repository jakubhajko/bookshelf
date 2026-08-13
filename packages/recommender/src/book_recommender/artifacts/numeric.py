"""Compact numeric artifact payloads (ADR-0014, rec-spec §8).

ADR-0014: "Numeric payloads are compact NumPy ``.npy``/``.npz`` arrays
(memory-mapped where it helps), not large JSON arrays." This module is the
only place in the codebase that touches NumPy's serialization format, so
the offline builders and the runtime loaders cannot drift apart about it.

Three properties every helper here holds to:

*No pickle.* ``allow_pickle=False`` everywhere, on write and on read. A
NumPy file that unpickles arbitrary objects on load is a remote-code-
execution primitive pointed at whatever wrote the artifact directory; the
cost of forbidding it is that object arrays cannot be stored, which is
exactly why strings go through :func:`encode_strings` instead.

*Deterministic bytes.* ``np.savez`` builds its zip container with
``ZipInfo`` entries stamped from the wall clock, so two identical builds
produce different files and a checksum can never prove reproducibility.
:func:`save_arrays` writes the container itself with a fixed timestamp and
sorted member order, which makes byte-identical rebuilds testable (rec-spec
§28: "deterministic artifact build given same input/config").

*Path safety comes from the caller.* Every path here must already have been
resolved through ``LocalArtifactStorage.resolve``, which is what enforces
the storage root. These functions take a resolved ``Path`` and do not
re-derive one from user-controlled strings.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from book_recommender.exceptions import IncompatibleArtifactError

# Fixed zip member timestamp. 1980-01-01 is the zip format's own epoch — the
# earliest value it can represent — so it is the conventional choice for
# reproducible archives.
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_CHECKSUM_CHUNK_BYTES = 1 << 20


def save_array(path: Path, array: npt.NDArray[np.generic]) -> None:
    """Write a single array as ``.npy`` — the format that supports
    ``mmap_mode`` on load, so large matrices (ALS factors, embeddings)
    belong here rather than in an ``.npz``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.save(handle, array, allow_pickle=False)


def load_array(path: Path, *, mmap: bool = False) -> npt.NDArray[np.generic]:
    """Load a ``.npy``. With ``mmap=True`` the array is paged in from disk on
    access instead of read whole — worth it for a matrix that is large
    relative to the working set, not for a 92k-element id column."""
    if not path.is_file():
        raise IncompatibleArtifactError(f"missing artifact array: {path.name}")
    try:
        loaded = np.load(path, allow_pickle=False, mmap_mode="r" if mmap else None)
    except ValueError as exc:
        raise IncompatibleArtifactError(f"unreadable artifact array {path.name}: {exc}") from exc
    return np.asarray(loaded)


def save_arrays(path: Path, arrays: Mapping[str, npt.NDArray[np.generic]]) -> None:
    """Write several named arrays into one deterministic ``.npz``.

    Hand-rolled rather than ``np.savez`` for the reproducibility reason in
    the module docstring. The member payloads are written with NumPy's own
    ``write_array``, so the result is an ordinary ``.npz`` that ``np.load``
    reads without knowing anything about how it was produced.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(arrays):
            info = zipfile.ZipInfo(f"{name}.npy", date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(info, "w") as member:
                np.lib.format.write_array(member, arrays[name], allow_pickle=False)


def load_arrays(path: Path) -> dict[str, npt.NDArray[np.generic]]:
    """Load every member of an ``.npz`` eagerly into a plain dict.

    Eager rather than returning NumPy's lazy ``NpzFile`` on purpose: the
    lazy handle keeps the zip open, and an artifact loader that returns one
    would leave a file descriptor per artifact family open for the lifetime
    of the worker process.
    """
    if not path.is_file():
        raise IncompatibleArtifactError(f"missing artifact array bundle: {path.name}")
    try:
        with np.load(path, allow_pickle=False) as bundle:
            return {name: _require_array(path, name, bundle[name]) for name in bundle.files}
    except (ValueError, zipfile.BadZipFile) as exc:
        raise IncompatibleArtifactError(f"unreadable artifact bundle {path.name}: {exc}") from exc


def _require_array(path: Path, name: str, value: object) -> npt.NDArray[np.generic]:
    """NumPy hands back raw ``bytes`` for a zip member that is not in ``.npy``
    format — it does not unpickle it (``allow_pickle=False`` holds), but it
    also does not complain. Without this check a bundle member containing a
    pickle payload would flow onward as a zero-dimensional bytes array and
    fail somewhere much less informative."""
    if not isinstance(value, np.ndarray):
        raise IncompatibleArtifactError(
            f"artifact bundle {path.name} member {name!r} is not a NumPy array"
        )
    if value.dtype.hasobject:
        raise IncompatibleArtifactError(
            f"artifact bundle {path.name} member {name!r} has an object dtype"
        )
    return value


def encode_strings(values: Sequence[str]) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.uint8]]:
    """Encode strings as a UTF-8 blob plus ``n + 1`` offsets into it.

    The obvious alternative — a fixed-width NumPy unicode array — pads every
    entry to the longest one. For 92k book titles that is a ~500-character
    dtype at 4 bytes per character: roughly 185 MB to store maybe 6 MB of
    text. Offsets and a packed blob cost the text plus 8 bytes per row, and
    unlike an object array they need no pickle.
    """
    blob = "".join(values).encode("utf-8")
    offsets = np.zeros(len(values) + 1, dtype=np.int64)
    cursor = 0
    for index, value in enumerate(values):
        cursor += len(value.encode("utf-8"))
        offsets[index + 1] = cursor
    return offsets, np.frombuffer(blob, dtype=np.uint8).copy()


def decode_strings(offsets: npt.NDArray[np.int64], blob: npt.NDArray[np.uint8]) -> tuple[str, ...]:
    """Inverse of :func:`encode_strings`, validating the offsets rather than
    trusting them — a truncated or reordered blob would otherwise surface as
    mojibake in recommendation diagnostics instead of as a load failure."""
    if offsets.ndim != 1 or offsets.size == 0:
        raise IncompatibleArtifactError("string column offsets must be a non-empty 1-D array")
    if offsets[0] != 0 or int(offsets[-1]) != blob.size:
        raise IncompatibleArtifactError(
            f"string column offsets do not span the blob: "
            f"[{int(offsets[0])}, {int(offsets[-1])}] vs {blob.size} bytes"
        )
    if bool(np.any(np.diff(offsets) < 0)):
        raise IncompatibleArtifactError("string column offsets are not monotonic")
    raw = blob.tobytes()
    try:
        return tuple(
            raw[int(start) : int(end)].decode("utf-8")
            for start, end in zip(offsets[:-1], offsets[1:], strict=True)
        )
    except UnicodeDecodeError as exc:
        raise IncompatibleArtifactError(f"string column is not valid UTF-8: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHECKSUM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_int_array(
    arrays: Mapping[str, npt.NDArray[np.generic]], name: str, *, expected_size: int | None = None
) -> npt.NDArray[np.int64]:
    """Fetch a named integer column, failing loudly on a shape/dtype the
    rest of the loader would otherwise silently misinterpret."""
    array = _require_member(arrays, name)
    if array.ndim != 1 or not np.issubdtype(array.dtype, np.integer):
        raise IncompatibleArtifactError(
            f"artifact column {name!r} must be a 1-D integer array, got "
            f"{array.ndim}-D {array.dtype}"
        )
    _require_size(name, array.size, expected_size)
    return array.astype(np.int64, copy=False)


def require_float_array(
    arrays: Mapping[str, npt.NDArray[np.generic]], name: str, *, expected_size: int | None = None
) -> npt.NDArray[np.float64]:
    array = _require_member(arrays, name)
    if array.ndim != 1 or not np.issubdtype(array.dtype, np.floating):
        raise IncompatibleArtifactError(
            f"artifact column {name!r} must be a 1-D float array, got {array.ndim}-D {array.dtype}"
        )
    _require_size(name, array.size, expected_size)
    return array.astype(np.float64, copy=False)


def require_string_column(
    arrays: Mapping[str, npt.NDArray[np.generic]], name: str, *, expected_size: int | None = None
) -> tuple[str, ...]:
    """Read a string column stored as ``<name>_offsets`` + ``<name>_blob``."""
    offsets = _require_member(arrays, f"{name}_offsets").astype(np.int64, copy=False)
    blob = _require_member(arrays, f"{name}_blob").astype(np.uint8, copy=False)
    values = decode_strings(offsets, blob)
    _require_size(name, len(values), expected_size)
    return values


def string_column_arrays(name: str, values: Sequence[str]) -> dict[str, npt.NDArray[np.generic]]:
    """Builder-side counterpart of :func:`require_string_column`."""
    offsets, blob = encode_strings(values)
    return {f"{name}_offsets": offsets, f"{name}_blob": blob}


def _require_member(
    arrays: Mapping[str, npt.NDArray[np.generic]], name: str
) -> npt.NDArray[np.generic]:
    if name not in arrays:
        raise IncompatibleArtifactError(
            f"artifact bundle is missing column {name!r} (has: {_sorted_names(arrays)})"
        )
    return arrays[name]


def _require_size(name: str, actual: int, expected: int | None) -> None:
    if expected is not None and actual != expected:
        raise IncompatibleArtifactError(
            f"artifact column {name!r} has {actual} entries, expected {expected}"
        )


def _sorted_names(names: Iterable[str]) -> str:
    return ", ".join(sorted(names)) or "<empty>"
