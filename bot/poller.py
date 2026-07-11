from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot.notification_styles import DEFAULT_NOTIFICATION_STYLE, format_notification_message, normalize_notification_layout, normalize_notification_style
from bot.database import Alert, Database
from bot.notifier import send_ad_notification
from bot.seeding import auto_heal_unseen, bootstrap_active_alerts, seed_alert
from bot.time_utils import is_ad_after_alert_created
from bot.kufar import KufarClient, get_image_urls

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
        self.default_interval = interval
        self.interval = min(15, interval)
        self._task: asyncio.Task | None = None
        self._running = False
        self._alert_last_poll: dict[int, float] = {}
        self._user_last_notify: dict[int, float] = {}

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
        logger.info("Poller started, tick=%ss, default_interval=%ss", self.interval, self.default_interval)
        try:
            await bootstrap_active_alerts(self.db, self.kufar)
        except Exception:
            logger.exception("Startup bootstrap sync failed")
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
        checked = 0

        for alert in alerts:
            try:
                if not await self._should_poll_alert(alert):
                    continue
                checked += 1
                self._alert_last_poll[alert.id] = time.monotonic()
                new_count, sent_count = await self._check_alert(alert)
                total_new += new_count
                total_sent += sent_count
            except Exception:
                logger.exception("Failed to check alert %s", alert.id)
            await asyncio.sleep(0.5)

        if not checked:
            return

        if total_new:
            logger.info(
                "Poll done: %s checked, %s new ads, %s notifications sent",
                checked,
                total_new,
                total_sent,
            )
        else:
            logger.info("Poll checked %s alert(s), no new ads", checked)

    async def _check_alert(self, alert: Alert) -> tuple[int, int]:
        if await self.db.count_seen(alert.id) == 0:
            n = await seed_alert(self.db, self.kufar, alert, clear_first=False)
            logger.info("Auto-initialized alert %s with %s ads", alert.id, n)
            return 0, 0

        ads = await self.kufar.search(**alert.search_params)
        if not ads:
            logger.info("Alert %s: Kufar returned 0 ads for current filters", alert.id)
            return 0, 0

        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        new_ids = await self.db.filter_unseen(alert.id, ad_ids)
        if not new_ids:
            logger.info(
                "Alert %s: search returned %s ad(s), all already seen",
                alert.id,
                len(ads),
            )
            return 0, 0

        if await auto_heal_unseen(self.db, self.kufar, alert, ads, new_ids):
            return 0, 0

        new_id_set = set(new_ids)
        new_ads = [ad for ad in ads if int(ad.get("ad_id", 0)) in new_id_set]
        new_ads.sort(key=lambda ad: ad.get("list_time", ""), reverse=True)
        logger.info("Alert %s: %s new ad(s) to process", alert.id, len(new_ads))

        notified_ids: list[int] = []
        skipped_old_ids: list[int] = []
        notify_cooldown = await self._user_notify_cooldown(alert.user_id)
        for ad in new_ads:
            ad_id = int(ad["ad_id"])
            if not is_ad_after_alert_created(ad, alert.created_at):
                skipped_old_ids.append(ad_id)
                continue
            if await self._notify(alert, ad):
                notified_ids.append(ad_id)
            if notify_cooldown > 0:
                await asyncio.sleep(0.3)

        if skipped_old_ids:
            logger.info(
                "Alert %s: marked %s old ad(s) as seen (listed before subscription)",
                alert.id,
                len(skipped_old_ids),
            )

        seen_ids = notified_ids + skipped_old_ids
        if seen_ids:
            await self.db.mark_seen(alert.id, seen_ids)

        eligible = len(new_ads) - len(skipped_old_ids)
        failed = eligible - len(notified_ids)
        if failed > 0:
            logger.warning(
                "Alert %s: %s/%s eligible notifications failed, will retry next poll",
                alert.id,
                failed,
                eligible,
            )

        return len(new_ads), len(notified_ids)

    async def _should_poll_alert(self, alert: Alert) -> bool:
        db_user = await self.db.get_user(alert.user_id)
        interval = (
            db_user.settings.effective_poll_interval(self.default_interval)
            if db_user
            else self.default_interval
        )
        last = self._alert_last_poll.get(alert.id, 0.0)
        return time.monotonic() - last >= interval

    async def _user_notify_cooldown(self, user_id: int) -> int:
        db_user = await self.db.get_user(user_id)
        if not db_user:
            return 0
        return max(0, db_user.settings.notify_cooldown)

    async def _can_notify_user(self, user_id: int) -> bool:
        cooldown = await self._user_notify_cooldown(user_id)
        if cooldown <= 0:
            return True
        last = self._user_last_notify.get(user_id, 0.0)
        allowed = time.monotonic() - last >= cooldown
        if not allowed:
            logger.info("Notify cooldown active for user %s (%ss)", user_id, cooldown)
        return allowed

    async def _notify(self, alert: Alert, ad: dict) -> bool:
        if not await self._can_notify_user(alert.user_id):
            return False

        image_urls = get_image_urls(ad)
        db_user = await self.db.get_user(alert.user_id)
        display = db_user.settings.notification_display if db_user else None
        style = normalize_notification_style(
            db_user.settings.notification_style if db_user else None
        )
        layout = normalize_notification_layout(
            db_user.settings.notification_layout if db_user else None
        )
        photos_enabled = True
        if db_user and not db_user.settings.photos_enabled:
            image_urls = []
            photos_enabled = False
        preview_url = ad.get("ad_link") or f"https://www.kufar.by/item/{ad.get('ad_id')}"

        try:
            sent = await send_ad_notification(
                self.bot,
                alert.user_id,
                format_notification_message(
                    ad,
                    subscription_name=alert.name,
                    display=display,
                    style=style,
                    layout=layout,
                ),
                image_urls,
                self.kufar.download_image,
                preview_url=preview_url,
                photos_enabled=photos_enabled,
            )
            if sent is not None:
                await self.db.record_notification(
                    alert.user_id,
                    alert.id,
                    sent.chat.id,
                    sent.message_id,
                )
                self._user_last_notify[alert.user_id] = time.monotonic()
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
