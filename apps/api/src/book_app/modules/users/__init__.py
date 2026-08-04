"""User identity (spec §8.1). Registration/login/session orchestration lives
in ``modules/auth`` — this module owns the ``User`` resource itself: the
persistence model, username validation rules, and basic CRUD.
"""

from __future__ import annotations
