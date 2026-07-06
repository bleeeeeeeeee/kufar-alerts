# Kufar Alerts

Telegram-бот для оповещений о новых объявлениях на [kufar.by](https://www.kufar.by) по вашим критериям поиска.

## Возможности

- Подписка по ссылке с Kufar (все фильтры из URL)
- Ручная настройка: запрос, категория, регион, цена
- Уведомления с фото, ценой и ссылкой
- Несколько подписок на пользователя
- Пауза / возобновление / удаление
- Работа 24/7 в облаке (Koyeb / Railway)

## Быстрый старт

### 1. Создайте бота в Telegram

1. Откройте [@BotFather](https://t.me/BotFather)
2. `/newbot` → получите токен

### 2. Настройте окружение

```bash
cp .env.example .env
# Отредактируйте .env — вставьте BOT_TOKEN
```

## Деплой 24/7 в облако (рекомендуется)

Локальный Docker работает только пока включён ПК. Для круглосуточной работы — **Koyeb** или **Railway** (оба без привязки карты).

### Koyeb — лучший вариант (бесплатно, без карты)

[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=git&builder=dockerfile&repository=github.com/bleeeeeeeeee/kufar-alerts&branch=main&name=kufar-alerts&service_type=worker)

1. Нажмите кнопку выше (или откройте [app.koyeb.com](https://app.koyeb.com))
2. Войдите через GitHub
3. Добавьте переменную `BOT_TOKEN` = токен от @BotFather
4. Deploy

Подробнее: [deploy/KOYEB.md](deploy/KOYEB.md)

### Railway — альтернатива (trial $5, без карты)

1. [railway.app/new](https://railway.app/new) → Deploy from GitHub → `kufar-alerts`
2. Variables → `BOT_TOKEN`
3. Restart Policy → **Always**

Подробнее: [deploy/RAILWAY.md](deploy/RAILWAY.md)

### Локально (только для разработки)

```bash
cp .env.example .env   # вставьте BOT_TOKEN
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

Или Docker (нужен запущенный Docker Desktop):

```bash
docker compose up -d --build
```

## Деплой на VPS

| Команда | Описание |
|---------|----------|
| `/new` | Создать подписку |
| `/list` | Список подписок |
| `/edit` | Редактировать подписку |
| `/edit ID` | Редактировать по ID |
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

## Команды бота

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
