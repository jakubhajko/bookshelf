"""Recommendation boundary module (spec §10, §11): typed context building,
eligibility/exclusion rules, provider orchestration, and persistence for
recommendation requests/results/impressions (spec §8.10).

Recommendation *algorithms* live in ``packages/recommender`` (spec §20: "no
recommendation algorithms in routes" — nor in this module's service either).
This module owns product eligibility, calls the typed provider boundary, and
persists what spec §9.9's cursor feeds need.
"""

from __future__ import annotations
