from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_ROLES = {"candidate", "recruiter", "admin", "owner"}


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        """
        Validates and normalizes an email address.
        """
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("Invalid email address")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _normalize_full_name(cls, value: str) -> str:
        """
        Normalizes a user full name.
        """
        return " ".join(value.strip().split())


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        """
        Validates and normalizes an email address.
        """
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("Invalid email address")
        return normalized


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str


class UpdateRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        """
        Validates and normalizes a user role.
        """
        role = value.lower().strip()
        if role not in VALID_ROLES:
            raise ValueError("Invalid role")
        return role
