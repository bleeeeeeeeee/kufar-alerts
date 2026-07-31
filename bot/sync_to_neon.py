import asyncpg
import sqlite3
import asyncio
from datetime import datetime
from bot.config import settings

class NeonSync:
    def __init__(self):
        self.neon_pool = None
    
    async def connect(self):
        self.neon_pool = await asyncpg.create_pool(
            settings.DATABASE_URL,  # URL от Neon
            min_size=1,
            max_size=2  # Минимум соединений
        )
    
    async def sync_all(self):
        """Синхронизирует все данные из SQLite в Neon"""
        # 1. Подключиться к SQLite
        sqlite_conn = sqlite3.connect(settings.DATABASE_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        
        # 2. Получить все подписки и уведомления
        subscriptions = sqlite_conn.execute(
            "SELECT * FROM subscriptions"
        ).fetchall()
        
        notifications = sqlite_conn.execute(
            "SELECT * FROM notifications WHERE created_at > datetime('now', '-1 day')"
        ).fetchall()
        
        # 3. Записать в Neon
        async with self.neon_pool.acquire() as conn:
            # Очистить старые данные (или обновить)
            await conn.execute("TRUNCATE subscriptions, notifications")
            
            for sub in subscriptions:
                await conn.execute(
                    "INSERT INTO subscriptions VALUES ($1, $2, $3, ...)",
                    *sub
                )
            
            for notif in notifications:
                await conn.execute(
                    "INSERT INTO notifications VALUES ($1, $2, $3, ...)",
                    *notif
                )
        
        sqlite_conn.close()
        logger.info(f"Synced to Neon at {datetime.now()}")