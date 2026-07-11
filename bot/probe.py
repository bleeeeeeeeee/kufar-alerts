from __future__ import annotations

import html

from bot.database import Alert, Database
from bot.kufar import KufarClient
from bot.time_utils import is_ad_after_alert_created


async def probe_alert(db: Database, kufar: KufarClient, alert: Alert) -> str:
    """Run a live Kufar search and show a short status for the subscription."""
    try:
        ads = await kufar.search(**alert.search_params)
    except Exception as exc:
        return f"⚠️ Не удалось проверить поиск: {html.escape(str(exc))}"

    ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
    new_ids = await db.filter_unseen(alert.id, ad_ids)
    new_id_set = set(new_ids)
    eligible = [
        ad
        for ad in ads
        if int(ad.get("ad_id", 0)) in new_id_set and is_ad_after_alert_created(ad, alert.created_at)
    ]

    lines = [
        f"🔍 <b>Проверка «{html.escape(alert.name)}»</b>",
        "",
        f"📥 Найдено на Kufar: <b>{len(ads)}</b>",
        f"🔔 К уведомлению: <b>{len(eligible)}</b>",
    ]

    if eligible:
        sample = eligible[0]
        subject = html.escape((sample.get("subject") or "—")[:60])
        lines.append(f"\n📌 Следующее: <i>{subject}</i>")
    elif not ads:
        lines.append("\nПо этим фильтрам сейчас ничего нет.")

    return "\n".join(lines)
