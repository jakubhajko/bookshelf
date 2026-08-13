"""Offline text encoder (rec-spec §11.1, ADR-0018, ADR-0021).

The second module in the repository that imports the training stack — here
``sentence_transformers`` and, through it, ``torch``. Nothing on a request
path imports it, and `test_dependency_boundaries.py` fails if that changes.

rec-spec §11.1: "Documents/books are embedded offline. The API must not load
the 0.6B text model to serve recommendations." The API loads
``embeddings.npy``; this module is what produces it.

**Device selection is automatic and reported.** Apple MPS is used when
available because it is roughly an order of magnitude faster than CPU for
this model, but nothing depends on it — the same build runs on CPU, slower,
with identical output up to float tolerance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from book_recommender.config import EncoderConfig


def select_device(preferred: str | None = None) -> str:
    """``mps`` > ``cuda`` > ``cpu``, unless the caller insists."""
    import torch

    if preferred:
        return preferred
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


@dataclass
class TextEncoder:
    """Thin wrapper over ``SentenceTransformer``.

    Deliberately thin: rec-spec §11.1 says not to "hard-code Qwen-specific
    behavior into serving contracts", and the way to honour that is for this
    class to know only what ``EncoderConfig`` says — a name, a dimension, a
    length cap — with nothing model-specific in the interface.
    """

    config: EncoderConfig
    device: str

    def __post_init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(
            self.config.name,
            device=self.device,
            truncate_dim=self.config.dimension,
            revision=self.config.revision,
        )
        # The model's own default is 32,768 tokens. Capping is a cost
        # decision, not a model limit — see EncoderConfig.max_sequence_length.
        self._model.max_seq_length = self.config.max_sequence_length

    @property
    def resolved_dimension(self) -> int:
        return int(self._model.get_embedding_dimension())

    @property
    def resolved_revision(self) -> str | None:
        """The commit the hub actually served, when it can be recovered.

        rec-spec §11.1 asks for "a pinned revision/identifier when possible".
        Loading by tag records only the tag, which will silently mean a
        different model later; the resolved commit hash is what makes an
        embedding artifact reproducible. Best-effort by design — a locally
        cached or offline model may not expose one, and recording ``None``
        is more honest than inventing a pin.
        """
        if self.config.revision:
            return self.config.revision
        try:
            config = self._model[0].auto_model.config
        except (AttributeError, IndexError, KeyError):
            return None
        commit = getattr(config, "_commit_hash", None)
        return str(commit) if commit else None

    def encode(
        self, texts: Sequence[str], *, show_progress: bool = False
    ) -> npt.NDArray[np.float32]:
        """Encode to L2-normalized ``float32``.

        Normalization happens here rather than in the artifact writer so that
        it cannot be forgotten by a future caller: retrieval treats the dot
        product as cosine similarity, and the loader refuses an artifact that
        does not declare normalization.
        """
        if not texts:
            return np.empty((0, self.config.dimension), dtype=np.float32)
        vectors = self._model.encode(
            list(texts),
            batch_size=self.config.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )
        return np.ascontiguousarray(vectors, dtype=np.float32)
