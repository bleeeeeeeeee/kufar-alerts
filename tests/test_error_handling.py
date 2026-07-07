import asyncio
from types import SimpleNamespace

from bot.error_handling import ErrorHandlingMiddleware, safe_answer


def test_error_middleware_catches_handler_exception():
    async def run_test() -> None:
        middleware = ErrorHandlingMiddleware()

        async def handler(event, data):
            raise RuntimeError("boom")

        result = await middleware(handler, object(), {})
        assert result is None

    asyncio.run(run_test())


def test_safe_answer_returns_false_when_callback_fails():
    async def run_test() -> None:
        callback = SimpleNamespace(
            answer=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        result = await safe_answer(callback)
        assert result is False

    asyncio.run(run_test())
