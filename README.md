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
2. Get your **API_ID** and **API_HASH** from [my.telegram.org](https://my.telegram.org) → API Development Tools
3. Ensure you have a MongoDB Atlas cluster (connection URI below uses the sandbox)
4. Add environment variables to `.env`:
   - `BOT_TOKEN=your_bot_token`
   - `ADMIN_ID=your_telegram_user_id`
   - `API_ID=12345` (from my.telegram.org)
   - `API_HASH=your_api_hash` (from my.telegram.org)
   - `MONGO_URI=mongodb+srv://user:pass@cluster/...&retryWrites=true&w=majority`
5. `pip install -r requirements.txt`
6. `python bot.py`

## Deploy

Push to GitHub and connect to Railway for automatic deployment. Set all env
vars (`BOT_TOKEN`, `ADMIN_ID`, `API_ID`, `API_HASH`, `MONGO_URI`) in your
Railway dashboard. The `Procfile` runs:
```
worker: python3 bot.py
```

## Usage

Send `/start` to begin. Approved users get an inline keyboard with **Lookup**, **Balance**, and **Help** buttons.
Admins also see **Add Credit** (DANGER), **List Users** (PRIMARY), and **Stats** (DEFAULT) buttons.

### Admin Add Credit (to any user)

Two ways to add credits:

1. **`/credit`** — admin enters user_id, then amount
2. **List Users → click user → 💳 Add Credit (DANGER)** — skips user_id step, goes straight to amount

### Credit System
- New users get **5 welcome credits** (configurable via `DEFAULT_NEW_USER_CREDITS`)
- Each lookup costs **1 credit** (configurable via `CREDIT_PER_LOOKUP`)
- Insufficient credits show a **💰 Buy Credit** (DANGER) button
