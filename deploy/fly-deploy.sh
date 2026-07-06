#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v flyctl &>/dev/null && ! command -v fly &>/dev/null; then
  echo "Installing flyctl..."
  curl -L https://fly.io/install.sh | sh
  export PATH="$HOME/.fly/bin:$PATH"
fi

FLY="$(command -v flyctl || command -v fly)"

if [ ! -f .env ]; then
  echo "Create .env from .env.example and set BOT_TOKEN first."
  exit 1
fi

# shellcheck disable=SC1091
source .env

if [ -z "${BOT_TOKEN:-}" ] || [ "$BOT_TOKEN" = "your_telegram_bot_token" ]; then
  echo "Set BOT_TOKEN in .env"
  exit 1
fi

echo "==> Logging in to Fly.io (browser may open)..."
$FLY auth login

if ! $FLY apps list 2>/dev/null | grep -q "kufar-alerts"; then
  echo "==> Creating Fly app..."
  $FLY launch --no-deploy --copy-config --name kufar-alerts --region waw --yes
fi

if ! $FLY volumes list -a kufar-alerts 2>/dev/null | grep -q "kufar_data"; then
  echo "==> Creating persistent volume..."
  $FLY volumes create kufar_data --region waw --size 1 -a kufar-alerts --yes
fi

echo "==> Setting secrets..."
$FLY secrets set BOT_TOKEN="$BOT_TOKEN" -a kufar-alerts

echo "==> Deploying..."
$FLY deploy -a kufar-alerts

echo ""
echo "Done! Bot is running 24/7 in the cloud."
echo "Logs: $FLY logs -a kufar-alerts"
echo "Status: $FLY status -a kufar-alerts"
