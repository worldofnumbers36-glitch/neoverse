"""
================================================================================
 NEOVERSE - Cyberpunk Virtual Universe Platform (Core Loop Prototype)
================================================================================
Single-file Flask + SQLite application.

SCOPE NOTE: The full NeoVerse spec (casinos, lotteries, mining, guilds, social
feeds, marketplace, admin moderation, etc.) is a multi-month, multi-service
project. This file implements a real, working CORE LOOP so the foundation is
solid and extendable:

    - Authentication (register / login / logout, hashed passwords, sessions)
    - User profiles (display name, avatar, bio, XP, level)
    - Multi-currency wallet (Neo = master currency, one-way conversion into
      4 other currencies, full transaction history)
    - Daily reward system (9-day streak cycle, randomized bonus chance,
      some days are Neo penalties instead of payouts)
    - Game marketplace MVP (developers set a Neo price and upload sandboxed
      HTML games, players browse + buy + play them; playing itself grants
      nothing - all economy flow happens through purchases and daily rewards)
    - Minimal admin panel (view users/games, toggle roles, remove games)
    - Lottery scratch cards, an instant investment mini-game, and an asset
      market with fluctuating prices (see SECTION 10.5)

Everything else in the original spec (guilds, casino, mining, social
network, chat, real estate, battle pass, etc.) is intentionally left
out of this first slice. Add features one section at a time on top of this
foundation rather than expanding this file all at once.

RUN:
    pip install flask --break-system-packages   (already present in most envs)
    python app.py
    -> http://127.0.0.1:5000
    -> sample admin login printed to console on first run

================================================================================
SECTION 1: IMPORTS & CONFIG
================================================================================
"""
import os
import sqlite3
import random
import secrets
import string
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, g,
    render_template_string, flash, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "neoverse.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "games")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("NEOVERSE_SECRET", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2MB max upload (HTML games)

# All currencies. NEO is the master currency. Others are one-way sinks:
# Neo -> Other is allowed, Other -> Neo is NEVER allowed (enforced in code).
# NOTE: per platform rules, ALL currencies here are fictional / virtual only
# and have no real-world value, cannot be withdrawn, redeemed, or exchanged
# for real money or goods.
CURRENCIES = {
    "NEO": {"name": "Neo", "master": True},
    "CYBER_DOLLAR": {"name": "Cyber Dollar", "rate_from_neo": 10},
    "QUANTUM_COIN": {"name": "Quantum Coin", "rate_from_neo": 5},
    "ARC_TOKEN": {"name": "Arc Token", "rate_from_neo": 8},
    "NANO_UNIT": {"name": "Nano Unit", "rate_from_neo": 20},
}
OTHER_CURRENCIES = [c for c in CURRENCIES if c != "NEO"]

# 9-slot daily reward ladder (Neo amounts). Most days are positive payouts,
# but a few are NEGATIVE (a small Neo penalty) to keep the streak meaningful
# and add a bit of casino-style risk. Day 9 is still the big payout.
# A "lucky" roll on a positive day multiplies the payout; a "lucky" roll on
# a negative (penalty) day cancels the penalty instead.
DAILY_REWARDS = [50, -20, 75, 90, -35, 140, 180, -60, 400]
LUCKY_CHANCE = 0.12
LUCKY_MULTIPLIER = 3

ALLOWED_GAME_EXT = {"html", "htm"}

GAME_CATEGORIES = ["Arcade", "Racing", "Action", "RPG", "Puzzle",
                    "Adventure", "Strategy", "Simulation", "Educational", "Casual"]

# ---- Lottery (scratch cards) ----
# Buying a batch reveals LOTTERY_CARD_COUNT individual cards, each hiding a
# random whole-number amount (which can be negative) of whichever currency
# was used to pay for the batch.
LOTTERY_CARD_COUNT = 16
LOTTERY_CARD_MIN = -100
LOTTERY_CARD_MAX = 100
LOTTERY_BATCH_COST = 300  # flat cost, in whichever currency is chosen, for a batch of 16 cards

# ---- Investment ----
# A single instant-resolution stake: the payout multiplier is rolled
# uniformly between these two bounds.
INVEST_MIN_MULTIPLIER = -10.0
INVEST_MAX_MULTIPLIER = 10.0

# ---- Asset Market ----
# Generic commodity / fictional sci-fi materials, 18 total. All trades
# settle in Neo. Seed prices below; the live price drifts randomly each
# time the market page is viewed (see asset_market route).
ASSET_SEED = [
    ("GOLD", "Gold", 500),
    ("SILVER", "Silver", 120),
    ("PLATINUM", "Platinum", 800),
    ("OIL", "Crude Oil", 60),
    ("URANIUM", "Uranium", 950),
    ("CYBER_CRYSTAL", "Cyber Crystal", 300),
    ("NANO_STEEL", "Nano Steel", 220),
    ("PLASMA_CORE", "Plasma Core", 650),
    ("QUANTUM_CHIP", "Quantum Chip", 1200),
    ("NEON_GLASS", "Neon Glass", 90),
    ("VOID_ORE", "Void Ore", 430),
    ("STARDUST", "Stardust", 2000),
    ("BIO_GEL", "Bio Gel", 75),
    ("CARBON_FIBER", "Carbon Fiber", 150),
    ("HOLOGRAM_SILK", "Hologram Silk", 340),
    ("DARK_MATTER", "Dark Matter", 5000),
    ("ICE_CRYSTAL", "Ice Crystal", 110),
    ("SOLAR_CELL", "Solar Cell", 200),
]
ASSET_JITTER_PCT = 0.08  # max +/-8% random price movement each time the market page loads

"""
================================================================================
SECTION 2: DATABASE LAYER (raw sqlite3, tables auto-created on startup)
================================================================================
"""

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        bio TEXT DEFAULT '',
        avatar_seed TEXT NOT NULL,
        xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 1,
        is_admin INTEGER NOT NULL DEFAULT 0,
        is_developer INTEGER NOT NULL DEFAULT 0,
        daily_streak INTEGER NOT NULL DEFAULT 0,
        last_daily_claim TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS balances (
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, currency),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        currency TEXT NOT NULL,
        amount INTEGER NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        developer_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT NOT NULL,
        filename TEXT NOT NULL,
        price INTEGER NOT NULL DEFAULT 0,
        play_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (developer_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS purchases (
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        price_paid INTEGER NOT NULL,
        purchased_at TEXT NOT NULL,
        PRIMARY KEY (user_id, game_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (game_id) REFERENCES games(id)
    );

    CREATE TABLE IF NOT EXISTS lottery_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        cost_paid INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS lottery_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER NOT NULL,
        slot_index INTEGER NOT NULL,
        value INTEGER NOT NULL,
        revealed INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (batch_id) REFERENCES lottery_batches(id)
    );

    CREATE TABLE IF NOT EXISTS investments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        amount_staked INTEGER NOT NULL,
        multiplier REAL NOT NULL,
        payout INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        current_price INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS asset_holdings (
        user_id INTEGER NOT NULL,
        asset_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, asset_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (asset_id) REFERENCES assets(id)
    );
    """)
    conn.commit()
    conn.close()


def seed_admin_and_demo():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        pw = "admin123"
        conn.execute("""
            INSERT INTO users (username, email, password_hash, display_name, bio,
                                avatar_seed, xp, level, is_admin, is_developer,
                                daily_streak, last_daily_claim, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 0, NULL, ?)
        """, ("admin", "admin@neoverse.local", generate_password_hash(pw),
              "NeoVerse Admin", "System administrator account.",
              "admin", 0, 1, datetime.utcnow().isoformat()))
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        conn.execute("INSERT INTO balances (user_id, currency, amount) VALUES (?, 'NEO', 100000)", (admin_id,))
        for cur in OTHER_CURRENCIES:
            conn.execute("INSERT INTO balances (user_id, currency, amount) VALUES (?, ?, 0)", (admin_id, cur))
        conn.commit()
        print("=" * 60)
        print(" NEOVERSE: sample admin account created")
        print("   username: admin")
        print(f"   password: {pw}")
        print(" CHANGE THIS PASSWORD before any real deployment.")
        print("=" * 60)

        # Seed one demo game so the marketplace isn't empty.
        demo_html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Neon Clicker</title>
<style>
  body{margin:0;background:#05060f;color:#7be0ff;font-family:sans-serif;
       display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh}
  h1{text-shadow:0 0 12px #00e5ff}
  button{background:#0a0f2a;color:#ffe066;border:2px solid #00e5ff;border-radius:10px;
         padding:18px 36px;font-size:20px;cursor:pointer;box-shadow:0 0 18px #00e5ff66}
  button:active{transform:scale(0.96)}
  #score{font-size:42px;margin:18px 0}
</style></head>
<body>
  <h1>NEON CLICKER</h1>
  <div id="score">0</div>
  <button onclick="document.getElementById('score').textContent=Number(document.getElementById('score').textContent)+1">
    TAP THE CORE
  </button>
</body></html>"""
        demo_id_row = conn.execute("""
            INSERT INTO games (developer_id, title, description, category, filename, price, play_count, created_at)
            VALUES (?, 'Neon Clicker', 'A tiny demo game seeded on first run.', 'Casual', 'demo_neon_clicker.html', 0, 0, ?)
        """, (admin_id, datetime.utcnow().isoformat()))
        conn.commit()
        with open(os.path.join(UPLOAD_DIR, "demo_neon_clicker.html"), "w") as f:
            f.write(demo_html)
    conn.close()


def seed_assets():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
    if existing == 0:
        for symbol, name, price in ASSET_SEED:
            conn.execute("INSERT INTO assets (symbol, name, current_price) VALUES (?, ?, ?)",
                         (symbol, name, price))
        conn.commit()
    conn.close()


"""
================================================================================
SECTION 3: HELPERS (auth, currency, leveling, daily rewards)
================================================================================
"""

def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u or not u["is_admin"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_balances(user_id):
    db = get_db()
    rows = db.execute("SELECT currency, amount FROM balances WHERE user_id=?", (user_id,)).fetchall()
    bal = {c: 0 for c in CURRENCIES}
    for r in rows:
        bal[r["currency"]] = r["amount"]
    return bal


def adjust_balance(user_id, currency, delta, note=""):
    db = get_db()
    row = db.execute("SELECT amount FROM balances WHERE user_id=? AND currency=?", (user_id, currency)).fetchone()
    if row is None:
        db.execute("INSERT INTO balances (user_id, currency, amount) VALUES (?, ?, 0)", (user_id, currency))
        current = 0
    else:
        current = row["amount"]
    new_amount = current + delta
    if new_amount < 0:
        raise ValueError("Insufficient balance")
    db.execute("UPDATE balances SET amount=? WHERE user_id=? AND currency=?", (new_amount, user_id, currency))
    db.execute("""INSERT INTO transactions (user_id, type, currency, amount, note, created_at)
                  VALUES (?, ?, ?, ?, ?, ?)""",
               (user_id, "credit" if delta >= 0 else "debit", currency, delta, note, datetime.utcnow().isoformat()))
    db.commit()


def grant_xp(user_id, amount):
    db = get_db()
    u = db.execute("SELECT xp, level FROM users WHERE id=?", (user_id,)).fetchone()
    new_xp = u["xp"] + amount
    new_level = min(1000, 1 + new_xp // 500)
    leveled_up = new_level > u["level"]
    db.execute("UPDATE users SET xp=?, level=? WHERE id=?", (new_xp, new_level, user_id))
    db.commit()
    if leveled_up:
        adjust_balance(user_id, "NEO", new_level * 10, f"Level up bonus (reached level {new_level})")
    return leveled_up, new_level


def daily_reward_status(user):
    today = date.today()
    last = user["last_daily_claim"]
    last_date = date.fromisoformat(last) if last else None
    can_claim = (last_date is None) or (last_date < today)
    # If they missed a day (gap > 1 day) streak resets.
    streak = user["daily_streak"]
    if last_date is not None and (today - last_date).days > 1:
        streak = 0
    next_day_index = streak % 9  # 0-indexed slot they will claim next
    return can_claim, streak, next_day_index


def get_asset_holdings(user_id):
    db = get_db()
    rows = db.execute("""SELECT a.id, a.symbol, a.name, a.current_price, COALESCE(h.quantity,0) AS quantity
                          FROM assets a
                          LEFT JOIN asset_holdings h ON h.asset_id = a.id AND h.user_id = ?
                          ORDER BY a.name""", (user_id,)).fetchall()
    return rows


"""
================================================================================
SECTION 4: TEMPLATES (cyberpunk neon-blue UI, dark navy/black, glassmorphism)
================================================================================
"""

BASE_CSS = """
:root{
  --bg-deep:#05060f; --bg-panel:rgba(10,14,32,0.65); --neon:#00e5ff;
  --neon-soft:#00e5ff55; --accent-yellow:#ffe066; --text:#d8f4ff; --text-dim:#7a8aa0;
  --danger:#ff4d6d; --good:#34f5b0;
}
*{box-sizing:border-box}
body{
  margin:0; min-height:100vh; font-family:'Segoe UI',system-ui,sans-serif; color:var(--text);
  background: radial-gradient(circle at 20% 20%, #0d1442 0%, #05060f 45%, #03040a 100%);
  background-attachment:fixed;
}
a{color:var(--neon); text-decoration:none}
.nav{
  display:flex; align-items:center; justify-content:space-between; padding:14px 28px;
  background:var(--bg-panel); backdrop-filter:blur(10px); border-bottom:1px solid var(--neon-soft);
  position:sticky; top:0; z-index:10;
}
.brand{font-weight:800; font-size:22px; letter-spacing:2px; color:var(--neon); text-shadow:0 0 14px var(--neon)}
.nav a{margin-left:18px; color:var(--text); font-size:14px}
.nav a:hover{color:var(--neon)}
.wrap{max-width:1000px; margin:0 auto; padding:28px 18px}
.card{
  background:var(--bg-panel); border:1px solid var(--neon-soft); border-radius:16px;
  padding:22px; margin-bottom:18px; backdrop-filter:blur(8px);
  box-shadow:0 0 24px -8px var(--neon);
}
.grid{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
h1,h2,h3{color:var(--text); margin-top:0}
h1{text-shadow:0 0 16px var(--neon-soft)}
.btn{
  display:inline-block; background:linear-gradient(135deg,#0a1640,#0d2050); color:var(--neon);
  border:1px solid var(--neon); padding:10px 20px; border-radius:10px; cursor:pointer;
  font-weight:600; letter-spacing:0.5px; transition:.15s;
}
.btn:hover{box-shadow:0 0 18px var(--neon); transform:translateY(-1px)}
.btn-yellow{border-color:var(--accent-yellow); color:var(--accent-yellow)}
.btn-yellow:hover{box-shadow:0 0 18px var(--accent-yellow)}
input,textarea,select{
  width:100%; padding:10px 12px; margin:6px 0 14px; border-radius:8px; border:1px solid #1c2a55;
  background:#070b1d; color:var(--text); font-size:14px;
}
input:focus,textarea:focus{outline:none; border-color:var(--neon)}
.flash{padding:10px 14px; border-radius:8px; margin-bottom:14px; font-size:14px}
.flash-error{background:#3a0f1a; border:1px solid var(--danger); color:#ffb3c1}
.flash-success{background:#0d2e23; border:1px solid var(--good); color:#bdfde6}
.badge{display:inline-block; padding:3px 10px; border-radius:20px; font-size:12px; border:1px solid var(--neon-soft)}
.currency-row{display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #14204a}
.currency-row:last-child{border-bottom:none}
.reward-grid{display:grid; grid-template-columns:repeat(9,1fr); gap:8px; margin:16px 0}
.reward-slot{
  aspect-ratio:1; border-radius:10px; border:1px solid var(--neon-soft); display:flex;
  align-items:center; justify-content:center; font-size:12px; text-align:center; padding:4px;
}
.reward-slot.done{background:#0d2050; color:var(--neon)}
.reward-slot.next{background:#1a0f3a; border-color:var(--accent-yellow); color:var(--accent-yellow); box-shadow:0 0 14px var(--accent-yellow)}
.reward-slot.future{color:var(--text-dim)}
.reward-slot.penalty{border-color:var(--danger)}
.reward-slot.penalty.next{box-shadow:0 0 14px var(--danger); border-color:var(--danger); color:#ffb3c1}
.game-card{display:flex; flex-direction:column; gap:8px}
.game-iframe-wrap{border:1px solid var(--neon-soft); border-radius:12px; overflow:hidden; height:520px}
.game-iframe-wrap iframe{width:100%; height:100%; border:none}
table{width:100%; border-collapse:collapse; font-size:14px}
th,td{text-align:left; padding:8px; border-bottom:1px solid #14204a}
.small{color:var(--text-dim); font-size:12px}

/* ---- Mobile nav (hamburger via checkbox hack, no JS needed) ---- */
.nav-toggle{display:none}
.nav-burger{display:none; cursor:pointer; font-size:26px; line-height:1; color:var(--neon); padding:4px 6px}
.nav-links{display:flex; align-items:center; flex-wrap:wrap}
.nav-links a{margin-left:18px}

/* ---- Generic responsive helpers used by some forms ---- */
.responsive-row{display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap}
.responsive-row > div{flex:1; min-width:140px}
.scratch-grid{grid-template-columns:repeat(4,1fr)}

/* ================== MOBILE LAYOUT ================== */
@media (max-width:768px){
  .nav{padding:12px 16px; flex-wrap:wrap}
  .brand{font-size:19px}
  .nav-burger{display:block}
  .nav-links{
    display:none; flex-direction:column; align-items:stretch;
    width:100%; margin-top:10px; gap:0;
  }
  .nav-toggle:checked ~ .nav-links{display:flex}
  .nav-links a{
    margin-left:0; padding:10px 4px; width:100%;
    border-bottom:1px solid #14204a; font-size:15px;
  }
}

@media (max-width:600px){
  .wrap{padding:18px 12px}
  h1{font-size:21px}
  h2{font-size:18px}
  .card{padding:16px; border-radius:12px}
  .grid{grid-template-columns:1fr; gap:12px}
  .reward-grid{grid-template-columns:repeat(3,1fr); gap:6px}
  .reward-slot{font-size:11px; padding:2px}
  .scratch-grid{grid-template-columns:repeat(3,1fr)}
  .game-iframe-wrap{height:380px}
  .currency-row{flex-wrap:wrap; gap:4px}
  table{display:block; overflow-x:auto; -webkit-overflow-scrolling:touch; white-space:nowrap}
  input,textarea,select{font-size:16px} /* prevents iOS auto-zoom on focus */
  .btn{width:100%; text-align:center; padding:12px 16px}
  .responsive-row{flex-direction:column; align-items:stretch}
  .responsive-row > div{min-width:0}
}

@media (max-width:400px){
  .reward-grid{grid-template-columns:repeat(2,1fr)}
  .scratch-grid{grid-template-columns:repeat(2,1fr)}
}
"""

BASE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · NeoVerse</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <div class="nav">
    <a href="{{ url_for('index') }}" class="brand">NEOVERSE</a>
    <input type="checkbox" id="nav-toggle" class="nav-toggle">
    <label for="nav-toggle" class="nav-burger">&#9776;</label>
    <div class="nav-links">
      {% if user %}
        <a href="{{ url_for('index') }}">Dashboard</a>
        <a href="{{ url_for('games_list') }}">Games</a>
        <a href="{{ url_for('wallet') }}">Wallet</a>
        <a href="{{ url_for('daily_reward') }}">Daily Reward</a>
        <a href="{{ url_for('lottery') }}">Lottery</a>
        <a href="{{ url_for('investment') }}">Investment</a>
        <a href="{{ url_for('asset_market') }}">Market</a>
        <a href="{{ url_for('profile', username=user['username']) }}">{{ user['display_name'] }}</a>
        {% if user['is_admin'] %}<a href="{{ url_for('admin_panel') }}">Admin</a>{% endif %}
        <a href="{{ url_for('logout') }}">Logout</a>
      {% else %}
        <a href="{{ url_for('login') }}">Login</a>
        <a href="{{ url_for('register') }}">Register</a>
      {% endif %}
    </div>
  </div>
  <div class="wrap">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for category, msg in messages %}
        <div class="flash flash-{{ category }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}
    {{ body|safe }}
  </div>
</body>
</html>
"""


def render_page(title, body_html, **extra):
    body = render_template_string(body_html, user=current_user(), **extra)
    return render_template_string(BASE_TEMPLATE, title=title, css=BASE_CSS, body=body, user=current_user())


"""
================================================================================
SECTION 5: AUTH ROUTES
================================================================================
"""

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip() or username

        if not (3 <= len(username) <= 20) or not username.isalnum():
            flash("Username must be 3-20 alphanumeric characters.", "error")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("register"))

        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username=? OR email=?", (username, email)).fetchone():
            flash("Username or email already in use.", "error")
            return redirect(url_for("register"))

        avatar_seed = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        db.execute("""
            INSERT INTO users (username, email, password_hash, display_name, bio, avatar_seed,
                                xp, level, is_admin, is_developer, daily_streak, last_daily_claim, created_at)
            VALUES (?, ?, ?, ?, '', ?, 0, 1, 0, 0, 0, NULL, ?)
        """, (username, email, generate_password_hash(password), display_name, avatar_seed,
              datetime.utcnow().isoformat()))
        db.commit()
        user_id = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        for cur in CURRENCIES:
            db.execute("INSERT INTO balances (user_id, currency, amount) VALUES (?, ?, ?)",
                       (user_id, cur, 200 if cur == "NEO" else 0))
        db.commit()
        session["user_id"] = user_id
        flash("Welcome to NeoVerse. You received a 200 Neo starter grant.", "success")
        return redirect(url_for("index"))

    body = """
    <div class="card" style="max-width:420px;margin:40px auto">
      <h2>Create Account</h2>
      <form method="post">
        <label>Username</label><input name="username" required>
        <label>Display Name</label><input name="display_name">
        <label>Email</label><input type="email" name="email" required>
        <label>Password</label><input type="password" name="password" required>
        <button class="btn" type="submit">Register</button>
      </form>
      <p class="small">Already have an account? <a href="{{ url_for('login') }}">Log in</a></p>
    </div>
    """
    return render_page("Register", body)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['display_name']}.", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    body = """
    <div class="card" style="max-width:420px;margin:40px auto">
      <h2>Log In</h2>
      <form method="post">
        <label>Username</label><input name="username" required>
        <label>Password</label><input type="password" name="password" required>
        <button class="btn" type="submit">Log In</button>
      </form>
      <p class="small">New here? <a href="{{ url_for('register') }}">Create an account</a></p>
      <p class="small">Demo admin: <b>admin</b> / <b>admin123</b></p>
    </div>
    """
    return render_page("Login", body)


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


"""
================================================================================
SECTION 6: DASHBOARD
================================================================================
"""

@app.route("/")
@login_required
def index():
    user = current_user()
    bal = get_balances(user["id"])
    can_claim, streak, next_idx = daily_reward_status(user)
    db = get_db()
    recent_games = db.execute("SELECT * FROM games ORDER BY created_at DESC LIMIT 3").fetchall()
    body = """
    <h1>Welcome back, {{ user['display_name'] }}</h1>
    <div class="grid">
      <div class="card">
        <h3>Level {{ user['level'] }}</h3>
        <p>XP: {{ user['xp'] }} / {{ user['level'] * 500 }} to next level</p>
        <p><span class="badge">{{ bal['NEO'] }} Neo</span></p>
      </div>
      <div class="card">
        <h3>Daily Reward</h3>
        <p>Streak: {{ streak }} days</p>
        {% if can_claim %}
          <a class="btn btn-yellow" href="{{ url_for('daily_reward') }}">Claim today's reward</a>
        {% else %}
          <p class="small">Already claimed today. Come back tomorrow.</p>
        {% endif %}
      </div>
      <div class="card">
        <h3>Quick Links</h3>
        <p><a href="{{ url_for('wallet') }}">View Wallet & Convert Currency</a></p>
        <p><a href="{{ url_for('games_list') }}">Browse Games</a></p>
        <p><a href="{{ url_for('profile', username=user['username']) }}">Edit Profile</a></p>
      </div>
    </div>
    <h2>Newest Games</h2>
    <div class="grid">
      {% for game in recent_games %}
        <div class="card">
          <b>{{ game['title'] }}</b><br>
          <span class="small">{{ game['category'] }} · {{ game['play_count'] }} plays</span><br>
          <a class="btn" style="margin-top:8px" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
        </div>
      {% else %}
        <p>No games yet.</p>
      {% endfor %}
    </div>
    """
    return render_page("Dashboard", body, bal=bal, can_claim=can_claim, streak=streak, recent_games=recent_games)


"""
================================================================================
SECTION 7: PROFILE
================================================================================
"""

@app.route("/profile/<username>")
@login_required
def profile(username):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        abort(404)
    is_self = current_user()["username"] == username
    body = """
    <div class="card">
      <h1>{{ target['display_name'] }} <span class="small">@{{ target['username'] }}</span></h1>
      <p>{{ target['bio'] or 'No bio yet.' }}</p>
      <p><span class="badge">Level {{ target['level'] }}</span>
         <span class="badge">{{ target['xp'] }} XP</span>
         {% if target['is_developer'] %}<span class="badge">Developer</span>{% endif %}
         {% if target['is_admin'] %}<span class="badge">Admin</span>{% endif %}</p>
      <p class="small">Joined {{ target['created_at'][:10] }}</p>
    </div>
    {% if is_self %}
    <div class="card">
      <h3>Edit Profile</h3>
      <form method="post" action="{{ url_for('edit_profile') }}">
        <label>Display Name</label><input name="display_name" value="{{ target['display_name'] }}">
        <label>Bio</label><textarea name="bio" rows="3">{{ target['bio'] }}</textarea>
        <button class="btn" type="submit">Save</button>
      </form>
    </div>
    {% endif %}
    """
    return render_page(f"{target['display_name']}", body, target=target, is_self=is_self)


@app.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile():
    user = current_user()
    db = get_db()
    db.execute("UPDATE users SET display_name=?, bio=? WHERE id=?",
               (request.form.get("display_name", user["display_name"]).strip()[:40],
                request.form.get("bio", "").strip()[:300],
                user["id"]))
    db.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("profile", username=user["username"]))


"""
================================================================================
SECTION 8: WALLET & CURRENCY CONVERSION
================================================================================
"""

@app.route("/wallet", methods=["GET", "POST"])
@login_required
def wallet():
    user = current_user()
    if request.method == "POST":
        target_currency = request.form.get("currency")
        try:
            neo_amount = int(request.form.get("neo_amount", "0"))
        except ValueError:
            neo_amount = 0
        if target_currency not in OTHER_CURRENCIES or neo_amount <= 0:
            flash("Invalid conversion request.", "error")
        else:
            bal = get_balances(user["id"])
            if bal["NEO"] < neo_amount:
                flash("Not enough Neo for that conversion.", "error")
            else:
                rate = CURRENCIES[target_currency]["rate_from_neo"]
                gained = neo_amount * rate
                adjust_balance(user["id"], "NEO", -neo_amount, f"Converted to {target_currency}")
                adjust_balance(user["id"], target_currency, gained, f"Converted from Neo")
                flash(f"Converted {neo_amount} Neo into {gained} {CURRENCIES[target_currency]['name']}.", "success")
        return redirect(url_for("wallet"))

    bal = get_balances(user["id"])
    db = get_db()
    history = db.execute("""SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 25""",
                          (user["id"],)).fetchall()
    body = """
    <h1>Wallet</h1>
    <div class="card">
      <h3>Balances</h3>
      {% for code, info in currencies.items() %}
        <div class="currency-row">
          <span>{{ info['name'] }}{% if info.get('master') %} <span class="small">(master currency)</span>{% endif %}</span>
          <b>{{ bal[code] }}</b>
        </div>
      {% endfor %}
    </div>
    <div class="card">
      <h3>Convert Neo &rarr; Other Currency</h3>
      <p class="small">One-way only. Converted currencies cannot be converted back into Neo. All currencies are
        fictional and have no real-world value.</p>
      <form method="post">
        <label>Amount of Neo to convert</label>
        <input type="number" name="neo_amount" min="1" required>
        <label>Target currency</label>
        <select name="currency">
          {% for code in other_currencies %}
            <option value="{{ code }}">{{ currencies[code]['name'] }} (rate: 1 Neo = {{ currencies[code]['rate_from_neo'] }})</option>
          {% endfor %}
        </select>
        <button class="btn" type="submit">Convert</button>
      </form>
    </div>
    <div class="card">
      <h3>Recent Transactions</h3>
      <table>
        <tr><th>Date</th><th>Type</th><th>Currency</th><th>Amount</th><th>Note</th></tr>
        {% for tx in history %}
          <tr>
            <td class="small">{{ tx['created_at'][:19] }}</td>
            <td>{{ tx['type'] }}</td>
            <td>{{ tx['currency'] }}</td>
            <td>{{ tx['amount'] }}</td>
            <td class="small">{{ tx['note'] }}</td>
          </tr>
        {% else %}
          <tr><td colspan="5" class="small">No transactions yet.</td></tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_page("Wallet", body, bal=bal, currencies=CURRENCIES,
                        other_currencies=OTHER_CURRENCIES, history=history)


"""
================================================================================
SECTION 9: DAILY REWARDS
================================================================================
"""

@app.route("/rewards/daily", methods=["GET", "POST"])
@login_required
def daily_reward():
    user = current_user()
    can_claim, streak, next_idx = daily_reward_status(user)

    if request.method == "POST":
        if not can_claim:
            flash("You already claimed today's reward.", "error")
            return redirect(url_for("daily_reward"))
        base_amount = DAILY_REWARDS[next_idx]
        lucky = random.random() < LUCKY_CHANCE
        is_penalty_day = base_amount < 0

        if is_penalty_day:
            if lucky:
                amount = 0  # lucky escape: penalty cancelled
            else:
                # Cap the penalty so the balance can never go negative.
                current_neo = get_balances(user["id"])["NEO"]
                amount = -min(abs(base_amount), current_neo)
        else:
            amount = base_amount * LUCKY_MULTIPLIER if lucky else base_amount

        new_streak = streak + 1
        db = get_db()
        db.execute("UPDATE users SET daily_streak=?, last_daily_claim=? WHERE id=?",
                   (new_streak, date.today().isoformat(), user["id"]))
        db.commit()

        note = f"Daily reward day {next_idx + 1}"
        if is_penalty_day:
            note += " (lucky escape)" if lucky else " (penalty)"
        elif lucky:
            note += " (LUCKY x3!)"

        if amount != 0:
            adjust_balance(user["id"], "NEO", amount, note)
        grant_xp(user["id"], 15)

        if is_penalty_day:
            if lucky:
                flash(f"Lucky escape! Day {next_idx + 1} was a penalty day but you avoided it.", "success")
            else:
                flash(f"Day {next_idx + 1} was a penalty day. You lost {abs(amount)} Neo.", "error")
        elif lucky:
            flash(f"LUCKY BONUS! You claimed {amount} Neo (day {next_idx + 1} reward x3).", "success")
        else:
            flash(f"You claimed {amount} Neo (day {next_idx + 1} of your streak).", "success")
        return redirect(url_for("daily_reward"))

    body = """
    <h1>Daily Reward</h1>
    <div class="card">
      <p>Current streak: <b>{{ streak }}</b> day(s). Missing a full day resets your streak.</p>
      <div class="reward-grid">
        {% for i in range(9) %}
          {% set day_streak_pos = streak % 9 %}
          {% set is_penalty = rewards[i] < 0 %}
          <div class="reward-slot {% if is_penalty %}penalty{% endif %} {% if i < day_streak_pos %}done{% elif i == next_idx %}next{% else %}future{% endif %}">
            Day {{ i + 1 }}<br>{{ '+' if rewards[i] >= 0 else '' }}{{ rewards[i] }} Neo
          </div>
        {% endfor %}
      </div>
      {% if can_claim %}
        <form method="post"><button class="btn {% if rewards[next_idx] < 0 %}{% else %}btn-yellow{% endif %}" type="submit">
          Claim Day {{ next_idx + 1 }} {% if rewards[next_idx] < 0 %}(Risk: Penalty Day){% else %}Reward{% endif %}
        </button></form>
      {% else %}
        <p class="small">Come back tomorrow for your next reward.</p>
      {% endif %}
      <p class="small">Every claim has a {{ (lucky_chance*100)|round(0) }}% chance of a {{ lucky_mult }}x lucky bonus
        on reward days, or a fully cancelled penalty on penalty days. Penalties never push your Neo balance below 0.</p>
    </div>
    """
    return render_page("Daily Reward", body, streak=streak, next_idx=next_idx, can_claim=can_claim,
                        rewards=DAILY_REWARDS, lucky_chance=LUCKY_CHANCE, lucky_mult=LUCKY_MULTIPLIER)


"""
================================================================================
SECTION 10: GAME MARKETPLACE (upload + play)
================================================================================
"""

def allowed_game_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_GAME_EXT


@app.route("/games")
@login_required
def games_list():
    db = get_db()
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    query = "SELECT g.*, u.display_name AS dev_name FROM games g JOIN users u ON g.developer_id = u.id WHERE 1=1"
    params = []
    if category:
        query += " AND g.category = ?"
        params.append(category)
    if q:
        query += " AND g.title LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY g.created_at DESC"
    games = db.execute(query, params).fetchall()
    body = """
    <h1>Game Marketplace</h1>
    <div class="card">
      <form method="get" class="responsive-row">
        <div><label>Search</label><input name="q" value="{{ request.args.get('q','') }}"></div>
        <div>
          <label>Category</label>
          <select name="category">
            <option value="">All</option>
            {% for c in categories %}<option value="{{ c }}" {% if c==category %}selected{% endif %}>{{ c }}</option>{% endfor %}
          </select>
        </div>
        <div><button class="btn" type="submit" style="margin-bottom:14px">Filter</button></div>
      </form>
    </div>
    <p><a class="btn btn-yellow" href="{{ url_for('upload_game') }}">+ Upload a Game</a></p>
    <div class="grid">
      {% for game in games %}
        <div class="card game-card">
          <b>{{ game['title'] }}</b>
          <span class="small">{{ game['category'] }} · by {{ game['dev_name'] }} · {{ game['play_count'] }} plays</span>
          <span class="badge" style="width:fit-content">{% if game['price'] > 0 %}{{ game['price'] }} Neo{% else %}Free{% endif %}</span>
          <span class="small">{{ game['description'] }}</span>
          <a class="btn" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
        </div>
      {% else %}
        <p>No games found.</p>
      {% endfor %}
    </div>
    """
    return render_page("Games", body, games=games, categories=GAME_CATEGORIES, category=category)


@app.route("/games/upload", methods=["GET", "POST"])
@login_required
def upload_game():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:60]
        description = request.form.get("description", "").strip()[:300]
        category = request.form.get("category")
        file = request.files.get("game_file")
        try:
            price = int(request.form.get("price", "0"))
        except ValueError:
            price = -1

        if not title or category not in GAME_CATEGORIES:
            flash("Title and a valid category are required.", "error")
            return redirect(url_for("upload_game"))
        if price < 0:
            flash("Price must be 0 (free) or a positive Neo amount.", "error")
            return redirect(url_for("upload_game"))
        if not file or file.filename == "" or not allowed_game_file(file.filename):
            flash("Please upload a single .html file.", "error")
            return redirect(url_for("upload_game"))

        db = get_db()
        # Mark uploader as a developer automatically on first upload.
        if not user["is_developer"]:
            db.execute("UPDATE users SET is_developer=1 WHERE id=?", (user["id"],))
            db.commit()

        safe_name = secure_filename(file.filename)
        unique_name = f"{secrets.token_hex(8)}_{safe_name}"
        file.save(os.path.join(UPLOAD_DIR, unique_name))

        db.execute("""INSERT INTO games (developer_id, title, description, category, filename, price, play_count, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                   (user["id"], title, description, category, unique_name, price, datetime.utcnow().isoformat()))
        db.commit()
        flash("Game uploaded! It now appears in the marketplace.", "success")
        return redirect(url_for("games_list"))

    body = """
    <h1>Upload a Game</h1>
    <div class="card" style="max-width:520px">
      <p class="small">Single .html file only (max 2MB). Your game runs inside a sandboxed iframe
        with scripts allowed but no access to the parent page or top-level navigation.</p>
      <form method="post" enctype="multipart/form-data">
        <label>Title</label><input name="title" required>
        <label>Description</label><textarea name="description" rows="3"></textarea>
        <label>Category</label>
        <select name="category">
          {% for c in categories %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
        </select>
        <label>Price (Neo) &mdash; 0 for free</label>
        <input type="number" name="price" min="0" value="0" required>
        <p class="small">Players pay this once in Neo to unlock the game. The full amount goes straight to
          your wallet. You and admins can always play your own games for free.</p>
        <label>Game File (.html)</label>
        <input type="file" name="game_file" accept=".html,.htm" required>
        <button class="btn" type="submit">Publish</button>
      </form>
    </div>
    """
    return render_page("Upload Game", body, categories=GAME_CATEGORIES)


@app.route("/games/play/<int:game_id>", methods=["GET", "POST"])
@login_required
def play_game(game_id):
    db = get_db()
    game = db.execute("""SELECT g.*, u.display_name AS dev_name FROM games g
                          JOIN users u ON g.developer_id = u.id WHERE g.id=?""", (game_id,)).fetchone()
    if not game:
        abort(404)
    user = current_user()

    already_owned = db.execute("SELECT 1 FROM purchases WHERE user_id=? AND game_id=?",
                                (user["id"], game_id)).fetchone() is not None
    is_free_or_exempt = (game["price"] == 0) or (game["developer_id"] == user["id"]) or bool(user["is_admin"])
    can_play = already_owned or is_free_or_exempt

    if not can_play:
        if request.method == "POST":
            bal = get_balances(user["id"])
            if bal["NEO"] < game["price"]:
                flash(f"You need {game['price']} Neo to buy this game. You have {bal['NEO']}.", "error")
                return redirect(url_for("play_game", game_id=game_id))
            adjust_balance(user["id"], "NEO", -game["price"], f"Purchased game: {game['title']}")
            adjust_balance(game["developer_id"], "NEO", game["price"], f"Sale of game: {game['title']}")
            db.execute("INSERT INTO purchases (user_id, game_id, price_paid, purchased_at) VALUES (?, ?, ?, ?)",
                       (user["id"], game_id, game["price"], datetime.utcnow().isoformat()))
            db.commit()
            flash(f"Purchased {game['title']} for {game['price']} Neo.", "success")
            can_play = True
        else:
            body = """
            <h1>{{ game['title'] }}</h1>
            <div class="card" style="max-width:480px">
              <p class="small">{{ game['category'] }} · by {{ game['dev_name'] }}</p>
              <p>{{ game['description'] }}</p>
              <p>This game costs <b>{{ game['price'] }} Neo</b> to unlock. It's a one-time purchase &mdash;
                you can replay it for free after buying.</p>
              <form method="post"><button class="btn btn-yellow" type="submit">Buy & Play for {{ game['price'] }} Neo</button></form>
              <p><a href="{{ url_for('games_list') }}">&larr; Back to Marketplace</a></p>
            </div>
            """
            return render_page(game["title"], body, game=game)

    # Player owns / can freely access the game: just play it. No Neo or XP is
    # awarded for playing - rewards only come from daily rewards, not gameplay.
    db.execute("UPDATE games SET play_count = play_count + 1 WHERE id=?", (game_id,))
    db.commit()

    body = """
    <h1>{{ game['title'] }}</h1>
    <p class="small">{{ game['category'] }} · by {{ game['dev_name'] }} · {{ game['play_count'] }} plays</p>
    <p>{{ game['description'] }}</p>
    <div class="game-iframe-wrap">
      <iframe src="{{ url_for('serve_game_file', filename=game['filename']) }}"
              sandbox="allow-scripts allow-forms"></iframe>
    </div>
    <p><a href="{{ url_for('games_list') }}">&larr; Back to Marketplace</a></p>
    """
    return render_page(game["title"], body, game=game)


@app.route("/uploads/games/<filename>")
@login_required
def serve_game_file(filename):
    safe = secure_filename(filename)
    return send_from_directory(UPLOAD_DIR, safe, mimetype="text/html")


"""
================================================================================
SECTION 10.5: LOTTERY (SCRATCH CARDS), INVESTMENT, ASSET MARKET
NOTE: all currencies here remain the same fictional / virtual currencies
defined in CURRENCIES above - no real-world value, not redeemable.
================================================================================
"""

@app.route("/lottery", methods=["GET", "POST"])
@login_required
def lottery():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        currency = request.form.get("currency")
        if currency not in CURRENCIES:
            flash("Invalid currency.", "error")
            return redirect(url_for("lottery"))
        bal = get_balances(user["id"])
        if bal[currency] < LOTTERY_BATCH_COST:
            flash(f"You need {LOTTERY_BATCH_COST} {CURRENCIES[currency]['name']} to buy a batch of "
                  f"{LOTTERY_CARD_COUNT} scratch cards.", "error")
            return redirect(url_for("lottery"))

        adjust_balance(user["id"], currency, -LOTTERY_BATCH_COST,
                        f"Bought {LOTTERY_CARD_COUNT} lottery scratch cards")
        cur = db.execute("""INSERT INTO lottery_batches (user_id, currency, cost_paid, created_at)
                             VALUES (?, ?, ?, ?)""",
                          (user["id"], currency, LOTTERY_BATCH_COST, datetime.utcnow().isoformat()))
        db.commit()
        batch_id = cur.lastrowid
        for i in range(LOTTERY_CARD_COUNT):
            value = random.randint(LOTTERY_CARD_MIN, LOTTERY_CARD_MAX)
            db.execute("""INSERT INTO lottery_cards (batch_id, slot_index, value, revealed)
                          VALUES (?, ?, ?, 0)""", (batch_id, i, value))
        db.commit()
        flash(f"Bought {LOTTERY_CARD_COUNT} scratch cards for {LOTTERY_BATCH_COST} "
              f"{CURRENCIES[currency]['name']}. Scratch them one by one!", "success")
        return redirect(url_for("lottery_batch", batch_id=batch_id))

    batches = db.execute("""SELECT b.*,
                                 (SELECT COUNT(*) FROM lottery_cards c WHERE c.batch_id=b.id AND c.revealed=0) AS unrevealed_count,
                                 (SELECT COALESCE(SUM(value),0) FROM lottery_cards c WHERE c.batch_id=b.id AND c.revealed=1) AS revealed_total
                          FROM lottery_batches b WHERE b.user_id=? ORDER BY b.created_at DESC LIMIT 15""",
                          (user["id"],)).fetchall()
    body = """
    <h1>Lottery: Scratch Cards</h1>
    <div class="card" style="max-width:480px">
      <p class="small">Buy a batch of {{ count }} scratch cards at once. Each card hides a random amount
        between {{ min_v }} and {{ max_v }} of the currency you pay with &mdash; some cards are losses,
        some are big wins. Scratch them one at a time on the next page.</p>
      <form method="post">
        <label>Pay with</label>
        <select name="currency">
          {% for code, info in currencies.items() %}
            <option value="{{ code }}">{{ info['name'] }}</option>
          {% endfor %}
        </select>
        <button class="btn btn-yellow" type="submit">Buy {{ count }} Cards for {{ cost }}</button>
      </form>
    </div>
    <h2>Your Recent Batches</h2>
    <div class="grid">
      {% for b in batches %}
        <div class="card">
          <b>Batch #{{ b['id'] }}</b> &middot; {{ b['currency'] }}<br>
          <span class="small">Bought {{ b['created_at'][:19] }} for {{ b['cost_paid'] }}</span><br>
          {% if b['unrevealed_count'] > 0 %}
            <span class="badge">{{ b['unrevealed_count'] }} cards left to scratch</span>
          {% else %}
            <span class="badge">Net result: {{ '+' if b['revealed_total'] >= 0 else '' }}{{ b['revealed_total'] }}</span>
          {% endif %}
          <br><a class="btn" style="margin-top:8px" href="{{ url_for('lottery_batch', batch_id=b['id']) }}">View</a>
        </div>
      {% else %}
        <p>No batches purchased yet.</p>
      {% endfor %}
    </div>
    """
    return render_page("Lottery", body, currencies=CURRENCIES, count=LOTTERY_CARD_COUNT,
                        cost=LOTTERY_BATCH_COST, min_v=LOTTERY_CARD_MIN, max_v=LOTTERY_CARD_MAX,
                        batches=batches)


@app.route("/lottery/batch/<int:batch_id>")
@login_required
def lottery_batch(batch_id):
    user = current_user()
    db = get_db()
    batch = db.execute("SELECT * FROM lottery_batches WHERE id=?", (batch_id,)).fetchone()
    if not batch or (batch["user_id"] != user["id"] and not user["is_admin"]):
        abort(404)
    cards = db.execute("SELECT * FROM lottery_cards WHERE batch_id=? ORDER BY slot_index", (batch_id,)).fetchall()
    revealed_total = sum(c["value"] for c in cards if c["revealed"])
    all_revealed = all(c["revealed"] for c in cards)
    body = """
    <h1>Scratch Card Batch #{{ batch['id'] }}</h1>
    <p class="small">Currency: {{ batch['currency'] }} &middot; Paid: {{ batch['cost_paid'] }} &middot; Bought {{ batch['created_at'][:19] }}</p>
    <div class="reward-grid scratch-grid">
      {% for c in cards %}
        {% if c['revealed'] %}
          <div class="reward-slot {% if c['value'] < 0 %}penalty{% endif %} done">
            #{{ c['slot_index'] + 1 }}<br>{{ '+' if c['value'] >= 0 else '' }}{{ c['value'] }}
          </div>
        {% else %}
          <form method="post" action="{{ url_for('lottery_scratch', batch_id=batch['id'], card_id=c['id']) }}">
            <button class="reward-slot next" type="submit" style="width:100%;cursor:pointer">
              #{{ c['slot_index'] + 1 }}<br>Scratch
            </button>
          </form>
        {% endif %}
      {% endfor %}
    </div>
    <div class="card" style="max-width:380px">
      <p>Revealed total so far: <b>{{ '+' if revealed_total >= 0 else '' }}{{ revealed_total }} {{ batch['currency'] }}</b></p>
      {% if all_revealed %}<p class="small">All cards revealed for this batch.</p>{% endif %}
    </div>
    <p><a href="{{ url_for('lottery') }}">&larr; Back to Lottery</a></p>
    """
    return render_page("Scratch Cards", body, batch=batch, cards=cards,
                        revealed_total=revealed_total, all_revealed=all_revealed)


@app.route("/lottery/scratch/<int:batch_id>/<int:card_id>", methods=["POST"])
@login_required
def lottery_scratch(batch_id, card_id):
    user = current_user()
    db = get_db()
    batch = db.execute("SELECT * FROM lottery_batches WHERE id=?", (batch_id,)).fetchone()
    if not batch or batch["user_id"] != user["id"]:
        abort(404)
    card = db.execute("SELECT * FROM lottery_cards WHERE id=? AND batch_id=?", (card_id, batch_id)).fetchone()
    if not card:
        abort(404)
    if not card["revealed"]:
        db.execute("UPDATE lottery_cards SET revealed=1 WHERE id=?", (card_id,))
        db.commit()
        value = card["value"]
        if value > 0:
            adjust_balance(user["id"], batch["currency"], value,
                            f"Lottery win: batch #{batch_id} card #{card['slot_index']+1}")
            flash(f"Card #{card['slot_index']+1}: you won {value} {batch['currency']}!", "success")
        elif value < 0:
            current_amt = get_balances(user["id"])[batch["currency"]]
            loss = -min(abs(value), current_amt)
            if loss != 0:
                adjust_balance(user["id"], batch["currency"], loss,
                                f"Lottery loss: batch #{batch_id} card #{card['slot_index']+1}")
            flash(f"Card #{card['slot_index']+1}: you lost {abs(loss)} {batch['currency']}.", "error")
        else:
            flash(f"Card #{card['slot_index']+1}: empty, no change.", "success")
    return redirect(url_for("lottery_batch", batch_id=batch_id))


@app.route("/investment", methods=["GET", "POST"])
@login_required
def investment():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        currency = request.form.get("currency")
        try:
            amount = int(request.form.get("amount", "0"))
        except ValueError:
            amount = 0
        if currency not in CURRENCIES or amount <= 0:
            flash("Enter a valid amount and currency.", "error")
            return redirect(url_for("investment"))
        bal = get_balances(user["id"])
        if bal[currency] < amount:
            flash("Not enough balance to invest that amount.", "error")
            return redirect(url_for("investment"))

        adjust_balance(user["id"], currency, -amount, "Investment stake")
        multiplier = round(random.uniform(INVEST_MIN_MULTIPLIER, INVEST_MAX_MULTIPLIER), 2)
        profit = round(amount * multiplier)
        payout = max(0, amount + profit)
        if payout > 0:
            adjust_balance(user["id"], currency, payout, f"Investment payout (x{multiplier})")
        db.execute("""INSERT INTO investments (user_id, currency, amount_staked, multiplier, payout, created_at)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (user["id"], currency, amount, multiplier, payout, datetime.utcnow().isoformat()))
        db.commit()

        net = payout - amount
        if net >= 0:
            flash(f"Investment closed at x{multiplier}: you staked {amount} and got back {payout} "
                  f"{currency} (net +{net}).", "success")
        else:
            flash(f"Investment closed at x{multiplier}: you staked {amount} and got back {payout} "
                  f"{currency} (net {net}).", "error")
        return redirect(url_for("investment"))

    history = db.execute("""SELECT * FROM investments WHERE user_id=? ORDER BY created_at DESC LIMIT 20""",
                          (user["id"],)).fetchall()
    body = """
    <h1>Investment</h1>
    <div class="card" style="max-width:420px">
      <p class="small">Stake any amount of a currency and immediately get a result between
        {{ min_m }}x and {{ max_m }}x. Results resolve instantly &mdash; your stake can never drop your
        balance below what you already had before staking.</p>
      <form method="post">
        <label>Currency</label>
        <select name="currency">
          {% for code, info in currencies.items() %}
            <option value="{{ code }}">{{ info['name'] }}</option>
          {% endfor %}
        </select>
        <label>Amount to invest</label>
        <input type="number" name="amount" min="1" required>
        <button class="btn btn-yellow" type="submit">Invest</button>
      </form>
    </div>
    <h2>Recent Investments</h2>
    <table>
      <tr><th>Date</th><th>Currency</th><th>Staked</th><th>Multiplier</th><th>Payout</th></tr>
      {% for inv in history %}
        <tr>
          <td class="small">{{ inv['created_at'][:19] }}</td>
          <td>{{ inv['currency'] }}</td>
          <td>{{ inv['amount_staked'] }}</td>
          <td>x{{ inv['multiplier'] }}</td>
          <td>{{ inv['payout'] }}</td>
        </tr>
      {% else %}
        <tr><td colspan="5" class="small">No investments yet.</td></tr>
      {% endfor %}
    </table>
    """
    return render_page("Investment", body, currencies=CURRENCIES, history=history,
                        min_m=INVEST_MIN_MULTIPLIER, max_m=INVEST_MAX_MULTIPLIER)


@app.route("/market")
@login_required
def asset_market():
    user = current_user()
    db = get_db()
    # Simulate a fluctuating market: nudge every asset price by a random +/- % each time
    # the market page loads (a simple random-walk, never lower than 1).
    assets = db.execute("SELECT * FROM assets").fetchall()
    for a in assets:
        pct = random.uniform(-ASSET_JITTER_PCT, ASSET_JITTER_PCT)
        new_price = max(1, round(a["current_price"] * (1 + pct)))
        db.execute("UPDATE assets SET current_price=? WHERE id=?", (new_price, a["id"]))
    db.commit()

    holdings = get_asset_holdings(user["id"])
    neo_balance = get_balances(user["id"])["NEO"]
    body = """
    <h1>Asset Market</h1>
    <p class="small">Prices fluctuate randomly every time you open this page. All trades are settled in Neo.
      Your Neo balance: <b>{{ neo_balance }}</b></p>
    <table>
      <tr><th>Asset</th><th>Price (Neo)</th><th>You Own</th><th>Buy</th><th>Sell</th></tr>
      {% for h in holdings %}
        <tr>
          <td>{{ h['name'] }} <span class="small">({{ h['symbol'] }})</span></td>
          <td>{{ h['current_price'] }}</td>
          <td>{{ h['quantity'] }}</td>
          <td>
            <form method="post" action="{{ url_for('market_buy', asset_id=h['id']) }}" style="display:flex;gap:4px">
              <input type="number" name="qty" min="1" value="1" style="width:70px;margin:0">
              <button class="btn" type="submit" style="padding:6px 10px;font-size:12px">Buy</button>
            </form>
          </td>
          <td>
            <form method="post" action="{{ url_for('market_sell', asset_id=h['id']) }}" style="display:flex;gap:4px">
              <input type="number" name="qty" min="1" value="1" style="width:70px;margin:0">
              <button class="btn" type="submit" style="padding:6px 10px;font-size:12px;border-color:var(--danger);color:var(--danger)" {% if h['quantity'] == 0 %}disabled{% endif %}>Sell</button>
            </form>
          </td>
        </tr>
      {% endfor %}
    </table>
    """
    return render_page("Asset Market", body, holdings=holdings, neo_balance=neo_balance)


@app.route("/market/buy/<int:asset_id>", methods=["POST"])
@login_required
def market_buy(asset_id):
    user = current_user()
    db = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not asset:
        abort(404)
    try:
        qty = int(request.form.get("qty", "0"))
    except ValueError:
        qty = 0
    if qty <= 0:
        flash("Enter a valid quantity to buy.", "error")
        return redirect(url_for("asset_market"))

    cost = asset["current_price"] * qty
    bal = get_balances(user["id"])
    if bal["NEO"] < cost:
        flash(f"You need {cost} Neo to buy {qty} x {asset['name']}.", "error")
        return redirect(url_for("asset_market"))

    adjust_balance(user["id"], "NEO", -cost, f"Bought {qty} x {asset['name']}")
    row = db.execute("SELECT quantity FROM asset_holdings WHERE user_id=? AND asset_id=?",
                      (user["id"], asset_id)).fetchone()
    if row:
        db.execute("UPDATE asset_holdings SET quantity=quantity+? WHERE user_id=? AND asset_id=?",
                   (qty, user["id"], asset_id))
    else:
        db.execute("INSERT INTO asset_holdings (user_id, asset_id, quantity) VALUES (?, ?, ?)",
                   (user["id"], asset_id, qty))
    db.commit()
    flash(f"Bought {qty} x {asset['name']} for {cost} Neo.", "success")
    return redirect(url_for("asset_market"))


@app.route("/market/sell/<int:asset_id>", methods=["POST"])
@login_required
def market_sell(asset_id):
    user = current_user()
    db = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not asset:
        abort(404)
    try:
        qty = int(request.form.get("qty", "0"))
    except ValueError:
        qty = 0
    row = db.execute("SELECT quantity FROM asset_holdings WHERE user_id=? AND asset_id=?",
                      (user["id"], asset_id)).fetchone()
    owned = row["quantity"] if row else 0
    if qty <= 0 or qty > owned:
        flash("Enter a valid quantity to sell (you can't sell more than you own).", "error")
        return redirect(url_for("asset_market"))

    proceeds = asset["current_price"] * qty
    db.execute("UPDATE asset_holdings SET quantity=quantity-? WHERE user_id=? AND asset_id=?",
               (qty, user["id"], asset_id))
    adjust_balance(user["id"], "NEO", proceeds, f"Sold {qty} x {asset['name']}")
    db.commit()
    flash(f"Sold {qty} x {asset['name']} for {proceeds} Neo.", "success")
    return redirect(url_for("asset_market"))


"""
================================================================================
SECTION 11: MINIMAL ADMIN PANEL
================================================================================
"""

@app.route("/admin")
@admin_required
def admin_panel():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    games = db.execute("""SELECT g.*, u.display_name AS dev_name FROM games g
                           JOIN users u ON g.developer_id=u.id ORDER BY g.created_at DESC""").fetchall()
    body = """
    <h1>Admin Panel</h1>
    <div class="card">
      <h3>Users ({{ users|length }})</h3>
      <table>
        <tr><th>Username</th><th>Level</th><th>Roles</th><th>Joined</th><th>Action</th></tr>
        {% for u in users %}
        <tr>
          <td>{{ u['username'] }}</td>
          <td>{{ u['level'] }}</td>
          <td>{% if u['is_admin'] %}Admin {% endif %}{% if u['is_developer'] %}Dev{% endif %}</td>
          <td class="small">{{ u['created_at'][:10] }}</td>
          <td>
            <form method="post" action="{{ url_for('admin_toggle_admin', user_id=u['id']) }}" style="display:inline">
              <button class="btn" type="submit" style="padding:4px 10px;font-size:12px">Toggle Admin</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
    <div class="card">
      <h3>Games ({{ games|length }})</h3>
      <table>
        <tr><th>Title</th><th>Dev</th><th>Category</th><th>Plays</th><th>Action</th></tr>
        {% for g in games %}
        <tr>
          <td>{{ g['title'] }}</td>
          <td>{{ g['dev_name'] }}</td>
          <td>{{ g['category'] }}</td>
          <td>{{ g['play_count'] }}</td>
          <td>
            <form method="post" action="{{ url_for('admin_delete_game', game_id=g['id']) }}" style="display:inline">
              <button class="btn" type="submit" style="padding:4px 10px;font-size:12px;border-color:var(--danger);color:var(--danger)">Remove</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_page("Admin", body, users=users, games=games)


@app.route("/admin/users/<int:user_id>/toggle_admin", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    db = get_db()
    u = db.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
    if u:
        db.execute("UPDATE users SET is_admin=? WHERE id=?", (0 if u["is_admin"] else 1, user_id))
        db.commit()
        flash("User updated.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/games/<int:game_id>/delete", methods=["POST"])
@admin_required
def admin_delete_game(game_id):
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if game:
        path = os.path.join(UPLOAD_DIR, game["filename"])
        if os.path.exists(path):
            os.remove(path)
        db.execute("DELETE FROM purchases WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM games WHERE id=?", (game_id,))
        db.commit()
        flash("Game removed.", "success")
    return redirect(url_for("admin_panel"))


"""
================================================================================
SECTION 12: ERROR HANDLERS & STARTUP
================================================================================
"""

@app.errorhandler(403)
def forbidden(e):
    return render_page("Forbidden", "<div class='card'><h2>403 - Forbidden</h2><p>You don't have access to this page.</p></div>"), 403


@app.errorhandler(404)
def not_found(e):
    return render_page("Not Found", "<div class='card'><h2>404 - Not Found</h2><p>That page doesn't exist.</p></div>"), 404


if __name__ == "__main__":
    init_db()
    seed_admin_and_demo()
    seed_assets()
    print("NeoVerse running at http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
