from __future__ import annotations

import logging

from bot.database import Alert, Database
from bot.time_utils import is_ad_after_alert_created
from bot.kufar import KufarClient

logger = logging.getLogger(__name__)


async def seed_alert(
    db: Database,
    kufar: KufarClient,
    alert: Alert,
    *,
    clear_first: bool = False,
) -> int:
    """Mark current search results as seen so only future ads trigger notifications."""
    if clear_first:
        await db.clear_seen(alert.id)

    try:
        ads = await kufar.search(**alert.search_params)
    except Exception:
        logger.exception("Failed to search while seeding alert %s", alert.id)
        return -1

    ad_ids = [
        int(ad["ad_id"])
        for ad in ads
        if ad.get("ad_id") and is_ad_after_alert_created(ad, alert.created_at)
    ]
    await db.seed_seen(alert.id, ad_ids)
    logger.info("Seeded alert %s with %s ads", alert.id, len(ad_ids))
    return len(ad_ids)


async def activate_alert_after_seed(
    db: Database,
    kufar: KufarClient,
    alert: Alert,
    *,
    clear_first: bool = False,
) -> int:
    """Seed current results, then enable polling for the alert."""
    seeded = await seed_alert(db, kufar, alert, clear_first=clear_first)
    if seeded >= 0:
        await db.set_alert_active(alert.id, alert.user_id, True)
    return seeded
