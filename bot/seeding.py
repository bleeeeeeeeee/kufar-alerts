from __future__ import annotations

import asyncio
import logging

from bot.database import Alert, Database
from bot.kufar import KufarClient
from bot.time_utils import is_ad_after_alert_created

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

    ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
    await db.seed_seen(alert.id, ad_ids)
    logger.info("Seeded alert %s with %s ads (all current search results)", alert.id, len(ad_ids))
    return len(ad_ids)


async def bootstrap_active_alerts(db: Database, kufar: KufarClient) -> None:
    """On startup: only initialize alerts that have never been synced."""
    alerts = await db.get_active_alerts()
    if not alerts:
        return

    initialized = 0
    for alert in alerts:
        try:
            if await db.count_seen(alert.id) > 0:
                continue
            await seed_alert(db, kufar, alert, clear_first=False)
            initialized += 1
        except Exception:
            logger.exception("Bootstrap sync failed for alert %s", alert.id)
        await asyncio.sleep(0.3)

    if initialized:
        logger.info("Bootstrap initialized %s alert(s) with empty seen history", initialized)


async def auto_heal_unseen(
    db: Database,
    kufar: KufarClient,
    alert: Alert,
    ads: list[dict],
    unseen_ids: list[int],
) -> bool:
    """
    If many unseen ads are all older than the subscription, merge-sync once
    instead of processing them one-by-one every poll.
    """
    if len(unseen_ids) < 3:
        return False

    unseen_set = set(unseen_ids)
    unseen_ads = [ad for ad in ads if int(ad.get("ad_id", 0)) in unseen_set]
    if not unseen_ads:
        return False

    if any(is_ad_after_alert_created(ad, alert.created_at) for ad in unseen_ads):
        return False

    n = await seed_alert(db, kufar, alert, clear_first=False)
    if n >= 0:
        logger.info(
            "Auto-synced alert %s: merged %s ads (%s were stale unseen)",
            alert.id,
            n,
            len(unseen_ids),
        )
        return True
    return False


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
