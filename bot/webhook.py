from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from flask import Flask, abort, request

from bot.config import get_settings
from bot.database import Database
from bot.error_handling import ErrorHandlingMiddleware
from bot.handlers import admin, alerts, edit, notifications, pickers, settings as settings_handlers, start
from bot.kufar import KufarClient
from bot.menu import setup_bot_menu
from bot.middleware import AccessMiddleware, DedupMiddleware, InjectMiddleware
from bot.poller import AlertPoller

logger = logging.getLogger(__name__)

app = Flask(__name__)
_app_ready = threading.Event()
_loop: asyncio.AbstractEventLoop | None = None
_bot: Bot | None = None
_dp: Dispatcher | None = None
_db: Database | None = None
_poller: AlertPoller | None = None
_settings = get_settings()


def _make_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.outer_middleware(ErrorHandlingMiddleware())
    dispatcher.update.middleware(DedupMiddleware())
    dispatcher.update.middleware(InjectMiddleware(_db, _kufar, _settings))
    dispatcher.update.middleware(AccessMiddleware(_db, _settings))

    dispatcher.include_router(start.router)
    dispatcher.include_router(settings_handlers.router)
    dispatcher.include_router(notifications.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(alerts.router)
    dispatcher.include_router(edit.router)
    dispatcher.include_router(pickers.router)
    return dispatcher


async def _initialize_app() -> None:
    global _bot, _dp, _db, _poller, _kufar

    _db = Database(_settings.database_path)
    await _db.init(admin_user_ids=_settings.admin_user_ids)

    _bot = Bot(
        token=_settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    _kufar = KufarClient(_bot.session, search_size=_settings.search_size)
    try:
        await _kufar.load_category_tree()
    except Exception:
        logger.exception("Failed to load category tree, continuing without it")

    _dp = _make_dispatcher()
    await setup_bot_menu(_bot)

    if _settings.webhook_enabled and _settings.webhook_url:
        webhook_kwargs: dict[str, Any] = {
            "url": _settings.webhook_url,
            "drop_pending_updates": True,
            "allowed_updates": _dp.resolve_used_update_types(),
        }
        if _settings.webhook_secret_token:
            webhook_kwargs["secret_token"] = _settings.webhook_secret_token

        try:
            await _bot.set_webhook(**webhook_kwargs)
            logger.info("Webhook set to %s", _settings.webhook_url)
        except Exception:
            logger.exception("Failed to set Telegram webhook")
            raise
    else:
        logger.warning("Webhook is not enabled or WEBHOOK_URL is not configured")

    _poller = AlertPoller(
        bot=_bot,
        db=_db,
        kufar=_kufar,
        interval=_settings.poll_interval,
    )
    _poller.start()
    _app_ready.set()


def _start_background_loop() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_initialize_app())
        _loop.run_forever()
    except Exception:
        logger.exception("Failed to start webhook loop")


@app.route("/healthz", methods=["GET"])
def health_check() -> str:
    return "ok"


@app.route(_settings.webhook_path, methods=["POST"])
def telegram_webhook() -> str:
    if _settings.webhook_secret_token:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != _settings.webhook_secret_token:
            logger.warning("Invalid webhook secret token")
            abort(403)

    if not _app_ready.wait(timeout=15):
        logger.warning("Webhook request received before app ready")
        abort(503)

    data = request.get_json(silent=True)
    if not data:
        logger.warning("Empty webhook payload")
        abort(400)

    try:
        update = Update(**data)
    except Exception:
        logger.exception("Failed to parse webhook update")
        abort(400)

    future = asyncio.run_coroutine_threadsafe(_dp.feed_update(_bot, update), _loop)
    try:
        future.result(timeout=15)
    except Exception:
        logger.exception("Failed to dispatch webhook update")
        abort(500)

    return "", 200


def _ensure_background_started() -> None:
    if not _app_ready.is_set():
        thread = threading.Thread(target=_start_background_loop, daemon=True, name="bot-webhook-loop")
        thread.start()


_ensure_background_started()
