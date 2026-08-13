"""Repository-hygiene test: the API runtime must not carry the training stack.

ADR-0018 and CLAUDE.md ("Keep training-only dependencies separated from
lightweight API runtime dependencies where practical"). Recommender Phase R3
is the first phase to add numerical dependencies at all, so this guard exists
from the moment the door is open rather than after something walks through
it: the offline artifact build may use a transformer encoder freely, but the
API process loads matrices and never a model.

Where the training dependencies eventually live is a Phase R4/R5 decision —
a non-default dependency group is the intended shape. What this test fixes is
only where they must *not* live.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

#: NumPy is intentionally absent: the runtime reads ``.npy``/``.npz``
#: artifacts (ADR-0014), so it is a legitimate serving dependency.
FORBIDDEN_TRAINING_DEPENDENCY_PREFIXES = (
    "torch",
    "transformers",
    "sentence-transformers",
    "implicit",
    "scikit-learn",
    "sklearn",
    "datasets",
    "accelerate",
)

APP_ROOT = Path(__file__).resolve().parent.parent


def test_api_runtime_dependencies_exclude_the_training_stack() -> None:
    pyproject = tomllib.loads((APP_ROOT / "pyproject.toml").read_text())
    for dependency in pyproject["project"].get("dependencies", []):
        assert not dependency.lower().startswith(FORBIDDEN_TRAINING_DEPENDENCY_PREFIXES), (
            f"apps/api must not depend on {dependency!r} in its runtime dependency set "
            "(see docs/adr/0018-offline-swappable-text-embeddings.md)"
        )


def test_api_source_never_imports_a_text_encoder() -> None:
    """The declared dependency set is only half of it — an import that
    resolves transitively would load the model into the API process just the
    same."""
    for path in (APP_ROOT / "src").rglob("*.py"):
        text = path.read_text()
        for forbidden in ("import torch", "import sentence_transformers", "import transformers"):
            assert forbidden not in text, f"{path} must not import a text encoder ({forbidden!r})"
