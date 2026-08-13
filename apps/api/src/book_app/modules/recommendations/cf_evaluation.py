"""Offline CF evaluation: per-user holdout and ranking metrics
(rec-spec §23.1).

Pure NumPy — no ``scipy``, no ``implicit``, no database — so the metrics are
covered by the fast test suite rather than only exercised inside a training
run that takes minutes. That matters more than it sounds: a silently wrong
NDCG would not crash anything, it would just quietly pick the wrong model.

**The split is random per user, and says so.** rec-spec §23.1: "Historical
data has no timestamps, so use a documented per-user random/stratified
holdout rather than pretending it is temporal." Anything resembling a
"last N interactions" split here would be fabricating recency the dataset
does not have (CLAUDE.md: "Historical data has no timestamps; never invent
them").

**Metrics are computed over held-out positives only.** A user's training
items are excluded from their own recommendations before scoring, because
recommending a book back to the reader who already has it is trivially easy
and would flatter every model equally.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from book_recommender.config import HoldoutConfig


@dataclass(frozen=True)
class HoldoutSplit:
    """Train/test partition of one interaction dataset.

    ``train_mask`` selects the triplets a model may learn from;
    ``held_out_items`` maps a dense user index to the item indices withheld
    from it. Users absent from ``held_out_items`` are trained on in full and
    simply not evaluated.
    """

    train_mask: npt.NDArray[np.bool_]
    held_out_items: Mapping[int, npt.NDArray[np.int32]]
    config: HoldoutConfig

    @property
    def evaluated_user_count(self) -> int:
        return len(self.held_out_items)

    @property
    def train_row_count(self) -> int:
        return int(self.train_mask.sum())


def build_holdout(
    user_indices: npt.NDArray[np.int32],
    item_indices: npt.NDArray[np.int32],
    config: HoldoutConfig,
) -> HoldoutSplit:
    """Withhold a random fraction of each sufficiently-active user's items.

    A user with fewer than ``min_interactions`` positives keeps all of them:
    holding one of three items out measures the split more than the model,
    and dropping such users from *training* as well would throw away the
    long tail the coverage metric exists to watch.
    """
    rng = np.random.default_rng(config.random_state)
    train_mask = np.ones(user_indices.size, dtype=bool)
    held_out: dict[int, npt.NDArray[np.int32]] = {}

    order = np.argsort(user_indices, kind="stable")
    sorted_users = user_indices[order]
    boundaries = np.flatnonzero(np.diff(sorted_users)) + 1
    for group in np.split(order, boundaries):
        if group.size == 0:
            continue
        if group.size < config.min_interactions:
            continue
        take = min(int(math.floor(group.size * config.fraction)), config.max_held_out)
        if take < 1:
            continue
        chosen = rng.choice(group, size=take, replace=False)
        train_mask[chosen] = False
        held_out[int(user_indices[group[0]])] = np.unique(
            item_indices[chosen].astype(np.int32, copy=False)
        )

    return HoldoutSplit(train_mask=train_mask, held_out_items=held_out, config=config)


# --- Metrics ----------------------------------------------------------------


def recall_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    hits = len(set(ranked[:k]) & relevant)
    # Capped at k: a user with 40 held-out items cannot have more than k of
    # them in a k-length list, and dividing by 40 would score a perfect
    # ranking below 1.0 and make the metric incomparable across users.
    return hits / min(len(relevant), k)


def precision_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked[:k]) & relevant) / k


def ndcg_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Binary-relevance NDCG. The dataset gives no graded relevance for a
    held-out positive, so pretending otherwise would invent signal."""
    if not relevant:
        return 0.0
    gain = sum(
        1.0 / math.log2(position + 2)
        for position, item in enumerate(ranked[:k])
        if item in relevant
    )
    ideal = sum(1.0 / math.log2(position + 2) for position in range(min(len(relevant), k)))
    return gain / ideal if ideal else 0.0


def average_precision_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for position, item in enumerate(ranked[:k]):
        if item in relevant:
            hits += 1
            total += hits / (position + 1)
    return total / min(len(relevant), k)


def gini_coefficient(counts: npt.NDArray[np.float64]) -> float:
    """Popularity concentration (rec-spec §23.1).

    0 means every catalog item is recommended equally often; 1 means a
    single item absorbs every recommendation. This is the metric that
    catches a model whose Recall looks respectable purely because it
    recommends the same 50 bestsellers to everyone.
    """
    if counts.size == 0:
        return 0.0
    values = np.sort(counts.astype(np.float64, copy=False))
    total = values.sum()
    if total <= 0:
        return 0.0
    index = np.arange(1, values.size + 1, dtype=np.float64)
    return float(
        (2.0 * (index * values).sum()) / (values.size * total) - (values.size + 1) / values.size
    )


@dataclass(frozen=True)
class EvaluationResult:
    """One model configuration's offline scorecard."""

    label: str
    users_evaluated: int
    metrics: dict[str, float] = field(default_factory=dict)
    #: Fraction of the catalog appearing in anyone's top-K list.
    catalog_coverage: float = 0.0
    popularity_gini: float = 0.0
    config: dict[str, str | int | float | bool] = field(default_factory=dict)

    def primary(self, k: int) -> float:
        """The number the sweep selects on. NDCG rewards putting a held-out
        book near the top, not merely inside the page."""
        return self.metrics.get(f"ndcg@{k}", 0.0)

    def as_row(self, k: int) -> str:
        return (
            f"{self.label:<28} "
            f"recall@{k}={self.metrics.get(f'recall@{k}', 0):.4f}  "
            f"ndcg@{k}={self.metrics.get(f'ndcg@{k}', 0):.4f}  "
            f"map@{k}={self.metrics.get(f'map@{k}', 0):.4f}  "
            f"coverage={self.catalog_coverage:.3f}  "
            f"gini={self.popularity_gini:.3f}"
        )


def evaluate_rankings(
    label: str,
    rankings: Mapping[int, Sequence[int]],
    held_out_items: Mapping[int, npt.NDArray[np.int32]],
    *,
    k_values: Sequence[int],
    item_count: int,
    config: Mapping[str, str | int | float | bool] | None = None,
) -> EvaluationResult:
    """Score per-user ranked item lists against their held-out positives."""
    metrics: dict[str, list[float]] = {}
    recommended: dict[int, int] = {}
    evaluated = 0

    largest_k = max(k_values) if k_values else 0
    for user_index, ranked in rankings.items():
        relevant_array = held_out_items.get(user_index)
        if relevant_array is None or relevant_array.size == 0:
            continue
        evaluated += 1
        relevant = {int(item) for item in relevant_array}
        for item in ranked[:largest_k]:
            recommended[int(item)] = recommended.get(int(item), 0) + 1
        for k in k_values:
            metrics.setdefault(f"recall@{k}", []).append(recall_at_k(ranked, relevant, k))
            metrics.setdefault(f"precision@{k}", []).append(precision_at_k(ranked, relevant, k))
            metrics.setdefault(f"ndcg@{k}", []).append(ndcg_at_k(ranked, relevant, k))
            metrics.setdefault(f"map@{k}", []).append(average_precision_at_k(ranked, relevant, k))

    averaged = {name: float(np.mean(values)) for name, values in metrics.items()}
    coverage = len(recommended) / item_count if item_count else 0.0
    gini = gini_coefficient(np.asarray(list(recommended.values()), dtype=np.float64))

    return EvaluationResult(
        label=label,
        users_evaluated=evaluated,
        metrics=averaged,
        catalog_coverage=coverage,
        popularity_gini=gini,
        config=dict(config or {}),
    )


# --- Reporting --------------------------------------------------------------


def write_evaluation_report(
    root: Path,
    *,
    model_name: str,
    model_version: str,
    results: Sequence[EvaluationResult],
    selected: str,
    context: Mapping[str, Any],
) -> Path:
    """Persist the scorecard beside the build, not inside the artifact.

    rec-spec §23.1: "Persist evaluation configuration and summary metrics
    alongside build reports, not in serving artifacts if that would bloat
    them." Two files per build, deliberately: JSON for comparing runs
    programmatically, and a text table for the human deciding whether a
    number moved for a good reason.
    """
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{model_name}-{model_version}"

    payload = {
        "model_name": model_name,
        "model_version": model_version,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "selected": selected,
        "context": _jsonable(context),
        "results": [
            {
                "label": result.label,
                "users_evaluated": result.users_evaluated,
                "metrics": result.metrics,
                "catalog_coverage": result.catalog_coverage,
                "popularity_gini": result.popularity_gini,
                "config": result.config,
            }
            for result in results
        ],
    }
    json_path = root / f"{stem}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # The deepest cutoff, because that is the one the sweep selects on
    # (``SELECTION_K``). A table headed by @10 next to a decision made at @50
    # is how someone later concludes the builder picked the losing variant.
    k = max(
        (int(name.split("@")[1]) for result in results for name in result.metrics if "@" in name),
        default=10,
    )
    lines = [
        f"{model_name} evaluation — {model_version}",
        f"selected: {selected}",
        "",
        *(
            result.as_row(k) + ("   <- selected" if result.label == selected else "")
            for result in results
        ),
        "",
        "context:",
        *(f"  {key}: {value}" for key, value in sorted(_jsonable(context).items())),
    ]
    (root / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    return json_path


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
