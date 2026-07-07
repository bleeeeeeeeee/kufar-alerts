from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserSettings:
    photos_enabled: bool = True
    auto_clear_chat: bool = True
    notification_topic_id: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UserSettings:
        if not data:
            return cls()
        topic_id = data.get("notification_topic_id")
        return cls(
            photos_enabled=bool(data.get("photos_enabled", True)),
            auto_clear_chat=bool(data.get("auto_clear_chat", True)),
            notification_topic_id=int(topic_id) if topic_id else None,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "photos_enabled": self.photos_enabled,
            "auto_clear_chat": self.auto_clear_chat,
        }
        if self.notification_topic_id is not None:
            data["notification_topic_id"] = self.notification_topic_id
        return data


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
