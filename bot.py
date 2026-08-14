import os
import logging
import requests
import uuid
from datetime import datetime, timezone
from pyrogram import Client, enums, types
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

logging.info("Connecting to MongoDB...")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.telegram_bot
users_col = db.users
stats_col = db.stats
logging.info("MongoDB connected: %s", db.name)

CREDIT_PER_LOOKUP = int(os.environ.get("CREDIT_PER_LOOKUP", "1"))
DEFAULT_NEW_USER_CREDITS = int(os.environ.get("DEFAULT_NEW_USER_CREDITS", "5"))

pending_input = {}

app = Client("creditbot", bot_token=BOT_TOKEN)


# ─────────────────────────── MongoDB helpers ────────────────────────────
def get_or_create_user(user_id: int, first_name: str = "User", username: str = None):
    uid_str = str(user_id)
    doc = users_col.find_one({"user_id_str": uid_str})
    if not doc:
        doc = {
            "user_id": user_id,
            "user_id_str": uid_str,
            "first_name": first_name,
            "username": username or "",
            "is_approved": False,
            "credits": DEFAULT_NEW_USER_CREDITS,
            "total_lookups": 0,
            "created_at": datetime.now(timezone.utc),
        }
        users_col.insert_one(doc)
        logging.info("New user created: %s (%s)", uid_str, first_name)
    else:
        update_data = {"$set": {"first_name": first_name}}
        if username:
            update_data["$set"]["username"] = username
        if not doc.get("credits") and doc.get("credits") != 0:
            update_data["$setOn"] = {"credits": DEFAULT_NEW_USER_CREDITS}
        users_col.update_one({"user_id_str": uid_str}, update_data)
    return doc


def is_approved(user_id: int) -> bool:
    doc = users_col.find_one({"user_id_str": str(user_id)})
    return bool(doc and doc.get("is_approved"))


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
@app.on_message(enums.ChatType.PRIVATE)
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
        else:
            message.reply_text("❓ Unknown command. Use /help or /start.",
                               reply_markup=main_menu_kb())
        return

    if message.text:
        _handle_text_input(message)


def _cmd_start(message: types.Message):
    uid = message.from_user.id
    first_name = message.from_user.first_name or "User"
    doc = get_or_create_user(uid, first_name, message.from_user.username)

    if doc.get("is_approved"):
        credits = doc.get("credits", 0)
        text = (
            f"👋 Welcome back, {first_name}!\n\n"
            f"💰 You have {credits} credit(s).\n"
            f"🔍 Send a phone number to look it up (costs {CREDIT_PER_LOOKUP} credit).\n"
            f"Example: 947426561"
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
                    parse_mode="html",
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
        "• Help — show this help\n\n"
        "👑 Admin:\n"
        "/admin — open admin panel\n"
        "/approve &lt;id&gt; — approve user\n"
        "/revoke &lt;id&gt; — revoke user\n\n"
        "❓ Contact @Ankit_jii25 for issues."
    )
    message.reply_text(help_text, reply_markup=main_menu_kb(), parse_mode="html")


def _cmd_admin(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    text = "👑 <b>Admin Panel</b>\n\nUse buttons below:"
    message.reply_text(text, reply_markup=admin_kb(), parse_mode="html")


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
    message.reply_text(text, reply_markup=kb, parse_mode="html")


def _cmd_add_credit(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        message.reply_text("⛔ Admin only.")
        return
    pending_input[message.from_user.id] = "awaiting_credit_user"
    message.reply_text(
        "🏦 <b>Add Credit</b>\n\n"
        "Send the <b>user_id</b> to add credits to:",
        parse_mode="html",
    )


def _cmd_approve(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
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


def _cmd_admin_list(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
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
    message.reply_text(text, reply_markup=user_list_kb(users), parse_mode="html")


def _cmd_admin_stats(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
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
        f"✅ Approvals: <code>{stats.get('approvals', 0)}</code>\n"
        f"🚫 Revocations: <code>{stats.get('revocations', 0)}</code>\n"
        f"👑 Admin ID: <code>{ADMIN_ID}</code>\n"
        f"🔗 API: <code>{API_URL}</code>\n"
    )
    message.reply_text(text, reply_markup=admin_kb(), parse_mode="html")


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
        parse_mode="html",
    )


def _handle_text_input(message: types.Message):
    uid = message.from_user.id
    state = pending_input.get(uid)

    if state == "awaiting_credit_user":
        raw = message.text.strip()
        if raw.isdigit():
            pending_input[uid] = ("awaiting_credit_amount", int(raw))
            message.reply_text(
                f"🏦 Now send the <b>amount</b> of credits to add for user {raw}:",
                parse_mode="html",
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


def _do_lookup(message: types.Message, phone_number: str):
    uid = message.from_user.id
    app.send_chat_action(message.chat.id, "typing")
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
        app.answer_callback_query(query.id, text, alert=alert)

    if data == "lookup":
        if not is_approved(uid):
            cb_answer("⛔ Not approved", alert=True)
            query.message.edit_text(
                "⛔ You are not authorized. Contact admin.",
                reply_markup=buy_credit_kb(),
            )
            return
        doc = get_user(uid)
        if doc.get("credits", 0) < CREDIT_PER_LOOKUP:
            query.message.edit_text(
                f"⚠️ Insufficient credits! You have {doc.get('credits', 0)}, "
                f"need {CREDIT_PER_LOOKUP}.",
                reply_markup=buy_credit_kb(),
            )
            return
        pending_input[uid] = "awaiting_lookup_number"
        query.message.edit_text(
            "🔍 <b>Send phone number</b>\nExample: <code>947426561</code>",
            parse_mode="html",
        )
        cb_answer("Enter number")

    elif data == "balance":
        if not is_approved(uid):
            cb_answer("⛔ Not approved", alert=True)
            return
        doc = get_user(uid)
        credits = doc.get("credits", 0)
        lookups = doc.get("total_lookups", 0)
        kb = admin_kb() if str(uid) == str(ADMIN_ID) else main_menu_kb()
        query.message.edit_text(
            f"💰 <b>Balance</b>\n\nCredits: <code>{credits}</code>\n"
            f"Lookups: <code>{lookups}</code>",
            parse_mode="html",
            reply_markup=kb,
        )
        cb_answer("Balance updated")

    elif data == "help":
        query.message.edit_text(
            "📖 <b>Help</b>\n\n"
            "Send a phone number to look it up.\n"
            f"Cost: {CREDIT_PER_LOOKUP} credit per lookup.\n"
            "Use buttons below:",
            parse_mode="html",
            reply_markup=main_menu_kb(),
        )
        cb_answer("Help")

    elif data == "buy_credit":
        query.message.edit_text(
            "💰 <b>Buy Credit</b>\n\n"
            "Contact the admin (@Ankit_jii25) to get more credits.\n"
            "You'll be notified once credits are added.",
            parse_mode="html",
            reply_markup=main_menu_kb(),
        )
        cb_answer("Contact admin")

    elif data == "admin_add_credit":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        parts = data.split("|")
        target = int(parts[2]) if len(parts) > 2 and parts[2] else None
        if target:
            pending_input[uid] = ("awaiting_credit_amount", target)
            query.message.edit_text(
                f"🏦 Sending amount for user <code>{target}</code>:",
                parse_mode="html",
            )
        else:
            pending_input[uid] = "awaiting_credit_user"
            query.message.edit_text("🏦 Send the user_id to add credits to:")
        cb_answer("Send user_id or amount")

    elif data == "admin_list_users":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        users = list(users_col.find({}))
        if not users:
            query.message.edit_text("📋 No users found.", reply_markup=admin_kb())
            return
        text = f"📋 <b>Users ({len(users)})</b>\n\n"
        for u in users:
            uid_val = u.get("user_id", "N/A")
            name = u.get("first_name", "Unknown")
            status = "✅" if u.get("is_approved") else "❌"
            cr = u.get("credits", 0)
            text += f"{status} <code>{uid_val}</code> — {name} ({cr} cr)\n"
        query.message.edit_text(text, reply_markup=user_list_kb(users), parse_mode="html")
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
        query.message.edit_text(text, reply_markup=user_action_kb(target_uid), parse_mode="html")
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
        query.message.edit_text(text, reply_markup=user_list_kb(users), parse_mode="html")

    elif data.startswith("admin_add_credit|"):
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        parts = data.split("|")
        target_uid = int(parts[2]) if len(parts) > 2 and parts[2] else None
        if target_uid:
            pending_input[uid] = ("awaiting_credit_amount", target_uid)
            query.message.edit_text(
                f"🏦 Send amount for user <code>{target_uid}</code>:",
                parse_mode="html",
            )
            cb_answer("Send amount")
        else:
            pending_input[uid] = "awaiting_credit_user"
            query.message.edit_text("🏦 Send the user_id:")
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
            f"✅ Approvals: <code>{stats.get('approvals', 0)}</code>\n"
            f"🚫 Revocations: <code>{stats.get('revocations', 0)}</code>\n"
        )
        query.message.edit_text(text, reply_markup=admin_kb(), parse_mode="html")
        cb_answer("Stats")

    elif data == "back_to_admin":
        if str(uid) != str(ADMIN_ID):
            cb_answer("⛔ Admin only", alert=True)
            return
        query.message.edit_text(
            "👑 <b>Admin Panel</b>\n\n",
            parse_mode="html",
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
            query.message.edit_text(
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
        query.message.edit_text(
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
    users_count = users_col.count_documents({})
    print(f"📂 MongoDB users loaded: {users_count}")
    print("📲 Bot running...")
    app.run()
