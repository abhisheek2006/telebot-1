import os
import logging
import random
import re
import string
import requests
from datetime import datetime, timezone
from pyrogram import Client, enums, filters, types
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://mondalabhisheek8_db_user:abhisheek@cluster0.m4wgvdi.mongodb.net/"
    "?retryWrites=true&w=majority",
)
API_URL = "https://nmdllpezcocquamhgpmb.supabase.co/functions/v1/lookup"

if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable is not set!")
    exit(1)
if not ADMIN_ID:
    logging.warning("ADMIN_ID environment variable is not set!")

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

logging.info("Connecting to MongoDB...")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.telegram_bot
users_col = db.users
stats_col = db.stats
codes_col = db.redeem_codes
logging.info("MongoDB connected: %s", db.name)

CREDIT_PER_LOOKUP = int(os.environ.get("CREDIT_PER_LOOKUP", "1"))
DEFAULT_NEW_USER_CREDITS = int(os.environ.get("DEFAULT_NEW_USER_CREDITS", "5"))
REFERRAL_WELCOME_CREDITS = int(os.environ.get("REFERRAL_WELCOME_CREDITS", "3"))
REFERRAL_THRESHOLD = int(os.environ.get("REFERRAL_THRESHOLD", "5"))
REFERRAL_BONUS_CREDITS = int(os.environ.get("REFERRAL_BONUS_CREDITS", "10"))
DEFAULT_REDEEM_CREDITS = int(os.environ.get("DEFAULT_REDEEM_CREDITS", "5"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
ADMIN_CONTACT = os.environ.get("ADMIN_CONTACT", f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "the admin")
ADMIN_NAME = os.environ.get("ADMIN_NAME", "Admin")

pending_input = {}

_client_kwargs = {"bot_token": BOT_TOKEN}
if API_ID and API_HASH:
    _client_kwargs["api_id"] = int(API_ID)
    _client_kwargs["api_hash"] = API_HASH
    logging.info("Using API_ID/API_HASH from environment for MTProto auth.")
else:
    # Fallback: PyroTGFork always needs api_id/api_hash for session creation.
    # Get your own pair from https://my.telegram.org for production.
    _client_kwargs["api_id"] = 18802415
    _client_kwargs["api_hash"] = "a8993f96404fd9a67de867586b3ddc92"
    logging.warning(
        "API_ID/API_HASH not set — using fallback demo credentials. "
        "Set your own pair from https://my.telegram.org in production!"
    )

app = Client("creditbot", parse_mode=enums.ParseMode.HTML, **_client_kwargs)


# ─────────────────────────── MongoDB helpers ────────────────────────────
def get_or_create_user(user_id: int, first_name: str = "User", username: str = None):
    uid_str = str(user_id)
    doc = users_col.find_one({"user_id_str": uid_str})
    if not doc:
        ref_code = generate_referral_code()
        while users_col.find_one({"referral_code": ref_code}):
            ref_code = generate_referral_code()
        doc = {
            "user_id": user_id,
            "user_id_str": uid_str,
            "first_name": first_name,
            "username": username or "",
            "is_approved": bool(ADMIN_ID and uid_str == str(ADMIN_ID)),
            "credits": DEFAULT_NEW_USER_CREDITS,
            "referral_code": ref_code,
            "referrals_count": 0,
            "referred_by": None,
            "total_lookups": 0,
            "created_at": datetime.now(timezone.utc),
        }
        users_col.insert_one(doc)
        logging.info("New user created: %s (%s) — ref code: %s", uid_str, first_name, ref_code)
    else:
        update_data = {"$set": {"first_name": first_name}}
        if username:
            update_data["$set"]["username"] = username
        if not doc.get("referral_code"):
            new_code = generate_referral_code()
            while users_col.find_one({"referral_code": new_code}):
                new_code = generate_referral_code()
            update_data["$set"]["referral_code"] = new_code
        users_col.update_one({"user_id_str": uid_str}, update_data)
        doc["referral_code"] = update_data["$set"].get("referral_code", doc.get("referral_code"))
    return doc


def is_approved(user_id: int) -> bool:
    uid_str = str(user_id)
    doc = users_col.find_one({"user_id_str": uid_str})
    if doc and doc.get("is_approved"):
        return True
    if ADMIN_ID and uid_str == str(ADMIN_ID):
        approve_user(user_id)
        return True
    return False


def approve_user(user_id: int):
    users_col.update_one(
        {"user_id_str": str(user_id)},
        {"$set": {"is_approved": True}},
    )


def revoke_user(user_id: int):
    users_col.update_one(
        {"user_id_str": str(user_id)},
        {"$set": {"is_approved": False}},
    )


def add_credits(user_id: int, amount: int):
    users_col.update_one(
        {"user_id_str": str(user_id)},
        {"$inc": {"credits": amount}},
    )


def deduct_credit(user_id: int):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"credits": -CREDIT_PER_LOOKUP, "total_lookups": 1}},
    )


def get_user(user_id: int):
    return users_col.find_one({"user_id_str": str(user_id)})


def bump_stat(key: str, amount: int = 1):
    stats_col.update_one({'_id': 'bot'}, {'$inc': {key: amount}}, upsert=True)


def safe_edit_text(message: types.Message, text: str, **kwargs):
    try:
        message.edit_text(text, **kwargs)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logging.warning("Edit failed: %s", e)
        try:
            message.reply_text(text, **kwargs)
        except Exception as e2:
            logging.warning("Reply also failed: %s", e2)


def generate_referral_code(length: int = 8) -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


def register_referral(user_id: int, referral_code: str) -> bool:
    if not referral_code:
        return False
    uid_str = str(user_id)
    referrer = users_col.find_one({"referral_code": referral_code})
    if not referrer:
        return False
    if str(referrer["user_id"]) == uid_str:
        return False
    existing = users_col.find_one({"user_id_str": uid_str, "referred_by": {"$ne": None}})
    if existing:
        return False
    users_col.update_one(
        {"user_id_str": str(referrer["user_id"])},
        {"$inc": {"referrals_count": 1}},
    )
    users_col.update_one(
        {"user_id_str": uid_str},
        {"$set": {"referred_by": str(referrer["user_id"])},
         "$inc": {"credits": REFERRAL_WELCOME_CREDITS}},
    )
    bump_stat("referrals")
    updated_referrer = users_col.find_one({"user_id_str": str(referrer["user_id"])})
    if updated_referrer and updated_referrer.get("referrals_count", 0) % REFERRAL_THRESHOLD == 0:
        add_credits(referrer["user_id"], REFERRAL_BONUS_CREDITS)
        bump_stat("referral_bonuses")
        try:
            bot_me = app.get_me()
            bot_username = bot_me.username
        except Exception:
            bot_username = "yourbot"
        ref_link = f"https://t.me/{bot_username}?start={referral_code}"
        try:
            app.send_message(
                referrer["user_id"],
                f"🎉 <b>Referral Bonus!</b>\n\n"
                f"You reached {updated_referrer['referrals_count']} referrals!\n"
                f"🎁 You received <b>{REFERRAL_BONUS_CREDITS}</b> bonus credits.\n\n"
                f"Your referral link:\n{ref_link}",
            )
        except Exception:
            pass
    return True


def get_bot_username() -> str:
    try:
        bot_me = app.get_me()
        return bot_me.username
    except Exception:
        return os.environ.get("BOT_USERNAME", "yourbot")


def generate_redeem_code(length: int = 10) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not codes_col.find_one({"code": code}):
            return code


def create_redeem_codes(amount_credits: int, count: int = 1, created_by: int = None, custom_code: str = None) -> list:
    created = []
    codes_to_insert = []
    for _ in range(count):
        if custom_code:
            if codes_col.find_one({"code": custom_code}):
                return []
            code = custom_code
        else:
            code = generate_redeem_code()
        doc = {
            "code": code,
            "credits": amount_credits,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
            "used_by": None,
            "used_at": None,
        }
        codes_to_insert.append(doc)
        created.append(code)
    if codes_to_insert:
        codes_col.insert_many(codes_to_insert)
    return created


def redeem_code(user_id: int, code: str) -> dict:
    code = code.strip().upper()
    doc = codes_col.find_one({"code": code})
    if not doc:
        return {"ok": False, "msg": "❌ Invalid redeem code."}
    if doc.get("used_by"):
        return {"ok": False, "msg": "❌ This code has already been redeemed."}
    credits = doc.get("credits", 0)
    codes_col.update_one(
        {"code": code},
        {"$set": {"used_by": user_id, "used_at": datetime.now(timezone.utc)}},
    )
    add_credits(user_id, credits)
    bump_stat("redeems")
    return {"ok": True, "msg": f"✅ Redeemed! You received {credits} credit(s).", "credits": credits}


# ─────────────────────────────── Keyboards ───────────────────────────────
def main_menu_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton(
                    "🔍 Lookup Number", callback_data="lookup",
                    style=enums.ButtonStyle.PRIMARY,
                )
            ],
            [
                types.InlineKeyboardButton(
                    "💰 Check Balance", callback_data="balance",
                    style=enums.ButtonStyle.SUCCESS,
                ),
                types.InlineKeyboardButton(
                    "🤝 Referral", callback_data="referral",
                    style=enums.ButtonStyle.DEFAULT,
                ),
            ],
            [
                types.InlineKeyboardButton(
                    "❓ Help", callback_data="help",
                    style=enums.ButtonStyle.DEFAULT,
                ),
            ],
        ]
    )


def admin_kb(user_id: int = None) -> types.InlineKeyboardMarkup:
    rows = main_menu_kb().inline_keyboard
    rows += [
        [
            types.InlineKeyboardButton(
                "🏦 Add Credit",
                callback_data=f"admin_add_credit|{user_id or ''}",
                style=enums.ButtonStyle.DANGER,
            )
        ],
        [
            types.InlineKeyboardButton(
                "👥 List Users", callback_data="admin_list_users",
                style=enums.ButtonStyle.PRIMARY,
            ),
            types.InlineKeyboardButton(
                "📊 Stats", callback_data="admin_stats",
                style=enums.ButtonStyle.DEFAULT,
            ),
        ],
    ]
    return types.InlineKeyboardMarkup(rows)


def buy_credit_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton(
                    "💰 Buy Credit", callback_data="buy_credit",
                    style=enums.ButtonStyle.DANGER,
                )
            ],
            [
                types.InlineKeyboardButton(
                    "❓ Help", callback_data="help",
                    style=enums.ButtonStyle.DEFAULT,
                ),
            ],
        ]
    )


def approval_kb(target_uid: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton(
                    "✅ Approve", callback_data=f"approve|{target_uid}",
                    style=enums.ButtonStyle.SUCCESS,
                ),
                types.InlineKeyboardButton(
                    "❌ Deny", callback_data=f"deny|{target_uid}",
                    style=enums.ButtonStyle.DANGER,
                ),
            ]
        ]
    )


def user_list_kb(users) -> types.InlineKeyboardMarkup:
    rows = []
    for u in users:
        uid = u.get("user_id", 0)
        uid_str = str(uid)
        approved = u.get("is_approved", False)
        name = u.get("first_name", "Unknown")
        label = f"{'✅' if approved else '❌'} {name} ({uid_str})"
        rows.append(
            [
                types.InlineKeyboardButton(
                    label, callback_data=f"user_detail|{uid_str}",
                    style=enums.ButtonStyle.DEFAULT,
                )
            ]
        )
    rows.append(
        [
            types.InlineKeyboardButton(
                "🔙 Back to Admin", callback_data="back_to_admin",
                style=enums.ButtonStyle.DEFAULT,
            )
        ]
    )
    return types.InlineKeyboardMarkup(rows)


def user_action_kb(target_uid: int) -> types.InlineKeyboardMarkup:
    uid_str = str(target_uid)
    doc = get_user(target_uid)
    approved = bool(doc and doc.get("is_approved")) if doc else False
    rows = []
    rows.append(
        [
            types.InlineKeyboardButton(
                "✅ Approve" if not approved else "🚫 Revoke",
                callback_data=f"toggle_approve|{uid_str}",
                style=enums.ButtonStyle.SUCCESS if not approved else enums.ButtonStyle.DANGER,
            )
        ]
    )
    rows.append(
        [
            types.InlineKeyboardButton(
                "💳 Add Credit", callback_data=f"admin_add_credit|{uid_str}",
                style=enums.ButtonStyle.DANGER,
            )
        ]
    )
    rows.append(
        [
            types.InlineKeyboardButton(
                "🔙 Back", callback_data="admin_list_users",
                style=enums.ButtonStyle.DEFAULT,
            )
        ]
    )
    return types.InlineKeyboardMarkup(rows)


# ─────────────────────────────── Handlers ───────────────────────────────
@app.on_message(filters.private)
def handle_message(client: Client, message: types.Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"
    username = message.from_user.username or None
    get_or_create_user(user_id, first_name, username)

    if message.text and message.text.startswith("/"):
        cmd = message.text.split()[0].lstrip("/").lower()
        if cmd == "start":
            _cmd_start(message)
        elif cmd == "help":
            _cmd_help(message)
        elif cmd == "admin":
            _cmd_admin(message)
        elif cmd == "balance":
            _cmd_balance(message)
        elif cmd == "referral":
            _cmd_referral(message)
        elif cmd == "listusers":
            _cmd_admin_list(message)
        elif cmd == "stats":
            _cmd_admin_stats(message)
        elif cmd == "lookup":
            _ask_lookup(message)
        elif cmd == "credit":
            _cmd_add_credit(message)
        elif cmd == "approve":
            _cmd_approve(message)
        elif cmd == "revoke":
            _cmd_revoke(message)
        elif cmd == "broadcast":
            _cmd_broadcast(message)
        elif cmd == "redeem":
            _cmd_redeem(message)
        elif cmd == "gencode":
            _cmd_gencode(message)
        elif cmd == "admininfo":
            _cmd_admininfo(message)
        else:
            message.reply_text("❓ Unknown command. Use /help or /start.",
                               reply_markup=main_menu_kb())
        return

    if message.text:
        _handle_text_input(message)


@app.on_message(filters.group)
def handle_group_message(client: Client, message: types.Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"
    username = message.from_user.username or None
    get_or_create_user(user_id, first_name, username)

    if message.text and message.text.startswith("/"):
        cmd = message.text.split()[0].lstrip("/").lower()

        if cmd == "start":
            start_payload = None
            parts = message.text.split()
            if len(parts) > 1:
                start_payload = parts[1].strip()
            if start_payload and len(start_payload) >= 3:
                referred = register_referral(user_id, start_payload)
                if referred:
                    doc = get_user(user_id)
                    message.reply_text(
                        f"✅ {first_name}, your referral was applied!\n"
                        f"Credits: {doc.get('credits', 0)}\n"
                        "Please use /balance in private for full details."
                    )
                    return
            bot_username = get_bot_username()
            text = (
                f"👋 Hello {first_name}!\n\n"
                "I'm a phone number lookup bot.\n\n"
                "Use me in <b>private chat</b> for full features:\n"
                f"👉 @{bot_username}\n\n"
                "Available commands:\n"
                "/start — welcome\n"
                "/help — help info\n"
                "/balance — check credits\n"
                "/referral — referral program"
            )
            message.reply_text(text)
            return

        if cmd == "help":
            text = (
                "📖 <b>How to use this bot</b>\n\n"
                "• 🔍 Lookup phone numbers\n"
                f"• 💰 Cost: {CREDIT_PER_LOOKUP} credit per lookup\n"
                "• 🤝 Referral program: invite friends for bonus credits\n\n"
                "Use /balance or /referral here, or switch to private chat."
            )
            message.reply_text(text)
            return

        if cmd == "balance":
            doc = get_user(user_id)
            if not doc:
                message.reply_text("❌ Please start the bot in private first.")
                return
            credits = doc.get("credits", 0)
            lookups = doc.get("total_lookups", 0)
            approved = is_approved(user_id)
            status = "✅ Approved" if approved else "⏳ Pending approval"
            text = (
                f"💰 <b>{first_name}'s Balance</b>\n\n"
                f"Status: {status}\n"
                f"Credits: <code>{credits}</code>\n"
                f"Lookups: <code>{lookups}</code>\n"
                f"Cost per lookup: <code>{CREDIT_PER_LOOKUP}</code>"
            )
            message.reply_text(text)
            return

        if cmd == "referral":
            doc = get_user(user_id)
            if not doc:
                message.reply_text("❌ Please start the bot in private first.")
                return
            if not is_approved(user_id):
                message.reply_text("⛔ You are not authorized.")
                return
            referral_code = doc.get("referral_code", "N/A")
            referrals_count = doc.get("referrals_count", 0)
            bot_username = get_bot_username()
            ref_link = f"https://t.me/{bot_username}?start={referral_code}"
            remaining = REFERRAL_THRESHOLD - (referrals_count % REFERRAL_THRESHOLD)
            text = (
                f"🤝 <b>Referral Program</b>\n\n"
                f"🔗 Your link: <code>{ref_link}</code>\n"
                f"📊 Referrals: <code>{referrals_count}</code>\n"
                f"🎁 Reward: {REFERRAL_BONUS_CREDITS} credits per {REFERRAL_THRESHOLD} referrals\n"
                f"⏳ Next bonus: {remaining} more"
            )
            message.reply_text(text)
            return

        message.reply_text(
            f"ℹ️ {first_name}, use the bot in <b>private chat</b> for lookups.\n"
            f"👉 @{get_bot_username()}"
        )
        return

    if message.text and (message.text.replace("+", "").isdigit() or
                          (len(message.text) >= 5 and all(c.isdigit() or c in '+ ' for c in message.text))):
        message.reply_text(
            f"🔒 {first_name}, phone number lookups are only available in <b>private chat</b> "
            f"for privacy reasons.\nPlease use /start in private: @{get_bot_username()}"
        )
        return

    if not message.text.startswith("/"):
        return


def _cmd_start(message: types.Message):
    uid = message.from_user.id
    first_name = message.from_user.first_name or "User"
    
    start_payload = None
    parts = message.text.split()
    if len(parts) > 1:
        start_payload = parts[1].strip()
    
    doc = get_or_create_user(uid, first_name, message.from_user.username)
    
    ref_credit_msg = ""
    if start_payload and len(start_payload) >= 3:
        referred = register_referral(uid, start_payload)
        if referred:
            doc = get_user(uid)
            ref_credit_msg = (
                f"\n\n🎁 <b>Referral bonus!</b> You received "
                f"{REFERRAL_WELCOME_CREDITS} extra credits for joining via a referral link."
            )
            credits = doc.get("credits", 0)
            message.reply_text(
                f"✅ Referral applied! Total credits: {credits}{ref_credit_msg}",
                reply_markup=main_menu_kb(),
            )

    if is_approved(uid):
        credits = doc.get("credits", 0)
        referral_code = doc.get("referral_code", "N/A")
        bot_username = get_bot_username()
        ref_link = f"https://t.me/{bot_username}?start={referral_code}"
        if ref_credit_msg:
            welcome_msg = "👋 Welcome! You joined via a referral link."
        else:
            welcome_msg = f"👋 Welcome back, {first_name}!"
        text = (
            f"{welcome_msg}\n\n"
            f"💰 You have {credits} credit(s).\n"
            f"🔍 Send a phone number to look it up (costs {CREDIT_PER_LOOKUP} credit).\n"
            f"🤝 Invite friends with your referral link:\n"
            f"<code>{ref_link}</code>\n\n"
            f"📈 Get {REFERRAL_BONUS_CREDITS} bonus credits for every {REFERRAL_THRESHOLD} referrals!"
        )
        message.reply_text(text, reply_markup=admin_kb() if str(uid) == str(ADMIN_ID) else main_menu_kb())
    else:
        text = (
            f"👋 Hello {first_name}!\n\n"
            "⏳ Your access request has been sent to the admin.\n"
            "📨 You will be notified once approved.\n\n"
            "💡 You already have "
            f"{DEFAULT_NEW_USER_CREDITS} welcome credits — "
            "but approval is required to use the bot."
        )
        message.reply_text(text)

        if ADMIN_ID:
            notification = (
                f"🆕 <b>New access request</b>\n\n"
                f"👤 Name: {first_name}\n"
                f"🆔 ID: {uid}\n"
                f"📛 Username: @{message.from_user.username or 'N/A'}\n\n"
                "Approve or deny below:"
            )
            try:
                app.send_message(
                    int(ADMIN_ID),
                    notification,
                    reply_markup=approval_kb(uid),

                )
            except Exception as e:
                logging.error("Could not notify admin: %s", e)


def _cmd_help(message: types.Message):
    if not is_approved(message.from_user.id):
        message.reply_text("⛔ You are not authorized.", reply_markup=buy_credit_kb())
        return
    help_text = (
        "📖 <b>How to use this bot</b>\n\n"
        f"🔍 Lookup: Send a phone number (e.g. <code>947426561</code>)\n"
        f"💰 Cost per lookup: <code>{CREDIT_PER_LOOKUP}</code> credit\n\n"
        "📋 Buttons:\n"
        "• Lookup Number — start a lookup\n"
        "• Check Balance — view your credit balance\n"
        "• Referral — invite friends for bonus credits\n"
        "• Help — show this help\n\n"
        "👑 Admin:\n"
        "/admin — open admin panel\n"
        "/approve &lt;id&gt; — approve user\n"
        "/revoke &lt;id&gt; — revoke user\n\n"
        "❓ Contact @Ankit_jii25 for issues."
    )
    message.reply_text(help_text, reply_markup=main_menu_kb())
def _cmd_admin(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    text = "👑 <b>Admin Panel</b>\n\nUse buttons below:"
    message.reply_text(text, reply_markup=admin_kb())


def _cmd_balance(message: types.Message):
    if not is_approved(message.from_user.id):
        message.reply_text("⛔ Unauthorized.", reply_markup=buy_credit_kb())
        return
    doc = get_user(message.from_user.id)
    credits = doc.get("credits", 0) if doc else 0
    lookups = doc.get("total_lookups", 0) if doc else 0
    text = (
        f"💰 <b>Balance</b>\n\n"
        f"Credits: <code>{credits}</code>\n"
        f"Total lookups: <code>{lookups}</code>\n"
        f"Cost per lookup: <code>{CREDIT_PER_LOOKUP}</code>\n\n"
        "💳 Need more? Contact the admin."
    )
    kb = admin_kb() if str(message.from_user.id) == str(ADMIN_ID) else main_menu_kb()
    message.reply_text(text, reply_markup=kb)


def _cmd_referral(message: types.Message):
    if not is_approved(message.from_user.id):
        message.reply_text("⛔ You are not authorized.", reply_markup=buy_credit_kb())
        return
    uid = message.from_user.id
    doc = get_user(uid)
    if not doc:
        message.reply_text("❌ User not found. Use /start first.")
        return
    referral_code = doc.get("referral_code", "N/A")
    referrals_count = doc.get("referrals_count", 0)
    bot_username = get_bot_username()
    ref_link = f"https://t.me/{bot_username}?start={referral_code}"
    remaining = REFERRAL_THRESHOLD - (referrals_count % REFERRAL_THRESHOLD)
    text = (
        f"🤝 <b>Referral Program</b>\n\n"
        f"🔗 <b>Your referral link:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 <b>Total referrals:</b> {referrals_count}\n"
        f"🎁 <b>Reward:</b> {REFERRAL_BONUS_CREDITS} bonus credits every {REFERRAL_THRESHOLD} referrals\n"
        f"⏳ <b>Next bonus in:</b> {remaining} more referral(s)\n\n"
        f"Share your link! Each friend who joins via your link gets "
        f"{DEFAULT_NEW_USER_CREDITS} welcome credits + "
        f"{REFERRAL_WELCOME_CREDITS} referral bonus."
    )
    is_admin = str(uid) == str(ADMIN_ID)
    message.reply_text(text, reply_markup=admin_kb() if is_admin else main_menu_kb())


def _cmd_add_credit(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    pending_input[message.from_user.id] = "awaiting_credit_user"
    message.reply_text(
        "🏦 <b>Add Credit</b>\n\n"
        "Send the <b>user_id</b> to add credits to:",
    )


def _cmd_approve(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        message.reply_text("❌ Usage: /approve <user_id>")
        return
    target = int(parts[1])
    pending_input[message.from_user.id] = None
    doc = get_or_create_user(target)
    if doc.get("is_approved"):
        message.reply_text(f"ℹ️ User {target} is already approved.")
    else:
        approve_user(target)
        message.reply_text(f"✅ User {target} approved.")
        bump_stat("approvals")
    _notify_approved(target, message.from_user.first_name)


def _notify_approved(uid: int, by: str):
    try:
        app.send_message(
            uid,
            f"🎉 Congratulations! Your request was approved by {by}.\n\n"
            "💰 You can now use the bot. Send a phone number to get started!",
            reply_markup=main_menu_kb(),
        )
    except Exception:
        logging.warning("Could not notify user %s", uid)


def _cmd_revoke(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        message.reply_text("❌ Usage: /revoke <user_id>")
        return
    target = int(parts[1])
    pending_input[message.from_user.id] = None
    doc = get_user(target)
    if doc and doc.get("is_approved"):
        revoke_user(target)
        message.reply_text(f"✅ User {target} revoked.")
        bump_stat("revocations")
    else:
        message.reply_text(f"ℹ️ User {target} was not approved.")


def _cmd_broadcast(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    pending_input[message.from_user.id] = "awaiting_broadcast_text"
    message.reply_text(
        "📣 <b>Broadcast</b>\n\n"
        "Send the message you want to broadcast to all users.\n"
        "You can include HTML formatting.\n\n"
        "Reply with <code>cancel</code> to abort.",
    )


def _cmd_redeem(message: types.Message):
    if not is_approved(message.from_user.id):
        message.reply_text("⛔ You are not authorized.", reply_markup=buy_credit_kb())
        return
    parts = message.text.split()
    if len(parts) < 2:
        message.reply_text(
            "🎟️ <b>Redeem Code</b>\n\n"
            "Usage: <code>/redeem &lt;CODE&gt;</code>\n\n"
            "Enter the redeem code you received from the admin.",
            reply_markup=main_menu_kb(),
        )
        return
    code = parts[1]
    result = redeem_code(message.from_user.id, code)
    doc = get_user(message.from_user.id)
    if result["ok"]:
        message.reply_text(
            f"{result['msg']}\n"
            f"💰 New balance: <code>{doc.get('credits', 0)}</code> credits.",
            reply_markup=main_menu_kb(),
        )
    else:
        message.reply_text(result["msg"], reply_markup=main_menu_kb())


def _cmd_admininfo(message: types.Message):
    admin_id = int(ADMIN_ID) if ADMIN_ID else None
    username = ADMIN_USERNAME or (f"@{ADMIN_CONTACT}" if not ADMIN_CONTACT.startswith("@") else ADMIN_CONTACT)
    name = ADMIN_NAME

    status = "unknown"
    if admin_id:
        try:
            admin_user = app.get_users(admin_id)
            us = getattr(admin_user, "status", None)
            if us == enums.UserStatus.ONLINE:
                status = "🟢 Online"
            elif us == enums.UserStatus.RECENTLY:
                status = "🟢 Recently Online"
            elif us == enums.UserStatus.LAST_WEEK:
                status = "🟡 Last Seen This Week"
            elif us == enums.UserStatus.LAST_MONTH:
                status = "🟠 Last Seen This Month"
            elif us == enums.UserStatus.OFFLINE:
                status = "🔴 Offline"
            elif us == enums.UserStatus.LONG_AGO:
                status = "🔴 Last Seen Long Ago"
            else:
                status = "🟡 Unknown"
            if not username and getattr(admin_user, "username", None):
                username = admin_user.username
            if name == "Admin" and getattr(admin_user, "first_name", None):
                name = admin_user.first_name
        except Exception:
            status = "🟡 Unknown"

    contact_line = ADMIN_CONTACT if ADMIN_CONTACT.startswith("@") else f"@{ADMIN_CONTACT}"
    text = (
        f"👑 <b>Admin Info</b>\n\n"
        f"👤 <b>Name:</b> {name}\n"
        f"📛 <b>Username:</b> @{username.lstrip('@')}\n"
        f"🕐 <b>Status:</b> {status}\n"
        f"📩 <b>Contact:</b> {contact_line}\n\n"
        f"💬 Message the admin to buy credits, request access, or get help."
    )
    kb = admin_kb() if str(message.from_user.id) == str(ADMIN_ID) else main_menu_kb()
    message.reply_text(text, reply_markup=kb)


def _cmd_gencode(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        message.reply_text(
            "🎟️ <b>Generate Redeem Code</b>\n\n"
            "Usage:\n"
            "<code>/gencode &lt;custom_code&gt; [amount]</code>\n"
            "<code>/gencode &lt;credits&gt; [count]</code>\n\n"
            "Examples:\n"
            "<code>/gencode MYCODE</code> — custom code, default credits\n"
            "<code>/gencode MYCODE 10</code> — custom code worth 10 credits\n"
            "<code>/gencode 10</code> — auto code worth 10 credits\n"
            "<code>/gencode 5 10</code> — ten auto codes worth 5 credits each",
            reply_markup=admin_kb(),
        )
        return

    first = parts[1]
    if first.isdigit():
        credits = int(first)
        count = 1
        if len(parts) >= 3:
            try:
                count = max(1, min(int(parts[2]), 100))
            except ValueError:
                message.reply_text("❌ Count must be a number.", reply_markup=admin_kb())
                return
        codes = create_redeem_codes(credits, count, message.from_user.id)
    else:
        custom_code = first.upper()
        if not re.match(r'^[A-Z0-9_-]{3,20}$', custom_code):
            message.reply_text(
                "❌ Invalid code. Use 3-20 chars of A-Z, 0-9, - or _.",
                reply_markup=admin_kb(),
            )
            return
        credits = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else DEFAULT_REDEEM_CREDITS
        count = 1
        codes = create_redeem_codes(credits, count, message.from_user.id, custom_code=custom_code)
        if not codes:
            message.reply_text(
                f"❌ Code <code>{custom_code}</code> already exists.",
                reply_markup=admin_kb(),
            )
            return

    bump_stat("codes_generated", count)
    text = (
        f"🎟️ <b>Redeem Codes Generated</b>\n\n"
        f"💳 Credits each: <code>{credits}</code>\n"
        f"🔢 Count: <code>{len(codes)}</code>\n\n"
        f"<code>{codes[0]}</code>"
    )
    if len(codes) > 1:
        code_lines = "\n".join(f"<code>{c}</code>" for c in codes)
        text = (
            f"🎟️ <b>Redeem Codes Generated</b>\n\n"
            f"💳 Credits each: <code>{credits}</code>\n"
            f"🔢 Count: <code>{len(codes)}</code>\n\n"
            f"{code_lines}"
        )
    message.reply_text(text, reply_markup=admin_kb())


def broadcast_to_all(text: str) -> dict:
    users = list(users_col.find({}))
    sent = 0
    failed = 0
    blocked = 0
    for u in users:
        uid = u.get("user_id")
        if not uid:
            continue
        try:
            app.send_message(uid, text)
            sent += 1
        except Exception as e:
            failed += 1
            if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower():
                blocked += 1
    return {"total": len(users), "sent": sent, "failed": failed, "blocked": blocked}


def format_broadcast_text(text: str) -> str:
    def link_repl(m):
        label = m.group(1)
        url = m.group(2)
        if not url.startswith(("http://", "https://", "tg://")):
            url = "https://" + url
        return f'<a href="{url}">{label}</a>'

    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', link_repl, text)
    text = re.sub(r'\[([^\]]+)\]\(([^\s)]+)\)', link_repl, text)
    text = re.sub(r'\[([^\]]+)\]', r'<b>\1</b>', text)
    text = re.sub(r'_([^_]+)_', r'<code>\1</code>', text)
    return text


def _cmd_admin_list(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    users = list(users_col.find({}))
    if not users:
        message.reply_text("📋 No users found.", reply_markup=admin_kb())
        return
    text = f"📋 <b>Users ({len(users)})</b>\n\n"
    for u in users:
        uid = u.get("user_id", "N/A")
        name = u.get("first_name", "Unknown")
        status = "✅" if u.get("is_approved") else "❌"
        cr = u.get("credits", 0)
        text += f"{status} <code>{uid}</code> — {name} ({cr} credits)\n"
    message.reply_text(text, reply_markup=user_list_kb(users))


def _cmd_admin_stats(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    stats = stats_col.find_one({"_id": "bot"}) or {}
    users = list(users_col.find({}))
    approved_count = sum(1 for u in users if u.get("is_approved"))
    total_credits = sum(u.get("credits", 0) for u in users)
    total_lookups = sum(u.get("total_lookups", 0) for u in users)
    text = (
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total users: <code>{len(users)}</code>\n"
        f"✅ Approved: <code>{approved_count}</code>\n"
        f"💰 Total credits: <code>{total_credits}</code>\n"
        f"🔍 Total lookups: <code>{total_lookups}</code>\n"
        f"🤝 Referrals: <code>{stats.get('referrals', 0)}</code>\n"
        f"🎁 Referral bonuses: <code>{stats.get('referral_bonuses', 0)}</code>\n"
        f"✅ Approvals: <code>{stats.get('approvals', 0)}</code>\n"
        f"🚫 Revocations: <code>{stats.get('revocations', 0)}</code>\n"
        f"👑 Admin ID: <code>{ADMIN_ID}</code>\n"
        f"🔗 API: <code>{API_URL}</code>\n"
    )
    message.reply_text(text, reply_markup=admin_kb())


def _ask_lookup(message: types.Message):
    if not is_approved(message.from_user.id):
        message.reply_text(
            "⛔ Not authorized. Contact admin.",
            reply_markup=buy_credit_kb(),
        )
        return
    doc = get_user(message.from_user.id)
    if doc.get("credits", 0) < CREDIT_PER_LOOKUP:
        message.reply_text(
            f"⚠️ Insufficient credits! You have {doc.get('credits', 0)}, "
            f"need {CREDIT_PER_LOOKUP}.\n\n"
            "💰 Request more from the admin.",
            reply_markup=buy_credit_kb(),
        )
        return
    pending_input[message.from_user.id] = "awaiting_lookup_number"
    message.reply_text(
        "🔍 <b>Enter phone number</b>\n\n"
        "Include country code:\n📱 Example: 947426561",
    )


def _handle_text_input(message: types.Message):
    uid = message.from_user.id
    state = pending_input.get(uid)

    if state == "awaiting_broadcast_text":
        if str(uid) != str(ADMIN_ID):
            pending_input[uid] = None
            return
        pending_input[uid] = None
        raw = message.text.strip()
        if raw.lower() == "cancel":
            message.reply_text("❌ Broadcast cancelled.", reply_markup=admin_kb())
            return
        if len(raw) < 1:
            message.reply_text("❌ Message cannot be empty.")
            return
        status_msg = message.reply_text(
            f"📣 Broadcasting to all users...\nThis may take a while.",
        )
        result = broadcast_to_all(format_broadcast_text(raw))
        bump_stat("broadcasts")
        text = (
            f"✅ <b>Broadcast complete</b>\n\n"
            f"👥 Total users: <code>{result['total']}</code>\n"
            f"📨 Sent: <code>{result['sent']}</code>\n"
            f"❌ Failed: <code>{result['failed']}</code>\n"
            f"🚫 Blocked bot: <code>{result['blocked']}</code>"
        )
        try:
            status_msg.edit_text(text, reply_markup=admin_kb())
        except Exception:
            message.reply_text(text, reply_markup=admin_kb())
        return

    if state == "awaiting_credit_user":
        raw = message.text.strip()
        if raw.isdigit():
            pending_input[uid] = ("awaiting_credit_amount", int(raw))
            message.reply_text(
                f"🏦 Now send the <b>amount</b> of credits to add for user {raw}:",
            )
        else:
            message.reply_text("❌ Please send a valid numeric user_id.")
        return

    if isinstance(state, tuple) and state[0] == "awaiting_credit_amount":
        target_uid = state[1]
        raw = message.text.strip()
        if raw.isdigit():
            amount = int(raw)
            add_credits(target_uid, amount)
            bump_stat("credits_added", amount)
            doc = get_user(target_uid)
            msg = (
                f"✅ Added {amount} credits to user {target_uid}.\n"
                f"New balance: {doc.get('credits', 0)}"
            )
            message.reply_text(msg, reply_markup=admin_kb())
            try:
                app.send_message(
                    target_uid,
                    f"🎁 You received {amount} credit(s) from the admin!\n"
                    f"New balance: {doc.get('credits', 0)}",
                    reply_markup=main_menu_kb(),
                )
            except Exception:
                pass
            pending_input[uid] = None
        else:
            message.reply_text("❌ Please send a valid numeric amount.")
        return

    if state == "awaiting_lookup_number":
        pending_input[uid] = None
        raw = message.text.strip()
        if not raw.replace("+", "").isdigit():
            message.reply_text("❌ Invalid number. Use digits only (e.g. 947426561).")
            return

        doc = get_user(uid)
        if doc.get("credits", 0) < CREDIT_PER_LOOKUP:
            message.reply_text(
                f"⚠️ Not enough credits (need {CREDIT_PER_LOOKUP}, have {doc.get('credits', 0)}).",
                reply_markup=buy_credit_kb(),
            )
            return

        deduct_credit(uid)
        bump_stat("lookups")
        _do_lookup(message, raw)
        return

    raw = message.text.strip()
    if raw.replace("+", "").isdigit() and len(raw) >= 5:
        if not is_approved(uid):
            message.reply_text("⛔ Not authorized. Contact admin.", reply_markup=buy_credit_kb())
            return
        doc = get_user(uid)
        if doc.get("credits", 0) < CREDIT_PER_LOOKUP:
            message.reply_text(
                f"⚠️ Not enough credits (need {CREDIT_PER_LOOKUP}, have {doc.get('credits', 0)}).",
                reply_markup=buy_credit_kb(),
            )
            return
        pending_input[uid] = None
        deduct_credit(uid)
        bump_stat("lookups")
        _do_lookup(message, raw)
        return


def _do_lookup(message: types.Message, phone_number: str):
    uid = message.from_user.id
    app.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    try:
        params = {"number": phone_number}
        logging.info("User %s querying API for %s", uid, phone_number)
        response = requests.get(API_URL, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            formatted = format_api_response(data, phone_number)
            kb = admin_kb() if str(uid) == str(ADMIN_ID) else main_menu_kb()
            app.send_message(message.chat.id, formatted, reply_markup=kb)
        else:
            app.send_message(
                message.chat.id,
                f"❌ API Error: {response.status_code}\nTry again later.",
                reply_markup=main_menu_kb(),
            )
            logging.error("API Error %s: %s", response.status_code, response.text)
    except requests.exceptions.Timeout:
        message.reply_text("⏰ API timed out.", reply_markup=main_menu_kb())
    except requests.exceptions.ConnectionError:
        message.reply_text("🌐 Connection error.", reply_markup=main_menu_kb())
    except Exception as e:
        message.reply_text(f"❌ Unexpected error: {str(e)[:100]}", reply_markup=main_menu_kb())


def format_api_response(data, phone_number):
    def replace_tag_credit(obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if key in ("tag", "credit"):
                    obj[key] = "@ABHISHEEK163"
                else:
                    replace_tag_credit(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                replace_tag_credit(item)

    replace_tag_credit(data)

    result_data = data.get("result", {})
    inner_result = result_data.get("result", {})
    records = inner_result.get("result", []) if isinstance(inner_result.get("result"), list) else [inner_result.get("result", {})]

    if not records:
        records = [{}]

    response_text = "🔍 <b>Lookup Result</b>\n\n"

    for record in records:
        if record:
            response_text += (
                f"📱 <b>Mobile:</b> <code>{record.get('num', 'N/A')}</code>\n"
                f"👤 <b>Name:</b> {record.get('name', 'N/A')}\n"
                f"👨‍👦 <b>Father:</b> {record.get('fname', 'N/A')}\n"
                f"🏠 <b>Address:</b> {record.get('address', 'N/A')}\n"
                f"🆔 <b>Adhaar:</b> <code>{record.get('aadhar', 'N/A')}</code>\n"
                f"📍 <b>Circle:</b> {record.get('circle', 'N/A')}\n"
                f"📞 <b>Alternate:</b> {record.get('alt', 'N/A')}\n"
                f"📧 <b>Email:</b> {record.get('email') or 'N/A'}\n"
            )
        response_text += "\n"

    tag = inner_result.get("tag", "@ABHISHEEK163")
    credit = result_data.get("credit", "@ABHISHEEK163")
    timestamp = result_data.get("meta", {}).get("timestamp", "N/A")
    response_text += f"🏷️ <b>Tag:</b> {tag}\n"
    response_text += f"👤 <b>Credit:</b> {credit}\n"
    response_text += f"🕐 <b>Timestamp:</b> {timestamp}"

    return response_text


# ────────────────────── Callback Query Handlers ───────────────────────────
@app.on_callback_query()
def handle_callback(client: Client, query: types.CallbackQuery):
    data = query.data
    uid = query.from_user.id
    first_name = query.from_user.first_name or "User"

    get_or_create_user(uid, first_name, query.from_user.username)

    def cb_answer(text: str, alert: bool = False):
        app.answer_callback_query(query.id, text, show_alert=alert)

    if data == "lookup":
        if not is_approved(uid):
            cb_answer("⛔ Not approved", alert=True)
            safe_edit_text(query.message,
                "⛔ You are not authorized. Contact admin.",
                reply_markup=buy_credit_kb(),
            )
            return
        doc = get_user(uid)
        if doc.get("credits", 0) < CREDIT_PER_LOOKUP:
            safe_edit_text(query.message,
                f"⚠️ Insufficient credits! You have {doc.get('credits', 0)}, "
                f"need {CREDIT_PER_LOOKUP}.",
                reply_markup=buy_credit_kb(),
            )
            return
        pending_input[uid] = "awaiting_lookup_number"
        safe_edit_text(query.message,
            "🔍 <b>Send phone number</b>\nExample: <code>947426561</code>",
        )
        cb_answer("Enter number")

    elif data == "balance":
        if not is_approved(uid):
            cb_answer("⛔ Not approved", alert=True)
            return
        doc = get_user(uid)
        credits = doc.get("credits", 0)
        lookups = doc.get("total_lookups", 0)
        referrals = doc.get("referrals_count", 0)
        referral_code = doc.get("referral_code", "N/A")
        bot_username = get_bot_username()
        ref_link = f"https://t.me/{bot_username}?start={referral_code}"
        kb = admin_kb() if str(uid) == str(ADMIN_ID) else main_menu_kb()
        safe_edit_text(query.message,
            f"💰 <b>Balance</b>\n\n"
            f"Credits: <code>{credits}</code>\n"
            f"Lookups: <code>{lookups}</code>\n"
            f"Referrals: <code>{referrals}</code>\n"
            f"🔗 Your link: <code>{ref_link}</code>",
            reply_markup=kb,
        )
        cb_answer("Balance updated")

    elif data == "referral":
        if not is_approved(uid):
            cb_answer("⛔ Not approved", alert=True)
            return
        doc = get_user(uid)
        if not doc:
            safe_edit_text(query.message, "❌ Error loading referral data. Use /start.", reply_markup=main_menu_kb())
            return
        referral_code = doc.get("referral_code", "N/A")
        referrals_count = doc.get("referrals_count", 0)
        bot_username = get_bot_username()
        ref_link = f"https://t.me/{bot_username}?start={referral_code}"
        remaining = REFERRAL_THRESHOLD - (referrals_count % REFERRAL_THRESHOLD)
        kb = admin_kb() if str(uid) == str(ADMIN_ID) else main_menu_kb()
        safe_edit_text(query.message, 
            f"🤝 <b>Referral Program</b>\n\n"
            f"🔗 <b>Your referral link:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>Total referrals:</b> {referrals_count}\n"
            f"🎁 <b>Reward:</b> {REFERRAL_BONUS_CREDITS} bonus credits every {REFERRAL_THRESHOLD} referrals\n"
            f"⏳ <b>Next bonus in:</b> {remaining} more referral(s)\n\n"
            f"Share your link! Each friend gets {DEFAULT_NEW_USER_CREDITS} welcome credits.",
            reply_markup=kb,
        )
        cb_answer("Referral info")

    elif data == "help":
        safe_edit_text(query.message, 
            "📖 <b>Help</b>\n\n"
            "Send a phone number to look it up.\n"
            f"Cost: {CREDIT_PER_LOOKUP} credit per lookup.\n"
            "Use buttons below:",
            reply_markup=main_menu_kb(),
        )
        cb_answer("Help")

    elif data == "buy_credit":
        safe_edit_text(query.message, 
            "💰 <b>Buy Credit</b>\n\n"
            "Contact the admin (@Ankit_jii25) to get more credits.\n"
            "You'll be notified once credits are added.",
            reply_markup=main_menu_kb(),
        )
        cb_answer("Contact admin")

    elif data == "admin_list_users":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        users = list(users_col.find({}))
        if not users:
            safe_edit_text(query.message, "📋 No users found.", reply_markup=admin_kb())
            return
        text = f"📋 <b>Users ({len(users)})</b>\n\n"
        for u in users:
            uid_val = u.get("user_id", "N/A")
            name = u.get("first_name", "Unknown")
            status = "✅" if u.get("is_approved") else "❌"
            cr = u.get("credits", 0)
            text += f"{status} <code>{uid_val}</code> — {name} ({cr} cr)\n"
        safe_edit_text(query.message, text, reply_markup=user_list_kb(users))
        cb_answer(f"Found {len(users)} users")

    elif data.startswith("user_detail|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        target_uid = int(data.split("|")[1])
        doc = get_user(target_uid)
        name = doc.get("first_name", "Unknown") if doc else "Unknown"
        cr = doc.get("credits", 0) if doc else 0
        approved = doc.get("is_approved", False) if doc else False
        lookups = doc.get("total_lookups", 0) if doc else 0
        text = (
            f"👤 <b>User Detail</b>\n\n"
            f"Name: <code>{name}</code>\n"
            f"ID: <code>{target_uid}</code>\n"
            f"Status: {'✅ Approved' if approved else '❌ Pending'}\n"
            f"Credits: <code>{cr}</code>\n"
            f"Lookups: <code>{lookups}</code>\n"
        )
        safe_edit_text(query.message, text, reply_markup=user_action_kb(target_uid))
        cb_answer(f"User {target_uid}")

    elif data.startswith("toggle_approve|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        target_uid = int(data.split("|")[1])
        doc = get_user(target_uid)
        if doc and doc.get("is_approved"):
            revoke_user(target_uid)
            cb_answer("User revoked")
            bump_stat("revocations")
        else:
            approve_user(target_uid)
            cb_answer("User approved")
            bump_stat("approvals")
            _notify_approved(target_uid, query.from_user.first_name)
        users = list(users_col.find({}))
        text = f"📋 <b>Users ({len(users)})</b>\n\n"
        for u in users:
            uid_val = u.get("user_id", "N/A")
            name = u.get("first_name", "Unknown")
            status = "✅" if u.get("is_approved") else "❌"
            cr = u.get("credits", 0)
            text += f"{status} <code>{uid_val}</code> — {name} ({cr} cr)\n"
        safe_edit_text(query.message, text, reply_markup=user_list_kb(users))
        cb_answer("User toggled")

    elif data.startswith("admin_add_credit|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        parts = data.split("|")
        target_uid = int(parts[1]) if len(parts) > 1 and parts[1] else None
        if target_uid:
            pending_input[uid] = ("awaiting_credit_amount", target_uid)
            safe_edit_text(query.message, 
                f"🏦 Send amount for user <code>{target_uid}</code>:",
            )
            cb_answer("Send amount")
        else:
            pending_input[uid] = "awaiting_credit_user"
            safe_edit_text(query.message, "🏦 Send the user_id:")
            cb_answer("Send user_id")

    elif data == "admin_stats":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        stats = stats_col.find_one({"_id": "bot"}) or {}
        users = list(users_col.find({}))
        approved_count = sum(1 for u in users if u.get("is_approved"))
        total_credits = sum(u.get("credits", 0) for u in users)
        total_lookups = sum(u.get("total_lookups", 0) for u in users)
        text = (
            "📊 <b>Stats</b>\n\n"
            f"👥 Users: <code>{len(users)}</code>\n"
            f"✅ Approved: <code>{approved_count}</code>\n"
            f"💰 Credits: <code>{total_credits}</code>\n"
            f"🔍 Lookups: <code>{total_lookups}</code>\n"
            f"🤝 Referrals: <code>{stats.get('referrals', 0)}</code>\n"
            f"🎁 Referral bonuses: <code>{stats.get('referral_bonuses', 0)}</code>\n"
            f"✅ Approvals: <code>{stats.get('approvals', 0)}</code>\n"
            f"🚫 Revocations: <code>{stats.get('revocations', 0)}</code>\n"
        )
        safe_edit_text(query.message, text, reply_markup=admin_kb())
        cb_answer("Stats")

    elif data == "back_to_admin":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        safe_edit_text(query.message, 
            "👑 <b>Admin Panel</b>\n\n",
            reply_markup=admin_kb(),
        )
        cb_answer("Back")

    elif data.startswith("approve|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        target_uid = int(data.split("|")[1])
        doc = get_or_create_user(target_uid)
        if doc.get("is_approved"):
            cb_answer("Already approved", alert=True)
        else:
            approve_user(target_uid)
            cb_answer("Approved!", alert=True)
            bump_stat("approvals")
            _notify_approved(target_uid, query.from_user.first_name)
            safe_edit_text(query.message, 
                f"✅ User {target_uid} approved.",
                reply_markup=admin_kb(),
            )

    elif data.startswith("deny|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        target_uid = int(data.split("|")[1])
        users_col.delete_one({"user_id_str": str(target_uid)})
        cb_answer("Denied!", alert=True)
        safe_edit_text(query.message, 
            f"❌ User {target_uid} denied.",
            reply_markup=admin_kb(),
        )


# ───────────────────────────────── Main ──────────────────────────────────
if __name__ == "__main__":
    print("🤖 Credit Bot starting...")
    print(f"🔗 API: {API_URL}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"💰 Credits/lookup: {CREDIT_PER_LOOKUP}")
    print(f"🆕 New user credits: {DEFAULT_NEW_USER_CREDITS}")
    print(f"🤝 Referral: {REFERRAL_WELCOME_CREDITS} welcome + {REFERRAL_BONUS_CREDITS} bonus per {REFERRAL_THRESHOLD} referrals")
    users_count = users_col.count_documents({})
    print(f"📂 MongoDB users loaded: {users_count}")
    print("📲 Bot running (private + group modes)...")
    app.run()
