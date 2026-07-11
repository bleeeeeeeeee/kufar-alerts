# run_bot.py
import sys
import os
import logging
from bot.main import main

# Настройка логирования
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # Убеждаемся, что переменные окружения загружены
    from dotenv import load_dotenv
    load_dotenv()
    
    # Запуск бота
    main()