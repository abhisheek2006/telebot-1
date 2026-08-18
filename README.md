# telebot-1 — Credit-Lookup Bot

A Telegram bot built with **Pyrogram (PyroTGFork)** and **MongoDB** that provides phone number lookup via the Supabase API, protected by a credit system and user-approval workflow. Features a referral program and works in both private chats and groups.

## Features

- **User approval system** — new users must be approved by the admin
- **Credit system** — each lookup deducts credits; new users get 5 welcome credits
- **Referral program** — invite friends for bonus credits:
  - Every user gets a unique referral code and link
  - 3 extra credits for every friend who joins via your referral link
  - 10 bonus credits for every 5 successful referrals
  - Works via deep-link: `https://t.me/{bot_username}?start={ref_code}`
- **Group support** — bot works in Telegram groups for `/start`, `/help`, `/balance`, `/referral`
  - Phone number lookups are restricted to private chat for privacy
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
    - `REFERRAL_WELCOME_CREDITS=3` — bonus credits for referred users (optional)
    - `REFERRAL_THRESHOLD=5` — referrals needed for bonus (optional)
    - `REFERRAL_BONUS_CREDITS=10` — bonus credits per threshold reached (optional)
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

Send `/start` to begin. Approved users get an inline keyboard with **Lookup**, **Balance**, **Referral**, and **Help** buttons.
Admins also see **Add Credit** (DANGER), **List Users** (PRIMARY), and **Stats** (DEFAULT) buttons.

### Referral Program

- Use `/referral` or click the 🤝 **Referral** button to view your referral link
- Share your link: `https://t.me/{bot_username}?start={your_ref_code}`
- Every friend who joins via your link gets 5 welcome credits + 3 referral bonus
- You get 10 bonus credits for every 5 successful referrals

### In Groups

The bot works in groups for basic commands:
- `/start` — welcome message + link to private chat
- `/help` — help info
- `/balance` — check your credit balance
- `/referral` — view your referral link and stats

Phone number lookups are only available in private chat for privacy.

### Credit System
- New users get **5 welcome credits** (configurable via `DEFAULT_NEW_USER_CREDITS`)
- Each lookup costs **1 credit** (configurable via `CREDIT_PER_LOOKUP`)
- Insufficient credits show a **💰 Buy Credit** (DANGER) button
