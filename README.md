# telebot-1 — Credit-Lookup Bot

A Telegram bot built with **Pyrogram (PyroTGFork)** and **MongoDB** that provides phone number lookup via the Supabase API, protected by a credit system and user-approval workflow.

## Features

- **User approval system** — new users must be approved by the admin
- **Credit system** — each lookup deducts credits; new users get welcome credits
- **MongoDB storage** — all users, credits, and stats stored in MongoDB Atlas
- **Inline keyboard interface** — every command is a styled inline button:
  - 🔴 `DANGER` (red) — admin actions & critical operations
  - 🟢 `SUCCESS` (green) — balance/approval actions
  - 🔵 `PRIMARY` (blue) — primary bot actions
  - ⚪ `DEFAULT` (transparent) — help/navigational buttons
- **Admin panel** — approve/deny users, add credits, view stats, list all users

## Setup

1. Get a bot token from [@BotFather](https://t.me/BotFather)
2. Ensure you have a MongoDB Atlas cluster (connection URI below uses the sandbox)
3. Add environment variables to `.env`:
   - `BOT_TOKEN=your_bot_token`
   - `ADMIN_ID=your_telegram_user_id`
   - `MONGO_URI=mongodb+srv://user:pass@cluster/...&retryWrites=true&w=majority`
4. `pip install -r requirements.txt`
5. `python bot.py`

## Deploy

Push to GitHub and connect to Railway for automatic deployment. The `Procfile` runs:
```
worker: python3 bot.py
```

## Usage

Send `/start` to begin. Approved users get an inline keyboard with **Lookup**, **Balance**, and **Help** buttons.
Admins also see **Add Credit**, **List Users**, and **Stats** buttons.
