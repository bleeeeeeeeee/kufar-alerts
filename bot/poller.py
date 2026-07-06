from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot.database import Alert, Database
from bot.kufar import KufarClient, format_ad_message, get_image_url

logger = logging.getLogger(__name__)


class AlertPoller:
    def __init__(
        self,
        bot: Bot,
        db: Database,
        kufar: KufarClient,
        interval: int,
    ) -> None:
        self.bot = bot
        self.db = db
        self.kufar = kufar
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="alert-poller")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        logger.info("Poller started, interval=%ss", self.interval)
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Poller iteration failed")
            await asyncio.sleep(self.interval)

    async def _poll_once(self) -> None:
        alerts = await self.db.get_active_alerts()
        if not alerts:
            return

        for alert in alerts:
            try:
                await self._check_alert(alert)
            except Exception:
                logger.exception("Failed to check alert %s", alert.id)
            await asyncio.sleep(1)

    async def _check_alert(self, alert: Alert) -> None:
        ads = await self.kufar.search(**alert.search_params)
        if not ads:
            return

        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        new_ids = await self.db.filter_unseen(alert.id, ad_ids)
        if not new_ids:
            return

        new_id_set = set(new_ids)
        new_ads = [ad for ad in ads if int(ad.get("ad_id", 0)) in new_id_set]
        new_ads.sort(key=lambda ad: ad.get("list_time", ""), reverse=True)

        for ad in new_ads:
            await self._notify(alert, ad)
            await asyncio.sleep(0.5)

        await self.db.mark_seen(alert.id, new_ids)

    async def _notify(self, alert: Alert, ad: dict) -> None:
        text = (
            f"🆕 <b>Новое объявление</b>\n"
            f"Подписка: <i>{alert.name}</i>\n\n"
            f"{format_ad_message(ad, self.kufar)}"
        )
        image_url = None
        images = ad.get("images") or []
        if images:
            image_url = get_image_url(images[0])

        try:
            if image_url:
                await self.bot.send_photo(
                    alert.user_id,
                    photo=image_url,
                    caption=text,
                    parse_mode="HTML",
                )
            else:
                await self.bot.send_message(
                    alert.user_id,
                    text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
        except Exception:
            logger.exception("Failed to notify user %s about ad %s", alert.user_id, ad.get("ad_id"))
