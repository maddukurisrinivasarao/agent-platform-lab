"""Mock short-lived credential broker that issues scoped, expiring tokens for tool calls."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable


class CredentialError(Exception):
    """Raised when a credential is unknown, expired, revoked, or used outside its scope."""


@dataclass(frozen=True)
class Credential:
    credential_id: str
    scope: str
    expires_at: datetime
    token: str = field(repr=False)


class CredentialBroker:
    def __init__(
        self,
        ttl_seconds: float = 60.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("Credential TTL cannot be negative.")
        self.ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._active: dict[str, Credential] = {}

    def issue(self, scope: str) -> Credential:
        credential = Credential(
            credential_id=f"cred-{secrets.token_hex(4)}",
            scope=scope,
            expires_at=self._clock() + self.ttl,
            token=f"mock-{secrets.token_urlsafe(16)}",
        )
        self._active[credential.credential_id] = credential
        return credential

    def validate(self, token: str, scope: str) -> Credential:
        credential = next(
            (item for item in self._active.values() if secrets.compare_digest(item.token, token)),
            None,
        )
        if credential is None:
            raise CredentialError("Credential is unknown or revoked.")
        if credential.scope != scope:
            raise CredentialError(
                f"Credential {credential.credential_id} is scoped to '{credential.scope}', not '{scope}'."
            )
        if self._clock() >= credential.expires_at:
            self.revoke(credential.credential_id)
            raise CredentialError(f"Credential {credential.credential_id} has expired.")
        return credential

    def revoke(self, credential_id: str) -> None:
        self._active.pop(credential_id, None)

    @property
    def active_count(self) -> int:
        return len(self._active)
