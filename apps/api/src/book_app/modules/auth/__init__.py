"""Authentication: sessions, tokens, CSRF, and the register/login/refresh/
logout/me/change-password endpoints (spec §6, §9.1). Depends on
``modules/users`` for the ``User`` resource itself.
"""

from __future__ import annotations
