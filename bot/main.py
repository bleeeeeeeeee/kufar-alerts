from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_settings
from bot.database import Database
from bot.error_handling import ErrorHandlingMiddleware
from bot.handlers import admin, alerts, edit, notifications, pickers, settings as settings_handlers, start
from bot.instance_lock import single_instance_lock
from bot.kufar import KufarClient
from bot.middleware import AccessMiddleware, DedupMiddleware, InjectMiddleware
from bot.menu import setup_bot_menu
from bot.poller import AlertPoller
from bot.web import run_web_in_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def restore_from_neon(db: Database, database_url: str) -> bool:
    """
    Восстанавливает данные из Neon в SQLite при первом запуске.
    Возвращает True, если данные были восстановлены.
    """
    try:
        from bot.sync_to_neon import NeonSync
        
        logger.info("Checking Neon for backup data...")
        sync = NeonSync()
        await sync.connect()
        
        if not sync.neon_pool:
            logger.warning("Could not connect to Neon, skipping restore")
            return False
        
        # Проверяем, есть ли данные в Neon
        async with sync.neon_pool.acquire() as conn:
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            
            if users_count == 0:
                logger.info("No data in Neon, nothing to restore")
                await sync.close()
                return False
            
            logger.info(f"Found {users_count} users in Neon, restoring...")
            
            # Получаем все данные из Neon
            users = await conn.fetch("SELECT * FROM users")
            alerts = await conn.fetch("SELECT * FROM alerts")
            seen_ads = await conn.fetch("SELECT * FROM seen_ads")
            notifications = await conn.fetch(
                "SELECT * FROM notification_messages WHERE created_at > NOW() - INTERVAL '1 day'"
            )
            config = await conn.fetch("SELECT * FROM bot_config")
            
            # Сохраняем в SQLite
            sqlite_conn = db._sqlite_conn()
            
            # Очищаем SQLite
            sqlite_conn.execute("DELETE FROM users")
            sqlite_conn.execute("DELETE FROM alerts")
            sqlite_conn.execute("DELETE FROM seen_ads")
            sqlite_conn.execute("DELETE FROM notification_messages")
            sqlite_conn.execute("DELETE FROM bot_config")
            
            # Восстанавливаем пользователей
            for row in users:
                d = dict(row)
                sqlite_conn.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, last_name, 
                                       role, active, settings_json, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        d.get('user_id'),
                        d.get('username'),
                        d.get('first_name'),
                        d.get('last_name'),
                        d.get('role', 'user'),
                        d.get('active', 1),
                        d.get('settings_json', '{}'),
                        d.get('created_at'),
                        d.get('last_seen_at')
                    )
                )
            
            # Восстанавливаем алерты
            for row in alerts:
                d = dict(row)
                sqlite_conn.execute(
                    """
                    INSERT INTO alerts (id, user_id, name, query, params_json, active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        d.get('id'),
                        d.get('user_id'),
                        d.get('name'),
                        d.get('query', ''),
                        d.get('params_json', '{}'),
                        d.get('active', 1),
                        d.get('created_at')
                    )
                )
            
            # Восстанавливаем просмотренные объявления
            for row in seen_ads:
                d = dict(row)
                sqlite_conn.execute(
                    """
                    INSERT INTO seen_ads (alert_id, ad_id, seen_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        d.get('alert_id'),
                        d.get('ad_id'),
                        d.get('seen_at')
                    )
                )
            
            # Восстанавливаем уведомления
            for row in notifications:
                d = dict(row)
                sqlite_conn.execute(
                    """
                    INSERT INTO notification_messages (user_id, alert_id, chat_id, message_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        d.get('user_id'),
                        d.get('alert_id'),
                        d.get('chat_id'),
                        d.get('message_id'),
                        d.get('created_at')
                    )
                )
            
            # Восстанавливаем конфиг
            for row in config:
                d = dict(row)
                sqlite_conn.execute(
                    """
                    INSERT INTO bot_config (key, value)
                    VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (
                        d.get('key'),
                        d.get('value')
                    )
                )
            
            sqlite_conn.commit()
            logger.info(f"Restored from Neon: {len(users)} users, {len(alerts)} alerts, {len(seen_ads)} seen ads")
            
            await sync.close()
            return True
            
    except Exception as e:
        logger.warning(f"Could not restore from Neon: {e}")
        return False


async def main() -> None:
    # Запускаем веб-сервер для health check (Flask)
    run_web_in_thread()
    
    # Получаем настройки
    app_settings = get_settings()
    
    # --- ВЫБОР БАЗЫ ДАННЫХ: POSTGRESQL ИЛИ SQLITE ---
    if app_settings.database_url:
        # Используем PostgreSQL (Neon) - ТОЛЬКО ДЛЯ БЭКАПОВ
        logger.info("Using PostgreSQL database (Neon) for backup only")
        db = Database(dsn=app_settings.database_url)
        await db.init(admin_user_ids=app_settings.admin_user_ids)
        logger.info("PostgreSQL initialized (backup mode)")
    else:
        # Используем SQLite - ОСНОВНАЯ БД
        logger.info("Using SQLite database as primary database")
        # Убеждаемся, что папка существует
        Path(app_settings.database_path).parent.mkdir(parents=True, exist_ok=True)
        # Используем единый класс Database без dsn
        db = Database(db_path=app_settings.database_path)
        await db.init(admin_user_ids=app_settings.admin_user_ids)
        logger.info("SQLite initialized at %s", app_settings.database_path)
        
        # --- ВОССТАНОВЛЕНИЕ ДАННЫХ ИЗ NEON (ПРИ ПЕРВОМ ЗАПУСКЕ) ---
        # Проверяем, есть ли данные в SQLite
        users_count = await db.count_users()
        if users_count == 0 and app_settings.database_url:
            logger.info("SQLite is empty, attempting to restore from Neon...")
            restored = await restore_from_neon(db, app_settings.database_url)
            if restored:
                logger.info("Data restored from Neon successfully!")
            else:
                logger.info("No data to restore from Neon, starting fresh")
        elif users_count == 0:
            logger.info("No data in SQLite, starting fresh")
        else:
            logger.info(f"SQLite already has {users_count} users, skipping restore")

    # --- БЛОКИРОВКА ДЛЯ ПРЕДОТВРАЩЕНИЯ ДВОЙНОГО ЗАПУСКА ---
    lock_path = Path(app_settings.database_path).with_suffix(".lock")
    try:
        with single_instance_lock(lock_path):
            # Инициализация бота
            bot = Bot(
                token=app_settings.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher(storage=MemoryStorage())

            # Сессия для Kufar API
            async with aiohttp.ClientSession() as session:
                kufar = KufarClient(session, search_size=app_settings.search_size)
                try:
                    await kufar.load_category_tree()
                except Exception:
                    logger.exception("Failed to load category tree, continuing without it")

                # --- МИДЛВАРЫ ---
                dp.update.outer_middleware(ErrorHandlingMiddleware())
                dp.update.middleware(DedupMiddleware())
                dp.update.middleware(InjectMiddleware(db, kufar, app_settings))
                dp.update.middleware(AccessMiddleware(db, app_settings))

                # --- МЕНЮ БОТА ---
                await setup_bot_menu(bot)

                # --- ПОДКЛЮЧЕНИЕ РОУТЕРОВ ---
                dp.include_router(start.router)
                dp.include_router(settings_handlers.router)
                dp.include_router(notifications.router)
                dp.include_router(admin.router)
                dp.include_router(alerts.router)
                dp.include_router(edit.router)
                dp.include_router(pickers.router)

                # --- ПОЛЛЕР (ФОНОВАЯ ПРОВЕРКА ОБЪЯВЛЕНИЙ) ---
                poller = AlertPoller(
                    bot=bot,
                    db=db,
                    kufar=kufar,
                    interval=app_settings.poll_interval,
                )
                poller.start()

                # --- ЗАПУСК БОТА ---
                logger.info("Bot started successfully!")
                logger.info("Poll interval: %s seconds", app_settings.poll_interval)
                logger.info("Database: %s", "PostgreSQL" if app_settings.database_url else "SQLite")
                
                await bot.delete_webhook(drop_pending_updates=True)
                try:
                    await dp.start_polling(
                        bot,
                        allowed_updates=dp.resolve_used_update_types(),
                        drop_pending_updates=True,
                    )
                finally:
                    await poller.stop()
                    await bot.session.close()
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())