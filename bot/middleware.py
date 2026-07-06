from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database import Database
from bot.kufar import KufarClient


class InjectMiddleware(BaseMiddleware):
    def __init__(self, db: Database, kufar: KufarClient) -> None:
        self.db = db
        self.kufar = kufar

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["kufar"] = self.kufar
        return await handler(event, data)
