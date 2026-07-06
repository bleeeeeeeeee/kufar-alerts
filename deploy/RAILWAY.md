# Деплой на Railway (24/7, без карты)

[Railway](https://railway.app) — $5 trial-кредитов при регистрации, **карта не нужна** (вход через GitHub).

## Шаги

1. Откройте [railway.app/new](https://railway.app/new)
2. **Deploy from GitHub repo** → выберите `kufar-alerts`
3. Railway определит Dockerfile автоматически
4. **Variables** → добавьте:
   ```
   BOT_TOKEN=ваш_токен
   POLL_INTERVAL=45
   SEARCH_SIZE=30
   DATABASE_PATH=/app/data/kufar_alerts.db
   ```
5. **Settings** → включите **Restart Policy: Always**
6. Deploy

## Через CLI

```bash
npm install -g @railway/cli
railway login
cd kufar-alerts
railway init
railway variables set BOT_TOKEN=ваш_токен
railway up
```

## Стоимость

Малый Python-бот ~$1–3/мес. Trial $5 хватает на несколько месяцев.

Логи: Railway Dashboard → Deployments → View Logs
