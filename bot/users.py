from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserSettings:
    photos_enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UserSettings:
        if not data:
            return cls()
        return cls(photos_enabled=bool(data.get("photos_enabled", True)))

    def to_dict(self) -> dict[str, Any]:
        return {"photos_enabled": self.photos_enabled}


@dataclass
class User:
    user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str = "user"
    active: bool = True
    settings: UserSettings = field(default_factory=UserSettings)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def display_name(self) -> str:
        parts = [self.first_name or "", self.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        if name:
            return name
        if self.username:
            return f"@{self.username}"
        return str(self.user_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "role": self.role,
            "active": self.active,
            "settings": self.settings.to_dict(),
            "display_name": self.display_name,
        }
