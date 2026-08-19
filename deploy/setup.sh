#!/bin/bash
set -e

APP_DIR="/home/ubuntu/telebot-1"
USER_NAME="ubuntu"

echo "==> Updating system..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git nginx

echo "==> Cloning repo if needed..."
if [ ! -d "$APP_DIR" ]; then
    sudo git clone https://github.com/abhisheek2006/telebot-1.git "$APP_DIR"
fi
sudo chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR"

echo "==> Installing Python deps..."
cd "$APP_DIR"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "==> Setting up logs..."
mkdir -p "$APP_DIR/logs"
sudo chown -R "$USER_NAME":"$USER_NAME" "$APP_DIR/logs"

echo "==> Installing systemd services..."
sudo cp deploy/telebot.service /etc/systemd/system/telebot.service
sudo cp deploy/webapp.service /etc/systemd/system/webapp.service
sudo systemctl daemon-reload
sudo systemctl enable telebot webapp

echo ""
echo "==> DONE! Next steps:"
echo "   1. Create .env:  nano $APP_DIR/.env   (BOT_TOKEN, ADMIN_ID, API_ID, API_HASH, MONGO_URI, WEB_SECRET_KEY, WEB_PASSWORD)"
echo "   2. Start the bot:  sudo systemctl start telebot"
echo "   3. Check status:   sudo systemctl status telebot"
echo "   4. View logs:      tail -f $APP_DIR/logs/bot.log"