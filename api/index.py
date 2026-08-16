import os
import functools
import random
import string
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash
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
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin123")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client.telegram_bot
users_col = db.users
stats_col = db.stats
codes_col = db.redeem_codes


def generate_redeem_code(length: int = 10) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not codes_col.find_one({"code": code}):
            return code


def create_redeem_codes(amount_credits: int, count: int = 1, created_by: int = None) -> list:
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
        }
        codes_col.insert_one(doc)
        created.append(code)
    return created


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == WEB_PASSWORD:
            session["logged_in"] = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash("Incorrect password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
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
    }
    return render_template("dashboard.html", stats=card_stats)


@app.route("/users")
@login_required
def users_list():
    users = list(users_col.find({}))
    return render_template("users.html", users=users)


@app.route("/users/<int:user_id>")
@login_required
def user_detail(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("users_list"))
    return render_template("user_detail.html", user=user)


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_approve(user_id):
    user = users_col.find_one({"user_id": user_id})
    if user:
        new_status = not user.get("is_approved", False)
        users_col.update_one(
            {"user_id": user_id}, {"$set": {"is_approved": new_status}}
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
    except ValueError:
        credits = 0
        count = 1
    if credits <= 0:
        flash("Credits must be a positive number.", "danger")
        return redirect(url_for("codes_list"))
    count = max(1, min(count, 100))
    codes = create_redeem_codes(credits, count)
    stats_col.update_one({"_id": "bot"}, {"$inc": {"codes_generated": count}}, upsert=True)
    flash(f"Generated {len(codes)} redeem code(s) worth {credits} credits each.", "success")
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)