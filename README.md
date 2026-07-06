# Kufar Alerts

Telegram-бот для оповещений о новых объявлениях на [kufar.by](https://www.kufar.by) по вашим критериям поиска.

## Возможности

- Подписка по ссылке с Kufar (все фильтры из URL)
- Ручная настройка: запрос, категория, регион, цена
- Уведомления с фото, ценой и ссылкой
- Несколько подписок на пользователя
- Пауза / возобновление / удаление
- Работа 24/7 в Docker с автоперезапуском

## Быстрый старт

### 1. Создайте бота в Telegram

1. Откройте [@BotFather](https://t.me/BotFather)
2. `/newbot` → получите токен

### 2. Настройте окружение

```bash
cp .env.example .env
# Отредактируйте .env — вставьте BOT_TOKEN
```

### 3. Запуск через Docker (рекомендуется)

```bash
docker compose up -d --build
docker compose logs -f
```

### 4. Локальный запуск (без Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/new` | Создать подписку |
| `/list` | Список подписок |
| `/pause ID` | Пауза |
| `/resume ID` | Возобновить |
| `/delete ID` | Удалить |
| `/help` | Справка |

## Как создать подписку по ссылке

1. Откройте [kufar.by](https://www.kufar.by) и настройте поиск (категория, регион, цена, ключевые слова)
2. Скопируйте URL из адресной строки
3. В боте: `/new` → «Вставить ссылку» → вставьте URL

При создании подписки бот запоминает текущие объявления и уведомляет только о **новых**.

## Регионы

| ID | Регион |
|----|--------|
| 1 | Брестская область |
| 2 | Витебская область |
| 3 | Гомельская область |
| 4 | Гродненская область |
| 5 | Могилёвская область |
| 6 | Минская область |
| 7 | Минск |

## Настройки (.env)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `BOT_TOKEN` | — | Токен Telegram-бота |
| `POLL_INTERVAL` | 45 | Интервал проверки (сек) |
| `SEARCH_SIZE` | 30 | Сколько объявлений проверять за раз |
| `DATABASE_PATH` | data/kufar_alerts.db | Путь к SQLite |

## Деплой 24/7 в облако (рекомендуется)

Локальный Docker работает только пока включён ваш ПК. Для круглосуточной работы — деплой в облако.

### Fly.io (бесплатный тариф ~256 MB, Варшава)

1. Зарегистрируйтесь на [fly.io](https://fly.io) (нужна карта для верификации, списаний на free tier обычно нет)
2. Заполните `.env` с `BOT_TOKEN`
3. Запустите:

```bash
chmod +x deploy/fly-deploy.sh
./deploy/fly-deploy.sh
```

Скрипт сам установит `flyctl`, создаст приложение, volume для SQLite и задеплоит бота.

Полезные команды:
```bash
fly logs -a kufar-alerts      # логи
fly status -a kufar-alerts    # статус
fly ssh console -a kufar-alerts  # консоль на сервере
```

### Render.com (альтернатива)

1. Запушьте репо на GitHub
2. [render.com](https://render.com) → New → Blueprint → подключите репо
3. Укажите `BOT_TOKEN` в переменных окружения
4. Render поднимет worker с диском для базы

### Локальный Docker (только для тестов)

```bash
docker compose up -d --build
```

Требует запущенный Docker Desktop и включённый ПК.

## Деплой на VPS

```bash
git clone <repo> kufar-alerts && cd kufar-alerts
cp .env.example .env && nano .env
docker compose up -d --build
```

Бот перезапустится автоматически при падении (`restart: unless-stopped`).

## Структура

```
bot/
  main.py       — точка входа
  config.py     — настройки
  database.py   — SQLite
  kufar.py      — API Kufar
  poller.py     — фоновая проверка
  handlers/     — команды Telegram
```
