from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot.database import Alert, Database
from bot.kufar import KufarClient, format_ad_message, get_image_urls
from bot.notifier import send_ad_notification
from bot.time_utils import is_ad_after_alert_created

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

        total_new = 0
        total_sent = 0

        for alert in alerts:
            try:
                new_count, sent_count = await self._check_alert(alert)
                total_new += new_count
                total_sent += sent_count
            except Exception:
                logger.exception("Failed to check alert %s", alert.id)
            await asyncio.sleep(0.5)

        if total_new:
            logger.info(
                "Poll done: %s alerts, %s new ads, %s notifications sent",
                len(alerts),
                total_new,
                total_sent,
            )

    async def _check_alert(self, alert: Alert) -> tuple[int, int]:
        ads = await self.kufar.search(**alert.search_params)
        if not ads:
            return 0, 0

        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        new_ids = await self.db.filter_unseen(alert.id, ad_ids)
        if not new_ids:
            return 0, 0

        new_id_set = set(new_ids)
        new_ads = [ad for ad in ads if int(ad.get("ad_id", 0)) in new_id_set]
        new_ads.sort(key=lambda ad: ad.get("list_time", ""), reverse=True)

        notified_ids: list[int] = []
        skipped_old_ids: list[int] = []
        for ad in new_ads:
            ad_id = int(ad["ad_id"])
            if not is_ad_after_alert_created(ad, alert.created_at):
                skipped_old_ids.append(ad_id)
                continue
            if await self._notify(alert, ad):
                notified_ids.append(ad_id)
            await asyncio.sleep(0.3)

        seen_ids = notified_ids + skipped_old_ids
        if seen_ids:
            await self.db.mark_seen(alert.id, seen_ids)

        failed = len(new_ads) - len(notified_ids)
        if failed:
            logger.warning(
                "Alert %s: %s/%s notifications failed, will retry next poll",
                alert.id,
                failed,
                len(new_ads),
            )

        return len(new_ads), len(notified_ids)

    async def _notify(self, alert: Alert, ad: dict) -> bool:
        text = (
            f"🆕 <b>Новое объявление</b>\n"
            f"📌 <i>{html.escape(alert.name)}</i>\n\n"
            f"{format_ad_message(ad, self.kufar)}"
        )
        image_urls = get_image_urls(ad)
        db_user = await self.db.get_user(alert.user_id)
        if db_user and not db_user.settings.photos_enabled:
            image_urls = []

        try:
            error = await send_ad_notification(
                self.bot,
                alert.user_id,
                text,
                image_urls,
                self.kufar.download_image,
                message_thread_id=db_user.settings.notification_topic_id if db_user else None,
            )
            if error is None:
                logger.info(
                    "Notified user %s about ad %s (alert %s)",
                    alert.user_id,
                    ad.get("ad_id"),
                    alert.id,
                )
                return True

            logger.error(
                "All delivery methods failed for user %s ad %s (alert %s)",
                alert.user_id,
                ad.get("ad_id"),
                alert.id,
            )
            return False

        except TelegramForbiddenError:
            logger.warning("User %s blocked the bot, pausing alert %s", alert.user_id, alert.id)
            await self.db.set_alert_active(alert.id, alert.user_id, False)
            return False
        except Exception:
            logger.exception(
                "Failed to notify user %s about ad %s (alert %s)",
                alert.user_id,
                ad.get("ad_id"),
                alert.id,
            )
            return False
