from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


PermissionDecision = Literal["allow", "ask", "deny"]


class ValidationResult(BaseModel):
    ok: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        return cls(ok=False, reason=reason)


class PermissionResult(BaseModel):
    decision: PermissionDecision
    reason: str | None = None
    source: str | None = None

    @classmethod
    def allow(cls, *, reason: str | None = None, source: str | None = None) -> "PermissionResult":
        return cls(decision="allow", reason=reason, source=source)

    @classmethod
    def ask(cls, *, reason: str | None = None, source: str | None = None) -> "PermissionResult":
        return cls(decision="ask", reason=reason, source=source)

    @classmethod
    def deny(cls, *, reason: str | None = None, source: str | None = None) -> "PermissionResult":
        return cls(decision="deny", reason=reason, source=source)
