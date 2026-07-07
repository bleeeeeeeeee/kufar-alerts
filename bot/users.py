from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DISPLAY_FIELD_LABELS: dict[str, str] = {
    "price": "Цена",
    "location": "Место",
    "category": "Категория",
    "condition": "Состояние",
    "delivery": "Доставка",
    "seller": "Продавец",
    "posted_at": "Дата публикации",
    "details": "Характеристики",
}

DISPLAY_FIELD_ICONS: dict[str, str] = {
    "price": "💰",
    "location": "📍",
    "category": "📂",
    "condition": "✨",
    "delivery": "📦",
    "seller": "👤",
    "posted_at": "🕐",
    "details": "📋",
}


@dataclass
class NotificationDisplay:
    price: bool = True
    location: bool = True
    category: bool = True
    condition: bool = True
    delivery: bool = True
    seller: bool = True
    posted_at: bool = True
    details: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NotificationDisplay:
        if not data:
            return cls()
        defaults = cls()
        return cls(
            **{
                key: bool(data.get(key, getattr(defaults, key)))
                for key in DISPLAY_FIELD_LABELS
            }
        )

    def to_dict(self) -> dict[str, bool]:
        return {key: bool(getattr(self, key)) for key in DISPLAY_FIELD_LABELS}


@dataclass
class UserSettings:
    photos_enabled: bool = True
    auto_clear_chat: bool = True
    notification_topic_id: int | None = None
    notification_display: NotificationDisplay = field(default_factory=NotificationDisplay)
    poll_interval: int | None = None
    notify_cooldown: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UserSettings:
        if not data:
            return cls()
        topic_id = data.get("notification_topic_id")
        poll_interval = data.get("poll_interval")
        notify_cooldown = int(data.get("notify_cooldown") or 0)
        return cls(
            photos_enabled=bool(data.get("photos_enabled", True)),
            auto_clear_chat=bool(data.get("auto_clear_chat", True)),
            notification_topic_id=int(topic_id) if topic_id else None,
            notification_display=NotificationDisplay.from_dict(data.get("notification_display")),
            poll_interval=int(poll_interval) if poll_interval else None,
            notify_cooldown=max(0, notify_cooldown),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "photos_enabled": self.photos_enabled,
            "auto_clear_chat": self.auto_clear_chat,
            "notification_display": self.notification_display.to_dict(),
            "notify_cooldown": self.notify_cooldown,
        }
        if self.notification_topic_id is not None:
            data["notification_topic_id"] = self.notification_topic_id
        if self.poll_interval is not None:
            data["poll_interval"] = self.poll_interval
        return data

    def effective_poll_interval(self, default: int) -> int:
        return self.poll_interval if self.poll_interval is not None else default


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
