import os
import functools
import random
import string
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("WEB_SECRET_KEY", "change-this-secret-key-in-production")

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://mondalabhisheek8_db_user:abhisheek@cluster0.m4wgvdi.mongodb.net/"
    "?retryWrites=true&w=majority",
)
ADMIN_ID = os.environ.get("ADMIN_ID")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "abhisheek2006")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "abhisheekmondal927@gmail.com")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client.telegram_bot
users_col = db.users
stats_col = db.stats
codes_col = db.redeem_codes
settings_col = db.admin_settings
lookups_col = db.lookups


def generate_redeem_code(length: int = 10) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not codes_col.find_one({"code": code}):
            return code


def create_redeem_codes(amount_credits: int, count: int = 1, created_by: int = None, max_redeems: int = 1) -> list:
    created = []
    for _ in range(count):
        code = generate_redeem_code()
        doc = {
            "code": code,
            "credits": amount_credits,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
            "used_by": None,
            "used_at": None,
            "max_redeems": max_redeems,
            "redeemed_by": [],
        }
        codes_col.insert_one(doc)
        created.append(code)
    return created


def ensure_admin_settings():
    """Seed admin settings (email + password hash) from env on first use."""
    doc = settings_col.find_one({"_id": "admin"})
    if doc:
        return doc
    doc = {
        "_id": "admin",
        "email": ADMIN_EMAIL,
        "password_hash": generate_password_hash(WEB_PASSWORD),
        "updated_at": datetime.now(timezone.utc),
    }
    settings_col.insert_one(doc)
    return doc


def get_admin_settings():
    return settings_col.find_one({"_id": "admin"}) or ensure_admin_settings()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


DEFAULT_MAINTENANCE_MESSAGE = (
    "🔧 <b>The bot is currently under maintenance.</b>\n\n"
    "Please try again later. Thank you for your patience!"
)


def get_maintenance_config():
    doc = stats_col.find_one({"_id": "bot"}) or {}
    return {
        "maintenance_mode": bool(doc.get("maintenance_mode", False)),
        "maintenance_message": doc.get("maintenance_message")
        or DEFAULT_MAINTENANCE_MESSAGE,
    }


def set_maintenance_mode(enabled: bool, message: str = None):
    update = {"maintenance_mode": enabled}
    if message:
        update["maintenance_message"] = message
    stats_col.update_one({"_id": "bot"}, {"$set": update}, upsert=True)


@app.route("/control")
@login_required
def control():
    config = get_maintenance_config()
    return render_template("control.html", maintenance=config)


@app.route("/control/maintenance", methods=["POST"])
@login_required
def control_maintenance():
    action = request.form.get("action", "")
    message = request.form.get("message", "").strip()
    if action == "enable":
        set_maintenance_mode(True, message or DEFAULT_MAINTENANCE_MESSAGE)
        flash("🔧 Bot is now in maintenance mode. Users will see the notice below.", "success")
    elif action == "disable":
        set_maintenance_mode(False)
        flash("✅ Bot is back online. Maintenance mode disabled.", "success")
    else:
        flash("Invalid action.", "danger")
    return redirect(url_for("control"))


@app.route("/control/broadcast", methods=["POST"])
@login_required
def control_broadcast():
    text = request.form.get("text", "").strip()
    if not text:
        flash("Broadcast message cannot be empty.", "danger")
        return redirect(url_for("control"))
    if not BOT_TOKEN:
        flash("BOT_TOKEN is not set in the environment. Cannot broadcast.", "danger")
        return redirect(url_for("control"))

    users = list(users_col.find({}))
    sent = failed = 0
    for u in users:
        uid = u.get("user_id")
        if not uid:
            continue
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": uid,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.ok:
                sent += 1
            else:
                failed += 1
        except requests.RequestException:
            failed += 1
    stats_col.update_one({"_id": "bot"}, {"$inc": {"broadcasts": 1}}, upsert=True)
    flash(
        f"📣 Broadcast sent to {sent} user(s)"
        + (f", {failed} failed." if failed else "."),
        "success",
    )
    return redirect(url_for("control"))


@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        settings = ensure_admin_settings()
        email_ok = email == settings.get("email", "").lower()
        pass_ok = check_password_hash(settings.get("password_hash", ""), password)
        if email_ok and pass_ok:
            session["logged_in"] = True
            session["admin_email"] = settings.get("email")
            flash("Welcome back! You are logged in.", "success")
            return redirect(url_for("dashboard"))
        if not email_ok:
            flash("Unknown email address.", "danger")
        else:
            flash("Incorrect password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    users = list(users_col.find({}))
    stats = stats_col.find_one({"_id": "bot"}) or {}

    approved_count = sum(1 for u in users if u.get("is_approved"))
    total_credits = sum(u.get("credits", 0) for u in users)
    total_lookups = sum(u.get("total_lookups", 0) for u in users)
    total_referrals = sum(u.get("referrals_count", 0) for u in users)

    card_stats = {
        "total_users": len(users),
        "approved": approved_count,
        "pending": len(users) - approved_count,
        "total_credits": total_credits,
        "total_lookups": total_lookups,
        "total_referrals": total_referrals,
        "referral_bonuses": stats.get("referral_bonuses", 0),
        "redeems": stats.get("redeems", 0),
        "codes_generated": stats.get("codes_generated", 0),
        "broadcasts": stats.get("broadcasts", 0),
        "lookup_records": lookups_col.count_documents({}),
    }
    return render_template("dashboard.html", stats=card_stats)


@app.route("/users")
@login_required
def users_list():
    q = request.args.get("q", "").strip().lower()
    query = {}
    if q:
        from bson import ObjectId
        try:
            q_int = int(q)
            query = {"$or": [
                {"user_id": q_int},
                {"first_name": {"$regex": q, "$options": "i"}},
                {"username": {"$regex": q, "$options": "i"}},
                {"referral_code": {"$regex": q, "$options": "i"}},
            ]}
        except ValueError:
            query = {"$or": [
                {"first_name": {"$regex": q, "$options": "i"}},
                {"username": {"$regex": q, "$options": "i"}},
                {"referral_code": {"$regex": q, "$options": "i"}},
            ]}
    users = list(users_col.find(query).sort("created_at", -1))
    return render_template("users.html", users=users, q=q)


@app.route("/users/<int:user_id>")
@login_required
def user_detail(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("users_list"))
    redeemed = list(codes_col.find({"used_by": user_id}).sort("used_at", -1))
    return render_template("user_detail.html", user=user, redeemed_codes=redeemed)


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_approve(user_id):
    user = users_col.find_one({"user_id": user_id})
    if user:
        new_status = not user.get("is_approved", False)
        users_col.update_one(
            {"user_id": user_id}, {"$set": {"is_approved": new_status}}
        )
        stats_col.update_one(
            {"_id": "bot"},
            {"$inc": {"approvals" if new_status else "revocations": 1}},
            upsert=True,
        )
        flash(
            f"User {user_id} {'approved' if new_status else 'revoked'}.",
            "success",
        )
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/users/<int:user_id>/credits", methods=["POST"])
@login_required
def add_credits(user_id):
    try:
        amount = int(request.form.get("amount", 0))
    except ValueError:
        amount = 0
    if amount == 0:
        flash("Enter a valid amount.", "danger")
        return redirect(url_for("user_detail", user_id=user_id))
    users_col.update_one({"user_id": user_id}, {"$inc": {"credits": amount}})
    stats_col.update_one(
        {"_id": "bot"}, {"$inc": {"credits_added": amount}}, upsert=True
    )
    flash(f"Added {amount} credits to user {user_id}.", "success")
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    result = users_col.delete_one({"user_id": user_id})
    if result.deleted_count:
        flash(f"User {user_id} deleted.", "success")
    else:
        flash("User not found.", "danger")
    return redirect(url_for("users_list"))


@app.route("/codes")
@login_required
def codes_list():
    codes = list(codes_col.find({}).sort("created_at", -1))
    return render_template("codes.html", codes=codes)


@app.route("/codes/generate", methods=["POST"])
@login_required
def codes_generate():
    try:
        credits = int(request.form.get("credits", 0))
        count = int(request.form.get("count", 1))
        max_redeems = int(request.form.get("max_redeems", 1))
    except ValueError:
        credits = 0
        count = 1
        max_redeems = 1
    if credits <= 0:
        flash("Credits must be a positive number.", "danger")
        return redirect(url_for("codes_list"))
    count = max(1, min(count, 100))
    max_redeems = max(1, min(max_redeems, 1000))
    codes = create_redeem_codes(credits, count, max_redeems=max_redeems)
    stats_col.update_one({"_id": "bot"}, {"$inc": {"codes_generated": count}}, upsert=True)
    flash(f"Generated {len(codes)} redeem code(s) worth {credits} credits each, redeemable by up to {max_redeems} person(s).", "success")
    return redirect(url_for("codes_list"))


@app.route("/codes/delete/<code>", methods=["POST"])
@login_required
def codes_delete(code):
    result = codes_col.delete_one({"code": code})
    if result.deleted_count:
        flash(f"Code {code} deleted.", "success")
    else:
        flash("Code not found.", "danger")
    return redirect(url_for("codes_list"))


@app.route("/lookups")
@login_required
def lookups_list():
    q = request.args.get("q", "").strip().lower()
    query = {}
    if q:
        try:
            q_int = int(q)
            query = {"$or": [
                {"number": {"$regex": q, "$options": "i"}},
                {"records.name": {"$regex": q, "$options": "i"}},
                {"user_id": q_int},
            ]}
        except ValueError:
            query = {"$or": [
                {"number": {"$regex": q, "$options": "i"}},
                {"records.name": {"$regex": q, "$options": "i"}},
            ]}
    lookups = list(lookups_col.find(query).sort("searched_at", -1).limit(200))

    user_names = {}
    user_ids = {l.get("user_id") for l in lookups if l.get("user_id")}
    for uid in user_ids:
        doc = users_col.find_one({"user_id": uid}, {"first_name": 1, "username": 1})
        if doc:
            user_names[uid] = doc

    for l in lookups:
        l["_id"] = str(l.get("_id"))
        record = None
        if l.get("records"):
            for r in l["records"]:
                if isinstance(r, dict) and r.get("name"):
                    record = r
                    break
        if not record and l.get("records"):
            first = l["records"][0]
            if isinstance(first, dict):
                record = first
        l["record"] = record or {}

    return render_template("lookups.html", lookups=lookups, q=q, user_names=user_names)


@app.route("/lookups/clear", methods=["POST"])
@login_required
def lookups_clear():
    count = lookups_col.count_documents({})
    lookups_col.delete_many({})
    flash(f"Cleared {count} lookup record(s).", "success")
    return redirect(url_for("lookups_list"))


@app.route("/profile")
@login_required
def profile():
    settings = get_admin_settings()
    return render_template("profile.html", settings=settings)


@app.route("/profile/email", methods=["POST"])
@login_required
def profile_email():
    settings = get_admin_settings()
    password = request.form.get("password", "")
    new_email = request.form.get("email", "").strip().lower()
    if not check_password_hash(settings.get("password_hash", ""), password):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("profile"))
    if "@" not in new_email or "." not in new_email:
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("profile"))
    settings_col.update_one(
        {"_id": "admin"},
        {"$set": {"email": new_email, "updated_at": datetime.now(timezone.utc)}},
    )
    session["admin_email"] = new_email
    flash("Email address updated.", "success")
    return redirect(url_for("profile"))


@app.route("/profile/password", methods=["POST"])
@login_required
def profile_password():
    settings = get_admin_settings()
    current = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not check_password_hash(settings.get("password_hash", ""), current):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("profile"))
    if len(new_password) < 6:
        flash("New password must be at least 6 characters.", "danger")
        return redirect(url_for("profile"))
    if new_password != confirm:
        flash("New passwords do not match.", "danger")
        return redirect(url_for("profile"))
    settings_col.update_one(
        {"_id": "admin"},
        {"$set": {"password_hash": generate_password_hash(new_password),
                  "updated_at": datetime.now(timezone.utc)}},
    )
    flash("Password changed successfully.", "success")
    return redirect(url_for("profile"))


@app.route("/favicon.ico")
@app.route("/favicon.png")
def favicon():
    resp = make_response(
        send_from_directory(app.static_folder, "favicon.png", mimetype="image/png")
    )
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)