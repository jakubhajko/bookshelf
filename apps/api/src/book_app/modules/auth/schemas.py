"""Request schemas for auth endpoints (spec §9.1).

No Pydantic length/format constraints on password fields — see
``service.py``'s module docstring for why (a Pydantic validation error
echoes the submitted value in its error details, and passwords must never
appear in a response body, spec §6.3). Real validation happens in
``service.py``; these are deliberately thin.
"""

from __future__ import annotations

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str
    password_confirmation: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirmation: str
