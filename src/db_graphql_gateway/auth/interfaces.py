from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AuthContext:
    user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    claims: dict[str, Any] = field(default_factory=dict)
    is_authenticated: bool = False
    error: str | None = None


class AuthenticationProvider(Protocol):
    async def authenticate(self, headers: dict[str, str]) -> AuthContext: ...
