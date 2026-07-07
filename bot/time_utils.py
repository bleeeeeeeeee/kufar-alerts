from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_iso_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if "T" not in raw and " " in raw:
            raw = raw.replace(" ", "T", 1)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def is_ad_after_alert_created(ad: dict[str, Any], created_at: str | None) -> bool:
    """True if the ad was listed after the subscription was created."""
    if not created_at:
        return True

    alert_time = parse_iso_time(created_at)
    ad_time = parse_iso_time(ad.get("list_time"))
    if alert_time is None or ad_time is None:
        return True
    return ad_time > alert_time
