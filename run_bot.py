# run_bot.py
import asyncio
import logging
from dotenv import load_dotenv
from bot.main import main

# Настройка логирования
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # Убеждаемся, что переменные окружения загружены
    load_dotenv()

    # Запуск бота
    asyncio.run(main())