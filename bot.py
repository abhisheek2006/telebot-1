import telebot
import requests
import json
import logging
import os
from telebot.types import Message

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Get environment variables from Railway
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

# Check if required variables are set
if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable is not set!")
    exit(1)

if not ADMIN_ID:
    logging.warning("ADMIN_ID environment variable is not set! Using default admin check will fail.")

# Supabase API endpoint
API_URL = "https://nmdllpezcocquamhgpmb.supabase.co/functions/v1/lookup"

# File to store approved users (persistent storage using Railway volume)
APPROVED_USERS_FILE = "approved_users.json"

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Load approved users from file
def load_approved_users():
    try:
        if os.path.exists(APPROVED_USERS_FILE):
            with open(APPROVED_USERS_FILE, 'r') as f:
                return set(json.load(f))
        return set()
    except json.JSONDecodeError:
        logging.error("Error reading approved_users.json, creating new file")
        return set()

# Save approved users to file
def save_approved_users(users):
    try:
        with open(APPROVED_USERS_FILE, 'w') as f:
            json.dump(list(users), f)
    except Exception as e:
        logging.error(f"Error saving approved users: {e}")

# Global set of approved user IDs
approved_users = load_approved_users()

# Check if user is approved
def is_user_approved(user_id):
    user_id_str = str(user_id)
    return user_id_str in approved_users or (ADMIN_ID and user_id_str == ADMIN_ID)

# Add user to approved list
def approve_user(user_id):
    user_id_str = str(user_id)
    if user_id_str not in approved_users:
        approved_users.add(user_id_str)
        save_approved_users(approved_users)
        return True
    return False

# Remove user from approved list
def revoke_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in approved_users:
        approved_users.remove(user_id_str)
        save_approved_users(approved_users)
        return True
    return False

# Admin-only decorator for commands
def admin_only(func):
    def wrapper(message):
        if ADMIN_ID and str(message.from_user.id) == ADMIN_ID:
            return func(message)
        else:
            bot.reply_to(message, "⛔ This command is only for the bot administrator.")
    return wrapper

# Command handler for /start
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "User"
    
    if is_user_approved(user_id):
        welcome_text = (
            f"👋 Welcome {first_name}!\n\n"
            "🔍 Send me a phone number and I'll look it up using the API.\n"
            "📱 Usage: Just send the number (e.g., 947426561)\n"
            "⚠️ Please include the country code.\n\n"
            "💡 Example: 947426561"
        )
        bot.reply_to(message, welcome_text)
    else:
        # Notify admin about new user
        if ADMIN_ID:
            notification = (
                f"🆕 New user requested access:\n"
                f"👤 Name: {first_name}\n"
                f"🆔 ID: {user_id}\n"
                f"📛 Username: @{username}\n"
                f"💬 Use /approve {user_id} to grant access"
            )
            try:
                bot.send_message(ADMIN_ID, notification)
            except:
                pass
        
        welcome_text = (
            f"👋 Welcome {first_name}!\n\n"
            "⏳ Your access request has been sent to the admin.\n"
            "📨 You will be notified once you are approved.\n\n"
            "💡 Please wait for admin approval."
        )
        bot.reply_to(message, welcome_text)

# Command handler for /help
@bot.message_handler(commands=['help'])
def send_help(message: Message):
    if not is_user_approved(message.from_user.id):
        bot.reply_to(message, "⛔ You are not authorized to use this bot. Please contact the admin.")
        return
        
    help_text = (
        "📖 How to use this bot:\n\n"
        "1️⃣ Send a phone number with country code\n"
        "2️⃣ The bot will query the Supabase API\n"
        "3️⃣ Get the lookup results\n\n"
        "🔢 Example: 947426561\n\n"
        "👑 Admin Commands:\n"
        "/approve <user_id> - Approve a user\n"
        "/revoke <user_id> - Revoke user access\n"
        "/listusers - List all approved users\n"
        "/stats - Show bot statistics\n\n"
        "❓ For any issues, contact @Ankit_jii25"
    )
    bot.reply_to(message, help_text)

# Admin commands
@bot.message_handler(commands=['approve'])
@admin_only
def approve_user_command(message: Message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /approve <user_id>")
            return
            
        user_id = parts[1]
        if approve_user(user_id):
            bot.reply_to(message, f"✅ User {user_id} has been approved successfully!")
            
            try:
                bot.send_message(user_id, "🎉 Congratulations! You have been approved to use this bot.\nSend me a phone number to get started!")
            except:
                bot.send_message(message.chat.id, f"⚠️ Could not notify user {user_id}. They may have started the bot.")
        else:
            bot.reply_to(message, f"ℹ️ User {user_id} is already approved.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['revoke'])
@admin_only
def revoke_user_command(message: Message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /revoke <user_id>")
            return
            
        user_id = parts[1]
        if ADMIN_ID and user_id == ADMIN_ID:
            bot.reply_to(message, "❌ Cannot revoke admin access!")
            return
            
        if revoke_user(user_id):
            bot.reply_to(message, f"✅ User {user_id} has been revoked successfully!")
            
            try:
                bot.send_message(user_id, "⛔ Your access to this bot has been revoked by the administrator.")
            except:
                pass
        else:
            bot.reply_to(message, f"ℹ️ User {user_id} was not approved.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['listusers'])
@admin_only
def list_users_command(message: Message):
    if not approved_users:
        bot.reply_to(message, "📋 No users are currently approved.")
        return
        
    user_list = "📋 <b>Approved Users:</b>\n\n"
    for i, user_id in enumerate(approved_users, 1):
        try:
            user = bot.get_chat(user_id)
            name = user.first_name or "Unknown"
            username = f" (@{user.username})" if user.username else ""
            user_list += f"{i}. {name}{username} - <code>{user_id}</code>\n"
        except:
            user_list += f"{i}. <code>{user_id}</code>\n"
            
    if ADMIN_ID:
        user_list += f"\n👑 <b>Admin:</b> <code>{ADMIN_ID}</code>"
    
    if len(user_list) > 4000:
        for part in [user_list[i:i+4000] for i in range(0, len(user_list), 4000)]:
            bot.send_message(message.chat.id, part, parse_mode='HTML')
    else:
        bot.reply_to(message, user_list, parse_mode='HTML')

@bot.message_handler(commands=['stats'])
@admin_only
def stats_command(message: Message):
    stats_text = (
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 <b>Total Approved Users:</b> {len(approved_users)}\n"
        f"👑 <b>Admin ID:</b> <code>{ADMIN_ID}</code>\n"
        f"🔗 <b>API Endpoint:</b> {API_URL}\n"
        f"📁 <b>Data File:</b> {APPROVED_USERS_FILE}\n"
    )
    bot.reply_to(message, stats_text, parse_mode='HTML')

# Main handler for text messages (phone numbers)
@bot.message_handler(func=lambda msg: True)
def handle_number_lookup(message: Message):
    user_id = message.from_user.id
    if not is_user_approved(user_id):
        bot.reply_to(message, "⛔ You are not authorized to use this bot. Please contact the admin.")
        return
    
    phone_number = message.text.strip()
    
    if not phone_number.replace('+', '').isdigit():
        bot.reply_to(message, "❌ Please send a valid phone number (digits only, optionally with + prefix)")
        return
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    try:
        params = {'number': phone_number}
        logging.info(f"User {user_id} querying API for number: {phone_number}")
        
        response = requests.get(API_URL, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            logging.info(f"API Response: {json.dumps(data, indent=2)}")
            formatted_response = format_api_response(data, phone_number)
            bot.reply_to(message, formatted_response, parse_mode='HTML')
        else:
            error_msg = f"❌ API Error: Status {response.status_code}\nPlease try again later."
            bot.reply_to(message, error_msg)
            logging.error(f"API Error: {response.status_code} - {response.text}")
            
    except requests.exceptions.Timeout:
        bot.reply_to(message, "⏰ API request timed out. Please try again.")
        logging.error("API request timed out")
    except requests.exceptions.ConnectionError:
        bot.reply_to(message, "🌐 Connection error. Please check your internet and try again.")
        logging.error("Connection error to API")
    except json.JSONDecodeError:
        bot.reply_to(message, "⚠️ Received invalid response from server. Please try again.")
        logging.error(f"JSON decode error: {response.text}")
    except Exception as e:
        bot.reply_to(message, f"❌ An unexpected error occurred: {str(e)[:100]}")
        logging.error(f"Unexpected error: {str(e)}")

def format_api_response(data, phone_number):
    try:
        result_data = data.get('result', {})
        inner_result = result_data.get('result', {})

        inner_result['tag'] = '@ABHISHEEK163'
        if 'credit' in result_data:
            result_data['credit'] = '@ABHISHEEK163'

        data['tag'] = '@ABHISHEEK163'
        if 'credit' in data:
            data['credit'] = '@ABHISHEEK163'

        formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
        return f"🔍 <b>Number Lookup Result</b>\n<code>{formatted_json}</code>"

    except Exception as e:
        logging.error(f"Error formatting response: {str(e)}")
        return f"⚠️ Could not parse response. Raw data:\n<code>{json.dumps(data, indent=2)[:500]}</code>"

# Health check endpoint for Railway
def health_check():
    return "Bot is running!", 200

# Run the bot
if __name__ == "__main__":
    print("🤖 Bot is starting on Railway...")
    print(f"🔗 Using API: {API_URL}")
    print(f"👥 Loaded {len(approved_users)} approved users")
    print("📲 Bot is running...")
    
    # Start polling with retry logic for Railway
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            logging.error(f"Bot polling error: {e}")
            logging.info("Restarting polling in 5 seconds...")
            import time
            time.sleep(5)