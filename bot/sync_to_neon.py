from __future__ import annotations

import asyncpg
import logging
import ssl
import sqlite3
from datetime import datetime
from typing import Any

from bot.config import get_settings

logger = logging.getLogger(__name__)


class NeonSync:
    def __init__(self):
        self.neon_pool = None
        self._settings = None
    
    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings
    
    async def connect(self):
        """Подключение к Neon"""
        if not self.settings.database_url:
            logger.warning("DATABASE_URL not set, skipping Neon sync")
            return
        
        try:
            # SSL-контекст как в database.py
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            self.neon_pool = await asyncpg.create_pool(
                self.settings.database_url,
                min_size=1,
                max_size=2,
                timeout=60.0,
                ssl=ssl_context,
            )
            logger.info("Connected to Neon successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Neon: {e}")
            raise
    
    async def sync_all(self, data: dict[str, Any] | None = None):
        """
        Синхронизирует все данные из SQLite в Neon.
        
        Args:
            data: Словарь с данными из SQLite (из get_all_data())
                  Если None, пытается получить данные самостоятельно
        """
        if not self.neon_pool:
            await self.connect()
        
        if not self.neon_pool:
            logger.error("No connection to Neon, sync aborted")
            return
        
        try:
            # Если данные не переданы, получаем их из SQLite
            if data is None:
                sqlite_conn = sqlite3.connect(self.settings.database_path)
                sqlite_conn.row_factory = sqlite3.Row
                
                data = {
                    'users': sqlite_conn.execute("SELECT * FROM users").fetchall(),
                    'alerts': sqlite_conn.execute("SELECT * FROM alerts").fetchall(),
                    'seen_ads': sqlite_conn.execute("SELECT * FROM seen_ads").fetchall(),
                    'notification_messages': sqlite_conn.execute(
                        "SELECT * FROM notification_messages WHERE created_at > datetime('now', '-1 day')"
                    ).fetchall(),
                    'bot_config': sqlite_conn.execute("SELECT * FROM bot_config").fetchall(),
                }
                sqlite_conn.close()
            
            async with self.neon_pool.acquire() as conn:
                # Очистка старых данных
                await conn.execute("""
                    TRUNCATE TABLE users, alerts, seen_ads, 
                    notification_messages, bot_config CASCADE
                """)
                logger.info("Truncated all tables in Neon")
                
                # 1. Пользователи
                users = data.get('users', [])
                if users:
                    for row in users:
                        d = dict(row)
                        await conn.execute(
                            """
                            INSERT INTO users (
                                user_id, username, first_name, last_name, 
                                role, active, settings_json, created_at, last_seen_at
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                            """,
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
                    logger.info(f"Synced {len(users)} users")
                
                # 2. Алерты (подписки)
                alerts = data.get('alerts', [])
                if alerts:
                    for row in alerts:
                        d = dict(row)
                        await conn.execute(
                            """
                            INSERT INTO alerts (
                                id, user_id, name, query, params_json, active, created_at
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            d.get('id'),
                            d.get('user_id'),
                            d.get('name'),
                            d.get('query', ''),
                            d.get('params_json', '{}'),
                            d.get('active', 1),
                            d.get('created_at')
                        )
                    logger.info(f"Synced {len(alerts)} alerts")
                
                # 3. Просмотренные объявления
                seen_ads = data.get('seen_ads', [])
                if seen_ads:
                    for row in seen_ads:
                        d = dict(row)
                        await conn.execute(
                            """
                            INSERT INTO seen_ads (alert_id, ad_id, seen_at)
                            VALUES ($1, $2, $3)
                            """,
                            d.get('alert_id'),
                            d.get('ad_id'),
                            d.get('seen_at')
                        )
                    logger.info(f"Synced {len(seen_ads)} seen ads")
                
                # 4. Уведомления
                notifications = data.get('notification_messages', [])
                if notifications:
                    for row in notifications:
                        d = dict(row)
                        await conn.execute(
                            """
                            INSERT INTO notification_messages (
                                user_id, alert_id, chat_id, message_id, created_at
                            ) VALUES ($1, $2, $3, $4, $5)
                            """,
                            d.get('user_id'),
                            d.get('alert_id'),
                            d.get('chat_id'),
                            d.get('message_id'),
                            d.get('created_at')
                        )
                    logger.info(f"Synced {len(notifications)} notifications")
                
                # 5. Конфиг
                config = data.get('bot_config', [])
                if config:
                    for row in config:
                        d = dict(row)
                        await conn.execute(
                            """
                            INSERT INTO bot_config (key, value)
                            VALUES ($1, $2)
                            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                            """,
                            d.get('key'),
                            d.get('value')
                        )
                    logger.info(f"Synced {len(config)} config entries")
                
                logger.info(f"Sync to Neon completed at {datetime.now()}")
                
        except Exception as e:
            logger.error(f"Sync to Neon failed: {e}")
            raise
    
    async def close(self):
        """Закрытие подключения к Neon"""
        if self.neon_pool:
            await self.neon_pool.close()
            logger.info("Neon connection closed")