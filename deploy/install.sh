#!/usr/bin/env bash
# Installation sur un serveur Ubuntu/Debian. À lancer en root depuis le dossier du projet :
#   sudo bash deploy/install.sh
set -euo pipefail

apt-get update -q
apt-get install -y -q python3 python3-venv rsync

id tradebot &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin tradebot
mkdir -p /opt/tradebot
rsync -a --exclude .git --exclude .venv --exclude 'state*.json' ./ /opt/tradebot/
[ -f /opt/tradebot/.env ] || cp .env.example /opt/tradebot/.env
grep -q '^TRADEBOT_ARGS=' /opt/tradebot/.env || echo 'TRADEBOT_ARGS=--capital 1000' >> /opt/tradebot/.env

python3 -m venv /opt/tradebot/.venv
/opt/tradebot/.venv/bin/pip install -q -r /opt/tradebot/requirements.txt
chown -R tradebot:tradebot /opt/tradebot
chmod 600 /opt/tradebot/.env   # clés API lisibles uniquement par le bot

cp deploy/tradebot.service /etc/systemd/system/tradebot.service
systemctl daemon-reload
systemctl enable tradebot

echo
echo "Installé. Étapes suivantes :"
echo "  1. nano /opt/tradebot/.env        (clés Kraken, Telegram, et TRADEBOT_ARGS)"
echo "  2. systemctl restart tradebot"
echo "  3. journalctl -u tradebot -f      (voir ce que fait le bot)"
