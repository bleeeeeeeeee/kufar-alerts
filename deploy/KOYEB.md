# Деплой на Koyeb (24/7, без карты)

[Koyeb](https://www.koyeb.com) — бесплатный always-on хостинг, регистрация только через email/GitHub, **карта не нужна**.

## Вариант 1: Одна кнопка (2 минуты)

1. Нажмите кнопку в README репозитория: **Deploy to Koyeb**
2. Войдите через GitHub
3. В разделе **Environment variables** добавьте:
   - `BOT_TOKEN` = ваш токен от @BotFather
4. Нажмите **Deploy**

Готово — бот работает 24/7, пока сервис запущен на Koyeb.

## Вариант 2: Через дашборд

1. [app.koyeb.com](https://app.koyeb.com) → Create Web Service
2. **GitHub** → репозиторий `bleeeeeeeeee/kufar-alerts`
3. **Builder**: Dockerfile
4. **Instance**: Free (Nano)
5. **Service type**: Worker (не Web — бот не слушает HTTP)
6. **Environment variables**:
   ```
   BOT_TOKEN=ваш_токен
   POLL_INTERVAL=45
   SEARCH_SIZE=30
   DATABASE_PATH=/tmp/kufar_alerts.db
   ```
7. Deploy

## Логи и управление

- Koyeb Dashboard → ваш сервис → **Logs**
- Перезапуск: **Redeploy**
- Автодеплой при push в `main` включается по умолчанию

## Лимиты free tier

- 1 nano-сервис (512 MB RAM)
- Без sleep mode — работает постоянно
- SQLite хранится в контейнере (при redeploy подписки сбросятся, но бот снова заработает)
