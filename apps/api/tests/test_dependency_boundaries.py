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


#: The only modules allowed to import the training stack. Both are offline
#: build code, reached from a CLI and never from a request path.
OFFLINE_ONLY_MODULES = {
    "modules/recommendations/cf_training.py",
    "modules/recommendations/content_encoding.py",
}

_ENCODER_IMPORTS = ("import torch", "import sentence_transformers", "import transformers")


def test_only_designated_offline_modules_import_the_training_stack() -> None:
    """R5 legitimately needs an encoder module, so the rule is no longer
    "nobody imports it" — it is "only these two files do, and they are
    offline builders". Widening this list should be a deliberate act."""
    source_root = APP_ROOT / "src"
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root / "book_app").as_posix()
        text = path.read_text()
        for forbidden in _ENCODER_IMPORTS:
            if forbidden in text:
                assert relative in OFFLINE_ONLY_MODULES, (
                    f"{relative} imports the training stack ({forbidden!r}); only "
                    f"{sorted(OFFLINE_ONLY_MODULES)} may (ADR-0018/ADR-0021)"
                )


def test_importing_the_api_does_not_pull_in_a_text_encoder() -> None:
    """The behavioural guarantee a source grep cannot give: after importing
    the FastAPI application, no transformer module is in ``sys.modules``.

    This is what ADR-0018 promises — "The API must not load the 0.6B text
    model to serve recommendations."

    Scope, stated precisely because it was checked rather than assumed: this
    covers the *import graph reachable from* ``book_app.main``. Adding an
    encoder import to a module the app does not import — a CLI, or
    ``semantic_profile`` while nothing in the serving path uses it yet —
    would not fail here; that is what
    ``test_only_designated_offline_modules_import_the_training_stack``
    covers. The two together are the guard. When R6 wires semantic
    generators into serving, ``semantic_profile`` enters this graph and this
    test starts covering it too.
    """
    import subprocess
    import sys

    probe = (
        "import book_app.main, sys; "
        "loaded = [m for m in sys.modules "
        "if m.split('.')[0] in {'torch', 'transformers', 'sentence_transformers'}]; "
        "print(','.join(sorted(loaded)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        f"importing the API loaded transformer modules: {result.stdout.strip()}"
    )
