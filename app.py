"""
================================================================================
 NEOVERSE - Cyberpunk Virtual Universe Platform v2.0
================================================================================
Single-file Flask + SQLite application.

FEATURES:
  - Auth (register / login / logout)
  - Social Core: follow / unfollow, friends, user search
  - Chat System: private messaging, online status, unread badges
  - Social Feed: text / image / video posts, likes, comments
  - Infinite Daily Rewards (streak-based formula: 50 + streak * 10 Neo)
  - Game Marketplace with multi-currency pricing
  - Earn Neo by playing games (first 20 plays/day → +10 Neo +5 XP each)
  - Notifications (messages, follows, likes, comments, friend requests, sales)
  - Account Settings & full Reset
  - Wallet & currency conversion
  - Lottery scratch cards
  - Investment system
  - Asset market
  - Admin panel

RUN:
    pip install flask --break-system-packages
    python app.py
    -> http://127.0.0.1:5000
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

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DB_PATH          = os.path.join(BASE_DIR, "neoverse.db")
UPLOAD_DIR       = os.path.join(BASE_DIR, "uploads", "games")
POSTS_UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "posts")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(POSTS_UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("NEOVERSE_SECRET", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB (post media)

CURRENCIES = {
    "NEO":          {"name": "Neo",          "master": True},
    "CYBER_DOLLAR": {"name": "Cyber Dollar", "rate_from_neo": 10},
    "QUANTUM_COIN": {"name": "Quantum Coin", "rate_from_neo": 5},
    "ARC_TOKEN":    {"name": "Arc Token",    "rate_from_neo": 8},
    "NANO_UNIT":    {"name": "Nano Unit",    "rate_from_neo": 20},
}
OTHER_CURRENCIES = [c for c in CURRENCIES if c != "NEO"]

# ── Infinite daily reward ─────────────────────────────────────────────────────
DAILY_BASE_REWARD  = 50
DAILY_STREAK_BONUS = 10
LUCKY_CHANCE       = 0.12
LUCKY_MULTIPLIER   = 3

# ── Game play rewards ─────────────────────────────────────────────────────────
GAME_DAILY_PLAY_LIMIT = 20
GAME_PLAY_NEO_REWARD  = 10
GAME_PLAY_XP_REWARD   = 5

# ── Online status ─────────────────────────────────────────────────────────────
ONLINE_THRESHOLD_MINUTES = 5

# ── File extensions ───────────────────────────────────────────────────────────
ALLOWED_GAME_EXT  = {"html", "htm"}
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_VIDEO_EXT = {"mp4", "webm"}
ALLOWED_POST_EXT  = ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT

GAME_CATEGORIES = [
    "Arcade","Racing","Action","RPG","Puzzle",
    "Adventure","Strategy","Simulation","Educational","Casual",
]

LOTTERY_CARD_COUNT = 16
LOTTERY_CARD_MIN   = -100
LOTTERY_CARD_MAX   = 100
LOTTERY_BATCH_COST = 300

INVEST_MIN_MULTIPLIER = -10.0
INVEST_MAX_MULTIPLIER =  10.0

ASSET_SEED = [
    ("GOLD","Gold",500),("SILVER","Silver",120),("PLATINUM","Platinum",800),
    ("OIL","Crude Oil",60),("URANIUM","Uranium",950),
    ("CYBER_CRYSTAL","Cyber Crystal",300),("NANO_STEEL","Nano Steel",220),
    ("PLASMA_CORE","Plasma Core",650),("QUANTUM_CHIP","Quantum Chip",1200),
    ("NEON_GLASS","Neon Glass",90),("VOID_ORE","Void Ore",430),
    ("STARDUST","Stardust",2000),("BIO_GEL","Bio Gel",75),
    ("CARBON_FIBER","Carbon Fiber",150),("HOLOGRAM_SILK","Hologram Silk",340),
    ("DARK_MATTER","Dark Matter",5000),("ICE_CRYSTAL","Ice Crystal",110),
    ("SOLAR_CELL","Solar Cell",200),
]
ASSET_JITTER_PCT = 0.08

"""
================================================================================
SECTION 2: DATABASE LAYER
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
    PRAGMA foreign_keys = ON;

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
        last_seen TEXT,
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
        price_currency TEXT NOT NULL DEFAULT 'NEO',
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

    -- ── Social core ───────────────────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS followers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower_id INTEGER NOT NULL,
        following_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(follower_id, following_id),
        FOREIGN KEY (follower_id) REFERENCES users(id),
        FOREIGN KEY (following_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS friend_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        responded_at TEXT,
        UNIQUE(sender_id, receiver_id),
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id_a INTEGER NOT NULL,
        user_id_b INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id_a, user_id_b),
        FOREIGN KEY (user_id_a) REFERENCES users(id),
        FOREIGN KEY (user_id_b) REFERENCES users(id)
    );

    -- ── Chat / messaging ──────────────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    );

    -- ── Social feed ───────────────────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        post_type TEXT NOT NULL DEFAULT 'text',
        media_filename TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS post_likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, post_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (post_id) REFERENCES posts(id)
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (post_id) REFERENCES posts(id)
    );

    -- ── Notifications ─────────────────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    -- ── Game play reward tracking ─────────────────────────────────────────────

    CREATE TABLE IF NOT EXISTS game_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        play_date TEXT NOT NULL,
        plays_today INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, game_id, play_date),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (game_id) REFERENCES games(id)
    );

    -- ── Indexes ───────────────────────────────────────────────────────────────

    CREATE INDEX IF NOT EXISTS idx_followers_follower  ON followers(follower_id);
    CREATE INDEX IF NOT EXISTS idx_followers_following ON followers(following_id);
    CREATE INDEX IF NOT EXISTS idx_fr_receiver         ON friend_requests(receiver_id, status);
    CREATE INDEX IF NOT EXISTS idx_fr_sender           ON friend_requests(sender_id, status);
    CREATE INDEX IF NOT EXISTS idx_friends_a           ON friends(user_id_a);
    CREATE INDEX IF NOT EXISTS idx_friends_b           ON friends(user_id_b);
    CREATE INDEX IF NOT EXISTS idx_messages_receiver   ON messages(receiver_id, is_read);
    CREATE INDEX IF NOT EXISTS idx_messages_sender     ON messages(sender_id);
    CREATE INDEX IF NOT EXISTS idx_posts_user          ON posts(user_id);
    CREATE INDEX IF NOT EXISTS idx_posts_created       ON posts(created_at);
    CREATE INDEX IF NOT EXISTS idx_notif_user          ON notifications(user_id, is_read);
    """)
    conn.commit()

    # ── Non-destructive column migrations ─────────────────────────────────────
    migrations = [
        "ALTER TABLE users  ADD COLUMN last_seen TEXT",
        "ALTER TABLE games  ADD COLUMN price_currency TEXT NOT NULL DEFAULT 'NEO'",
    ]
    for stmt in migrations:
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception:
            pass

    conn.close()


def seed_admin_and_demo():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        pw = "admin123"
        conn.execute("""
            INSERT INTO users (username,email,password_hash,display_name,bio,
                               avatar_seed,xp,level,is_admin,is_developer,
                               daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,?,?,?,?,1,1,0,NULL,?)
        """, ("admin","admin@neoverse.local",generate_password_hash(pw),
              "NeoVerse Admin","System administrator account.","admin",
              0,1,datetime.utcnow().isoformat()))
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,'NEO',100000)",(admin_id,))
        for cur in OTHER_CURRENCIES:
            conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,0)",(admin_id,cur))
        conn.commit()
        print("="*60)
        print(" NEOVERSE: admin account created  username:admin  password:admin123")
        print("="*60)

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
  <button onclick="document.getElementById('score').textContent=
    Number(document.getElementById('score').textContent)+1">TAP THE CORE</button>
</body></html>"""
        conn.execute("""
            INSERT INTO games (developer_id,title,description,category,filename,
                               price,price_currency,play_count,created_at)
            VALUES (?,'Neon Clicker','A tiny demo game seeded on first run.',
                    'Casual','demo_neon_clicker.html',0,'NEO',0,?)
        """, (admin_id, datetime.utcnow().isoformat()))
        conn.commit()
        with open(os.path.join(UPLOAD_DIR, "demo_neon_clicker.html"), "w") as f:
            f.write(demo_html)
    conn.close()


def seed_assets():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"] == 0:
        for symbol, name, price in ASSET_SEED:
            conn.execute("INSERT INTO assets (symbol,name,current_price) VALUES (?,?,?)",
                         (symbol, name, price))
        conn.commit()
    conn.close()


def seed_demo_social_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    demo_users = [
        ("nova","nova@neoverse.local","Nova Sek"),
        ("ghostwire","ghostwire@neoverse.local","Ghostwire"),
        ("kira","kira@neoverse.local","Kira Vance"),
    ]
    for username, email, display_name in demo_users:
        if conn.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone():
            continue
        avatar_seed = "".join(random.choices(string.ascii_lowercase+string.digits, k=8))
        conn.execute("""
            INSERT INTO users (username,email,password_hash,display_name,bio,avatar_seed,
                               xp,level,is_admin,is_developer,daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,'',?,0,1,0,0,0,NULL,?)
        """, (username,email,generate_password_hash("password123"),display_name,avatar_seed,
              datetime.utcnow().isoformat()))
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()["id"]
        for cur in CURRENCIES:
            conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,?)",
                         (uid, cur, 200 if cur=="NEO" else 0))
        conn.commit()
    conn.close()


"""
================================================================================
SECTION 3: HELPERS
================================================================================
"""

def current_user():
    if "user_id" not in session:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.","error")
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

# ── Balance / XP ──────────────────────────────────────────────────────────────

def get_balances(user_id):
    rows = get_db().execute("SELECT currency,amount FROM balances WHERE user_id=?",(user_id,)).fetchall()
    bal = {c: 0 for c in CURRENCIES}
    for r in rows:
        bal[r["currency"]] = r["amount"]
    return bal

def adjust_balance(user_id, currency, delta, note=""):
    db = get_db()
    row = db.execute("SELECT amount FROM balances WHERE user_id=? AND currency=?",(user_id,currency)).fetchone()
    if row is None:
        db.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,0)",(user_id,currency))
        current = 0
    else:
        current = row["amount"]
    new_amount = current + delta
    if new_amount < 0:
        raise ValueError("Insufficient balance")
    db.execute("UPDATE balances SET amount=? WHERE user_id=? AND currency=?",(new_amount,user_id,currency))
    db.execute("""INSERT INTO transactions (user_id,type,currency,amount,note,created_at)
                  VALUES (?,?,?,?,?,?)""",
               (user_id,"credit" if delta>=0 else "debit",currency,delta,note,datetime.utcnow().isoformat()))
    db.commit()

def grant_xp(user_id, amount):
    db = get_db()
    u = db.execute("SELECT xp,level FROM users WHERE id=?",(user_id,)).fetchone()
    new_xp    = u["xp"] + amount
    new_level = min(1000, 1 + new_xp // 500)
    leveled_up = new_level > u["level"]
    db.execute("UPDATE users SET xp=?,level=? WHERE id=?",(new_xp,new_level,user_id))
    db.commit()
    if leveled_up:
        adjust_balance(user_id,"NEO",new_level*10,f"Level up bonus (level {new_level})")
    return leveled_up, new_level

# ── Infinite daily reward ─────────────────────────────────────────────────────

def daily_reward_amount(streak):
    """streak is 0-based (0 = first ever claim). Returns Neo to award."""
    return DAILY_BASE_REWARD + streak * DAILY_STREAK_BONUS

def daily_reward_status(user):
    today     = date.today()
    last      = user["last_daily_claim"]
    last_date = date.fromisoformat(last) if last else None
    can_claim = (last_date is None) or (last_date < today)
    streak    = user["daily_streak"]
    if last_date is not None and (today - last_date).days > 1:
        streak = 0          # streak broken by missing a day
    return can_claim, streak

# ── Game play rewards ─────────────────────────────────────────────────────────

def get_game_plays_today(user_id, game_id):
    today = date.today().isoformat()
    row = get_db().execute(
        "SELECT plays_today FROM game_rewards WHERE user_id=? AND game_id=? AND play_date=?",
        (user_id, game_id, today)).fetchone()
    return row["plays_today"] if row else 0

def record_game_play_reward(user_id, game_id):
    """Returns (neo_earned, xp_earned). 0,0 if daily limit reached."""
    today  = date.today().isoformat()
    plays  = get_game_plays_today(user_id, game_id)
    if plays >= GAME_DAILY_PLAY_LIMIT:
        return 0, 0
    db = get_db()
    if plays > 0:
        db.execute("UPDATE game_rewards SET plays_today=plays_today+1 WHERE user_id=? AND game_id=? AND play_date=?",
                   (user_id, game_id, today))
    else:
        db.execute("INSERT INTO game_rewards (user_id,game_id,play_date,plays_today) VALUES (?,?,?,1)",
                   (user_id, game_id, today))
    db.commit()
    adjust_balance(user_id,"NEO",GAME_PLAY_NEO_REWARD,"Game play reward")
    grant_xp(user_id, GAME_PLAY_XP_REWARD)
    return GAME_PLAY_NEO_REWARD, GAME_PLAY_XP_REWARD

# ── Assets ────────────────────────────────────────────────────────────────────

def get_asset_holdings(user_id):
    return get_db().execute("""
        SELECT a.id,a.symbol,a.name,a.current_price,COALESCE(h.quantity,0) AS quantity
        FROM assets a LEFT JOIN asset_holdings h ON h.asset_id=a.id AND h.user_id=?
        ORDER BY a.name
    """, (user_id,)).fetchall()

# ── Social helpers ────────────────────────────────────────────────────────────

def friend_pair(a, b):
    return (a, b) if a < b else (b, a)

def is_following(follower_id, following_id):
    return get_db().execute(
        "SELECT 1 FROM followers WHERE follower_id=? AND following_id=?",
        (follower_id, following_id)).fetchone() is not None

def is_friend(a, b):
    x, y = friend_pair(a, b)
    return get_db().execute(
        "SELECT 1 FROM friends WHERE user_id_a=? AND user_id_b=?",(x,y)).fetchone() is not None

def pending_friend_request(sender_id, receiver_id):
    return get_db().execute(
        "SELECT * FROM friend_requests WHERE sender_id=? AND receiver_id=? AND status='pending'",
        (sender_id, receiver_id)).fetchone()

def follower_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=?",(user_id,)).fetchone()["c"]

def following_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM followers WHERE follower_id=?",(user_id,)).fetchone()["c"]

def friend_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM friends WHERE user_id_a=? OR user_id_b=?",
        (user_id,user_id)).fetchone()["c"]

def social_counts(user_id):
    return {
        "followers": follower_count(user_id),
        "following": following_count(user_id),
        "friends":   friend_count(user_id),
    }

def incoming_friend_request_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM friend_requests WHERE receiver_id=? AND status='pending'",
        (user_id,)).fetchone()["c"]

# ── Online status ─────────────────────────────────────────────────────────────

def is_online(last_seen_str):
    if not last_seen_str:
        return False
    try:
        last = datetime.fromisoformat(last_seen_str)
        return (datetime.utcnow() - last).total_seconds() < ONLINE_THRESHOLD_MINUTES * 60
    except Exception:
        return False

# ── Notifications ─────────────────────────────────────────────────────────────

def create_notification(user_id, notif_type, message, link=None):
    get_db().execute(
        "INSERT INTO notifications (user_id,type,message,link,is_read,created_at) VALUES (?,?,?,?,0,?)",
        (user_id, notif_type, message, link, datetime.utcnow().isoformat()))
    get_db().commit()

def unread_notification_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0",
        (user_id,)).fetchone()["c"]

def unread_message_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM messages WHERE receiver_id=? AND is_read=0",
        (user_id,)).fetchone()["c"]

# ── Update last_seen on every request ─────────────────────────────────────────

@app.before_request
def update_last_seen():
    if "user_id" in session:
        try:
            db = get_db()
            db.execute("UPDATE users SET last_seen=? WHERE id=?",
                       (datetime.utcnow().isoformat(), session["user_id"]))
            db.commit()
        except Exception:
            pass

"""
================================================================================
SECTION 4: CSS & BASE TEMPLATE
================================================================================
"""

BASE_CSS = """
:root{
  --bg-deep:#05060f; --bg-panel:rgba(10,14,32,0.72); --neon:#00e5ff;
  --neon-soft:#00e5ff44; --accent-yellow:#ffe066; --text:#d8f4ff; --text-dim:#7a8aa0;
  --danger:#ff4d6d; --good:#34f5b0; --neon-purple:#b14dff;
  --neon-purple-soft:#b14dff44; --card-shadow:0 0 28px -8px #00e5ff33;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  min-height:100vh; font-family:'Segoe UI',system-ui,sans-serif; color:var(--text);
  background:radial-gradient(circle at 20% 20%,#0d1442 0%,#05060f 45%,#03040a 100%);
  background-attachment:fixed;
}
a{color:var(--neon);text-decoration:none}
a:hover{opacity:.85}

/* ── Nav ── */
.nav{
  display:flex;align-items:center;justify-content:space-between;padding:12px 24px;
  background:rgba(5,6,15,.88);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--neon-soft);position:sticky;top:0;z-index:100;gap:12px;
}
.brand{font-weight:900;font-size:20px;letter-spacing:3px;color:var(--neon);
       text-shadow:0 0 16px var(--neon);white-space:nowrap}
.nav-right{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.nav-right a{color:var(--text);font-size:13px;padding:5px 8px;border-radius:6px;
             white-space:nowrap;transition:.15s}
.nav-right a:hover{background:var(--neon-soft);color:var(--neon)}
.nav-badge{
  display:inline-block;min-width:16px;padding:0 4px;border-radius:10px;
  background:var(--danger);color:#fff;font-size:10px;line-height:16px;
  text-align:center;margin-left:3px;vertical-align:2px;
}
.nav-notif-badge{background:var(--accent-yellow);color:#111}
.nav-toggle{display:none}
.nav-burger{display:none;cursor:pointer;font-size:24px;color:var(--neon);
            border:none;background:none;padding:4px}

/* ── Layout ── */
.wrap{max-width:1020px;margin:0 auto;padding:26px 16px}

/* ── Cards ── */
.card{
  background:var(--bg-panel);border:1px solid var(--neon-soft);border-radius:16px;
  padding:20px;margin-bottom:16px;backdrop-filter:blur(8px);
  box-shadow:var(--card-shadow);
}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
h1{font-size:26px;color:var(--text);text-shadow:0 0 18px var(--neon-soft);margin-bottom:14px}
h2{font-size:20px;color:var(--text);margin-bottom:10px}
h3{font-size:16px;color:var(--text);margin-bottom:8px}

/* ── Buttons ── */
.btn{
  display:inline-block;background:linear-gradient(135deg,#0a1640,#0d2050);
  color:var(--neon);border:1px solid var(--neon);padding:9px 18px;border-radius:9px;
  cursor:pointer;font-weight:600;font-size:13px;letter-spacing:.4px;
  transition:.15s;text-align:center;
}
.btn:hover{box-shadow:0 0 16px var(--neon);transform:translateY(-1px);opacity:1}
.btn-yellow{border-color:var(--accent-yellow);color:var(--accent-yellow)}
.btn-yellow:hover{box-shadow:0 0 16px var(--accent-yellow)}
.btn-purple{border-color:var(--neon-purple);color:var(--neon-purple)}
.btn-purple:hover{box-shadow:0 0 16px var(--neon-purple)}
.btn-danger{border-color:var(--danger);color:var(--danger)}
.btn-danger:hover{box-shadow:0 0 16px var(--danger)}
.btn-good{border-color:var(--good);color:var(--good)}
.btn-good:hover{box-shadow:0 0 16px var(--good)}
.btn-sm{padding:5px 11px;font-size:12px}

/* ── Forms ── */
input,textarea,select{
  width:100%;padding:9px 11px;margin:5px 0 12px;border-radius:8px;
  border:1px solid #1c2a55;background:#070b1d;color:var(--text);font-size:14px;
}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--neon)}
label{font-size:13px;color:var(--text-dim)}

/* ── Flash messages ── */
.flash{padding:9px 13px;border-radius:8px;margin-bottom:12px;font-size:13px}
.flash-error{background:#3a0f1a;border:1px solid var(--danger);color:#ffb3c1}
.flash-success{background:#0d2e23;border:1px solid var(--good);color:#bdfde6}

/* ── Badges ── */
.badge{display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;
       border:1px solid var(--neon-soft)}
.badge-purple{border-color:var(--neon-purple-soft);color:var(--neon-purple)}
.badge-good{border-color:var(--good);color:var(--good)}
.badge-yellow{border-color:var(--accent-yellow);color:var(--accent-yellow)}

/* ── Wallet ── */
.currency-row{display:flex;justify-content:space-between;padding:7px 0;
              border-bottom:1px solid #14204a}
.currency-row:last-child{border-bottom:none}

/* ── Daily reward ── */
.reward-progress{
  background:#0a0f2a;border:1px solid var(--neon-soft);border-radius:12px;
  padding:16px;margin:12px 0;
}
.reward-bar-wrap{background:#0d1030;border-radius:20px;height:8px;margin:8px 0}
.reward-bar{background:linear-gradient(90deg,var(--neon),var(--neon-purple));
             border-radius:20px;height:8px;transition:.4s}

/* ── Game ── */
.game-card{display:flex;flex-direction:column;gap:8px}
.game-iframe-wrap{border:1px solid var(--neon-soft);border-radius:12px;overflow:hidden;height:520px}
.game-iframe-wrap iframe{width:100%;height:100%;border:none}

/* ── Tables ── */
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #14204a}
th{color:var(--text-dim);font-weight:600}

/* ── Scratch cards ── */
.reward-grid{display:grid;gap:8px;grid-template-columns:repeat(4,1fr);margin:14px 0}
.reward-slot{
  aspect-ratio:1;border-radius:10px;border:1px solid var(--neon-soft);display:flex;
  align-items:center;justify-content:center;font-size:12px;text-align:center;padding:4px;
}
.reward-slot.done{background:#0d2050;color:var(--neon)}
.reward-slot.next{background:#1a0f3a;border-color:var(--accent-yellow);
                  color:var(--accent-yellow);box-shadow:0 0 12px var(--accent-yellow)}
.reward-slot.future{color:var(--text-dim)}
.reward-slot.penalty{border-color:var(--danger)}

/* ── Profile ── */
.profile-header{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.avatar-circle{
  width:64px;height:64px;border-radius:50%;
  background:linear-gradient(135deg,var(--neon),var(--neon-purple));
  display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:22px;color:#05060f;
  box-shadow:0 0 18px var(--neon-soft);flex-shrink:0;position:relative;
}
.avatar-mini{
  width:36px;height:36px;border-radius:50%;
  background:linear-gradient(135deg,var(--neon),var(--neon-purple));
  display:flex;align-items:center;justify-content:center;
  font-weight:700;font-size:14px;color:#05060f;flex-shrink:0;position:relative;
}
.avatar-lg{
  width:52px;height:52px;border-radius:50%;
  background:linear-gradient(135deg,var(--neon),var(--neon-purple));
  display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:19px;color:#05060f;flex-shrink:0;position:relative;
}
.online-dot{
  width:11px;height:11px;border-radius:50%;background:var(--good);
  border:2px solid var(--bg-deep);position:absolute;bottom:1px;right:1px;
}
.stat-row{display:flex;gap:20px;flex-wrap:wrap;margin:10px 0}
.stat-block{text-align:center}
.stat-block b{display:block;font-size:19px;color:var(--neon)}
.stat-block span{font-size:11px;color:var(--text-dim)}

/* ── User list ── */
.user-list-item{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:10px 0;border-bottom:1px solid #14204a;flex-wrap:wrap;
}
.user-list-item:last-child{border-bottom:none}
.user-mini{display:flex;align-items:center;gap:10px}
.action-row{display:flex;gap:6px;flex-wrap:wrap}
.tabs{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
.tab-link{padding:7px 14px;border-radius:20px;border:1px solid var(--neon-soft);font-size:12px}
.tab-link.active{background:var(--neon);color:#05060f;font-weight:700}

/* ── Chat ── */
.chat-layout{display:grid;grid-template-columns:260px 1fr;gap:14px;min-height:500px}
.chat-sidebar{display:flex;flex-direction:column;gap:0}
.chat-contact{
  display:flex;align-items:center;gap:10px;padding:10px 12px;
  border-bottom:1px solid #14204a;cursor:pointer;transition:.15s;
  text-decoration:none;color:var(--text);
}
.chat-contact:hover,.chat-contact.active{background:var(--neon-soft)}
.chat-contact-info{flex:1;min-width:0}
.chat-contact-info b{display:block;font-size:13px;white-space:nowrap;
                      overflow:hidden;text-overflow:ellipsis}
.chat-contact-info span{font-size:11px;color:var(--text-dim);white-space:nowrap;
                         overflow:hidden;text-overflow:ellipsis;display:block}
.chat-unread-dot{min-width:18px;height:18px;border-radius:9px;background:var(--neon);
                  color:#05060f;font-size:10px;font-weight:700;display:flex;
                  align-items:center;justify-content:center;padding:0 4px}
.chat-messages{
  display:flex;flex-direction:column;gap:10px;padding:16px;
  height:420px;overflow-y:auto;background:#060810;border-radius:10px;
  border:1px solid var(--neon-soft);
}
.chat-bubble{
  max-width:70%;padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.5;
  word-break:break-word;
}
.chat-bubble.mine{
  background:linear-gradient(135deg,#082060,#0a1840);border:1px solid var(--neon-soft);
  margin-left:auto;border-bottom-right-radius:4px;
}
.chat-bubble.theirs{
  background:#0d1028;border:1px solid #1c2a55;
  border-bottom-left-radius:4px;
}
.chat-bubble .ts{font-size:10px;color:var(--text-dim);margin-top:4px}
.chat-bubble.mine .ts{text-align:right}
.chat-input-row{display:flex;gap:8px;margin-top:10px}
.chat-input-row input{margin:0;flex:1}
.read-tick{color:var(--neon);font-size:11px;margin-left:4px}

/* ── Feed / Posts ── */
.post-card{margin-bottom:14px}
.post-header{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.post-meta{flex:1}
.post-meta b{font-size:14px}
.post-meta span{font-size:11px;color:var(--text-dim)}
.post-content{font-size:14px;line-height:1.6;margin-bottom:10px;white-space:pre-wrap;word-break:break-word}
.post-media{margin-bottom:10px}
.post-media img{max-width:100%;max-height:400px;border-radius:10px;object-fit:cover}
.post-media video{max-width:100%;max-height:400px;border-radius:10px}
.post-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
              padding-top:8px;border-top:1px solid #14204a}
.post-actions form{display:inline}
.like-count{color:var(--text-dim);font-size:13px}
.comments-section{margin-top:10px;border-top:1px solid #14204a;padding-top:10px}
.comment{display:flex;gap:8px;margin-bottom:8px;align-items:flex-start}
.comment-body{flex:1}
.comment-body b{font-size:13px}
.comment-body p{font-size:13px;color:var(--text);margin:2px 0;white-space:pre-wrap;word-break:break-word}
.comment-body span{font-size:10px;color:var(--text-dim)}

/* ── Notifications ── */
.notif-item{
  display:flex;align-items:flex-start;gap:10px;padding:10px 0;
  border-bottom:1px solid #14204a;
}
.notif-item:last-child{border-bottom:none}
.notif-item.unread{background:rgba(0,229,255,.04);margin:0 -20px;padding:10px 20px}
.notif-icon{
  width:34px;height:34px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:16px;flex-shrink:0;
  background:var(--neon-soft);
}
.notif-body{flex:1}
.notif-body p{font-size:13px;margin-bottom:2px}
.notif-body span{font-size:11px;color:var(--text-dim)}
.notif-unread-dot{width:8px;height:8px;border-radius:50%;background:var(--neon);
                   flex-shrink:0;margin-top:6px}

/* ── Leaderboard ── */
.lb-row{display:flex;align-items:center;gap:10px;padding:8px 0;
        border-bottom:1px solid #14204a}
.lb-row:last-child{border-bottom:none}
.lb-rank{font-size:16px;font-weight:800;color:var(--accent-yellow);
          width:28px;text-align:center;flex-shrink:0}

/* ── Settings ── */
.settings-section{margin-bottom:18px;padding-bottom:18px;border-bottom:1px solid #14204a}
.settings-section:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}

/* ── Misc ── */
.small{color:var(--text-dim);font-size:12px}
.text-danger{color:var(--danger)}
.text-good{color:var(--good)}
.text-yellow{color:var(--accent-yellow)}
.flex{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.responsive-row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap}
.responsive-row>div{flex:1;min-width:140px}
.divider{border:none;border-top:1px solid #14204a;margin:14px 0}

/* ── Mobile nav ── */
@media(max-width:768px){
  .nav{flex-wrap:wrap;padding:10px 14px}
  .nav-burger{display:block}
  .nav-right{
    display:none;flex-direction:column;align-items:stretch;
    width:100%;margin-top:8px;
  }
  .nav-toggle:checked~.nav-right{display:flex}
  .nav-right a{padding:9px 4px;border-bottom:1px solid #14204a;font-size:14px}
  .chat-layout{grid-template-columns:1fr}
  .chat-sidebar{max-height:200px;overflow-y:auto}
}
@media(max-width:600px){
  .wrap{padding:14px 10px}
  h1{font-size:20px}
  .card{padding:14px;border-radius:12px}
  .grid{grid-template-columns:1fr}
  .reward-grid{grid-template-columns:repeat(3,1fr)}
  .game-iframe-wrap{height:360px}
  table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
  input,textarea,select{font-size:16px}
  .btn{width:100%;text-align:center}
  .action-row form,.action-row .btn{width:100%}
  .user-list-item{flex-direction:column;align-items:flex-start}
}
@media(max-width:400px){.reward-grid{grid-template-columns:repeat(2,1fr)}}
"""

NAV_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title }} · NeoVerse</title>
  <style>{{ css|safe }}</style>
</head>
<body>
<div class="nav">
  <a href="{{ url_for('index') }}" class="brand">⬡ NEOVERSE</a>
  <input type="checkbox" id="nav-toggle" class="nav-toggle">
  <label for="nav-toggle" class="nav-burger">&#9776;</label>
  <div class="nav-right">
    {% if user %}
      <a href="{{ url_for('index') }}">Dashboard</a>
      <a href="{{ url_for('feed') }}">Feed</a>
      <a href="{{ url_for('games_list') }}">Games</a>
      <a href="{{ url_for('wallet') }}">Wallet</a>
      <a href="{{ url_for('daily_reward') }}">Daily</a>
      <a href="{{ url_for('lottery') }}">Lottery</a>
      <a href="{{ url_for('investment') }}">Invest</a>
      <a href="{{ url_for('asset_market') }}">Market</a>
      <a href="{{ url_for('user_search') }}">Find</a>
      <a href="{{ url_for('friend_requests_page') }}">Requests
        {% if pending_req_count and pending_req_count>0 %}
          <span class="nav-badge">{{ pending_req_count }}</span>
        {% endif %}
      </a>
      <a href="{{ url_for('messages_list') }}">💬
        {% if unread_msg_count and unread_msg_count>0 %}
          <span class="nav-badge">{{ unread_msg_count }}</span>
        {% endif %}
      </a>
      <a href="{{ url_for('notifications_page') }}">🔔
        {% if unread_notif_count and unread_notif_count>0 %}
          <span class="nav-badge nav-notif-badge">{{ unread_notif_count }}</span>
        {% endif %}
      </a>
      <a href="{{ url_for('profile', username=user['username']) }}">{{ user['display_name'] }}</a>
      <a href="{{ url_for('settings_page') }}">⚙</a>
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
    u = current_user()
    prc  = incoming_friend_request_count(u["id"]) if u else 0
    umc  = unread_message_count(u["id"])           if u else 0
    unc  = unread_notification_count(u["id"])       if u else 0
    body = render_template_string(body_html, user=u,
                                  pending_req_count=prc,
                                  unread_msg_count=umc,
                                  unread_notif_count=unc, **extra)
    return render_template_string(NAV_TEMPLATE, title=title, css=BASE_CSS,
                                  body=body, user=u,
                                  pending_req_count=prc,
                                  unread_msg_count=umc,
                                  unread_notif_count=unc)

@app.template_filter("initial")
def initial_filter(name):
    return (name or "?")[:1].upper()

"""
================================================================================
SECTION 5: AUTH ROUTES
================================================================================
"""

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username     = request.form.get("username","").strip().lower()
        email        = request.form.get("email","").strip().lower()
        password     = request.form.get("password","")
        display_name = request.form.get("display_name","").strip() or username

        if not (3 <= len(username) <= 20) or not username.isalnum():
            flash("Username must be 3-20 alphanumeric characters.","error")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.","error")
            return redirect(url_for("register"))

        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username=? OR email=?",(username,email)).fetchone():
            flash("Username or email already in use.","error")
            return redirect(url_for("register"))

        avatar_seed = "".join(random.choices(string.ascii_lowercase+string.digits, k=8))
        db.execute("""
            INSERT INTO users (username,email,password_hash,display_name,bio,avatar_seed,
                               xp,level,is_admin,is_developer,daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,?,?  ,0,1,0,0,0,NULL,?)
        """, (username,email,generate_password_hash(password),display_name,"",avatar_seed,
              datetime.utcnow().isoformat()))
        db.commit()
        uid = db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()["id"]
        for cur in CURRENCIES:
            db.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,?)",
                       (uid, cur, 200 if cur=="NEO" else 0))
        db.commit()
        session["user_id"] = uid
        flash("Welcome to NeoVerse! You received 200 Neo to get started.","success")
        return redirect(url_for("index"))

    body = """
    <div class="card" style="max-width:400px;margin:40px auto">
      <h2>Create Account</h2>
      <form method="post">
        <label>Username</label><input name="username" required>
        <label>Display Name</label><input name="display_name">
        <label>Email</label><input type="email" name="email" required>
        <label>Password</label><input type="password" name="password" required>
        <button class="btn btn-yellow" type="submit" style="margin-top:4px">Register</button>
      </form>
      <p class="small" style="margin-top:10px">Already have an account? <a href="{{ url_for('login') }}">Log in</a></p>
    </div>"""
    return render_page("Register", body)


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip().lower()
        password = request.form.get("password","")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['display_name']}.","success")
            return redirect(url_for("index"))
        flash("Invalid username or password.","error")
        return redirect(url_for("login"))

    body = """
    <div class="card" style="max-width:400px;margin:40px auto">
      <h2>Log In</h2>
      <form method="post">
        <label>Username</label><input name="username" required>
        <label>Password</label><input type="password" name="password" required>
        <button class="btn btn-yellow" type="submit" style="margin-top:4px">Log In</button>
      </form>
      <p class="small" style="margin-top:10px">New here? <a href="{{ url_for('register') }}">Create account</a></p>
    </div>"""
    return render_page("Login", body)


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.","success")
    return redirect(url_for("login"))


"""
================================================================================
SECTION 6: DASHBOARD (homepage upgrade)
================================================================================
"""

@app.route("/")
@login_required
def index():
    user = current_user()
    bal  = get_balances(user["id"])
    can_claim, streak = daily_reward_status(user)
    next_reward = daily_reward_amount(streak)
    db = get_db()

    # Trending games (top play_count)
    trending_games = db.execute("""
        SELECT g.*,u.display_name AS dev_name FROM games g
        JOIN users u ON g.developer_id=u.id
        ORDER BY g.play_count DESC LIMIT 4
    """).fetchall()

    # Latest posts
    latest_posts = db.execute("""
        SELECT p.*,u.username,u.display_name,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comment_count
        FROM posts p JOIN users u ON u.id=p.user_id
        ORDER BY p.created_at DESC LIMIT 4
    """).fetchall()

    # Richest players (NEO balance)
    richest = db.execute("""
        SELECT u.username,u.display_name,b.amount FROM balances b
        JOIN users u ON u.id=b.user_id
        WHERE b.currency='NEO' ORDER BY b.amount DESC LIMIT 5
    """).fetchall()

    # Top levels
    top_levels = db.execute("""
        SELECT username,display_name,level,xp FROM users ORDER BY level DESC,xp DESC LIMIT 5
    """).fetchall()

    counts        = social_counts(user["id"])
    unread_msgs   = unread_message_count(user["id"])
    unread_notifs = unread_notification_count(user["id"])

    body = """
    <h1>Welcome back, {{ user['display_name'] }} ⚡</h1>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      <div class="card">
        <h3>Level {{ user['level'] }}</h3>
        <p style="font-size:13px;color:var(--text-dim);margin:4px 0">{{ user['xp'] }} XP total</p>
        <span class="badge badge-yellow">{{ bal['NEO'] }} Neo</span>
      </div>
      <div class="card">
        <h3>Daily Reward</h3>
        <p style="font-size:13px;margin:4px 0">Streak: <b style="color:var(--neon)">{{ streak }}</b> days</p>
        <p class="small">Next: +{{ next_reward }} Neo</p>
        {% if can_claim %}
          <a class="btn btn-yellow" style="margin-top:8px" href="{{ url_for('daily_reward') }}">Claim Now ✦</a>
        {% else %}
          <p class="small" style="margin-top:6px">Claimed today ✓</p>
        {% endif %}
      </div>
      <div class="card">
        <h3>Network</h3>
        <p style="font-size:13px;margin:4px 0">
          <b style="color:var(--neon)">{{ counts['friends'] }}</b> friends &middot;
          <b style="color:var(--neon)">{{ counts['followers'] }}</b> followers
        </p>
        <a class="btn btn-sm" style="margin-top:8px" href="{{ url_for('user_search') }}">Find People</a>
      </div>
      <div class="card">
        <h3>Inbox</h3>
        {% if unread_msgs > 0 %}
          <p><span class="badge" style="border-color:var(--neon)">{{ unread_msgs }} unread message{{ 's' if unread_msgs!=1 }}</span></p>
        {% else %}
          <p class="small">No new messages</p>
        {% endif %}
        {% if unread_notifs > 0 %}
          <p style="margin-top:4px"><span class="badge badge-yellow">{{ unread_notifs }} notification{{ 's' if unread_notifs!=1 }}</span></p>
        {% endif %}
        <a class="btn btn-sm" style="margin-top:8px" href="{{ url_for('messages_list') }}">Open Messages</a>
      </div>
    </div>

    <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:4px">
      <div>
        <h2>🔥 Trending Games</h2>
        {% for game in trending_games %}
          <div class="card" style="padding:14px;margin-bottom:10px">
            <div class="flex" style="justify-content:space-between">
              <b>{{ game['title'] }}</b>
              <span class="small">{{ game['play_count'] }} plays</span>
            </div>
            <p class="small" style="margin:4px 0">{{ game['category'] }} · {{ game['dev_name'] }}</p>
            <a class="btn btn-sm" style="margin-top:6px" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
          </div>
        {% else %}
          <p class="small">No games yet.</p>
        {% endfor %}
        <a href="{{ url_for('games_list') }}" class="small">View all games →</a>
      </div>

      <div>
        <h2>👑 Leaderboards</h2>
        <div class="card" style="margin-bottom:10px">
          <h3 style="margin-bottom:8px">Richest Players</h3>
          {% for r in richest %}
            <div class="lb-row">
              <span class="lb-rank">#{{ loop.index }}</span>
              <a href="{{ url_for('profile', username=r['username']) }}" style="font-size:13px">{{ r['display_name'] }}</a>
              <span class="badge badge-yellow" style="margin-left:auto">{{ r['amount'] }} Neo</span>
            </div>
          {% endfor %}
        </div>
        <div class="card">
          <h3 style="margin-bottom:8px">Highest Level</h3>
          {% for r in top_levels %}
            <div class="lb-row">
              <span class="lb-rank">#{{ loop.index }}</span>
              <a href="{{ url_for('profile', username=r['username']) }}" style="font-size:13px">{{ r['display_name'] }}</a>
              <span class="badge" style="margin-left:auto">Lv {{ r['level'] }}</span>
            </div>
          {% endfor %}
        </div>
      </div>
    </div>

    <h2 style="margin-top:10px">📰 Latest Posts</h2>
    {% for post in latest_posts %}
      <div class="card post-card">
        <div class="post-header">
          <div class="avatar-mini"><span>{{ post['display_name']|initial }}</span></div>
          <div class="post-meta">
            <b><a href="{{ url_for('profile', username=post['username']) }}">{{ post['display_name'] }}</a></b>
            <span>{{ post['created_at'][:16].replace('T',' ') }}</span>
          </div>
        </div>
        {% if post['content'] %}
          <p class="post-content">{{ post['content'][:200] }}{% if post['content']|length > 200 %}…{% endif %}</p>
        {% endif %}
        <div class="flex">
          <span class="small">❤ {{ post['like_count'] }} &nbsp; 💬 {{ post['comment_count'] }}</span>
          <a class="btn btn-sm" href="{{ url_for('view_post', post_id=post['id']) }}">View</a>
        </div>
      </div>
    {% else %}
      <p class="small">No posts yet. <a href="{{ url_for('feed') }}">Go to feed →</a></p>
    {% endfor %}
    """
    return render_page("Dashboard", body,
                       bal=bal, can_claim=can_claim, streak=streak, next_reward=next_reward,
                       trending_games=trending_games, latest_posts=latest_posts,
                       richest=richest, top_levels=top_levels, counts=counts,
                       unread_msgs=unread_msgs, unread_notifs=unread_notifs)


"""
================================================================================
SECTION 7: PROFILE & SOCIAL
================================================================================
"""

@app.route("/profile/<username>")
@login_required
def profile(username):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target:
        abort(404)
    me      = current_user()
    is_self = me["username"] == username

    counts          = social_counts(target["id"])
    following_them  = is_following(me["id"], target["id"])
    they_follow_me  = is_following(target["id"], me["id"])
    are_friends     = is_friend(me["id"], target["id"])
    outgoing_req    = pending_friend_request(me["id"], target["id"])
    incoming_req    = pending_friend_request(target["id"], me["id"])
    online          = is_online(target["last_seen"])

    user_posts = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id) AS comment_count
        FROM posts p WHERE p.user_id=? ORDER BY p.created_at DESC LIMIT 10
    """, (target["id"],)).fetchall()

    body = """
    <div class="card">
      <div class="profile-header">
        <div class="avatar-circle">
          {{ target['display_name']|initial }}
          {% if online %}<div class="online-dot"></div>{% endif %}
        </div>
        <div style="flex:1">
          <h1 style="margin-bottom:4px">
            {{ target['display_name'] }}
            <span class="small">@{{ target['username'] }}</span>
          </h1>
          <p style="font-size:13px;color:var(--text-dim)">{{ target['bio'] or 'No bio yet.' }}</p>
          <p style="margin-top:6px">
            <span class="badge">Level {{ target['level'] }}</span>
            <span class="badge">{{ target['xp'] }} XP</span>
            {% if target['is_developer'] %}<span class="badge badge-purple">Dev</span>{% endif %}
            {% if target['is_admin'] %}<span class="badge badge-purple">Admin</span>{% endif %}
            {% if not is_self and are_friends %}<span class="badge badge-good">Friends</span>{% endif %}
            {% if not is_self and they_follow_me %}<span class="badge">Follows you</span>{% endif %}
            {% if online %}<span class="badge badge-good">● Online</span>{% endif %}
          </p>
        </div>
      </div>

      <div class="stat-row" style="margin-top:12px">
        <div class="stat-block"><b>{{ counts['friends'] }}</b><span>Friends</span></div>
        <a href="{{ url_for('followers_list', username=target['username']) }}" style="text-decoration:none">
          <div class="stat-block"><b>{{ counts['followers'] }}</b><span>Followers</span></div>
        </a>
        <a href="{{ url_for('following_list', username=target['username']) }}" style="text-decoration:none">
          <div class="stat-block"><b>{{ counts['following'] }}</b><span>Following</span></div>
        </a>
        <div class="stat-block"><b>{{ user_posts|length }}</b><span>Posts</span></div>
      </div>

      {% if not is_self %}
      <div class="action-row" style="margin-top:12px">
        {% if following_them %}
          <form method="post" action="{{ url_for('unfollow_user', username=target['username']) }}">
            <button class="btn btn-sm" type="submit">Unfollow</button>
          </form>
        {% else %}
          <form method="post" action="{{ url_for('follow_user', username=target['username']) }}">
            <button class="btn btn-yellow btn-sm" type="submit">Follow</button>
          </form>
        {% endif %}

        {% if are_friends %}
          <form method="post" action="{{ url_for('remove_friend', username=target['username']) }}">
            <button class="btn btn-danger btn-sm" type="submit">Remove Friend</button>
          </form>
        {% elif outgoing_req %}
          <span class="btn btn-sm" style="opacity:.6;cursor:default">Request Sent</span>
          <form method="post" action="{{ url_for('cancel_friend_request', username=target['username']) }}">
            <button class="btn btn-danger btn-sm" type="submit">Cancel</button>
          </form>
        {% elif incoming_req %}
          <form method="post" action="{{ url_for('respond_friend_request', request_id=incoming_req['id'], action='accept') }}">
            <button class="btn btn-yellow btn-sm" type="submit">Accept Friend Request</button>
          </form>
          <form method="post" action="{{ url_for('respond_friend_request', request_id=incoming_req['id'], action='reject') }}">
            <button class="btn btn-danger btn-sm" type="submit">Reject</button>
          </form>
        {% else %}
          <form method="post" action="{{ url_for('send_friend_request', username=target['username']) }}">
            <button class="btn btn-purple btn-sm" type="submit">Add Friend</button>
          </form>
        {% endif %}

        <a class="btn btn-sm" href="{{ url_for('chat_page', user_id=target['id']) }}">💬 Message</a>
      </div>
      {% endif %}
    </div>

    {% if is_self %}
    <div class="card">
      <h3>Edit Profile</h3>
      <form method="post" action="{{ url_for('edit_profile') }}">
        <label>Display Name</label>
        <input name="display_name" value="{{ target['display_name'] }}">
        <label>Bio</label>
        <textarea name="bio" rows="3">{{ target['bio'] }}</textarea>
        <button class="btn" type="submit">Save</button>
      </form>
    </div>
    {% endif %}

    <h2>Posts</h2>
    {% for post in user_posts %}
      <div class="card post-card">
        {% if post['content'] %}
          <p class="post-content">{{ post['content'][:300] }}{% if post['content']|length>300 %}…{% endif %}</p>
        {% endif %}
        {% if post['media_filename'] %}
          <div class="post-media">
            {% if post['post_type']=='image' %}
              <img src="{{ url_for('serve_post_media', filename=post['media_filename']) }}" alt="">
            {% elif post['post_type']=='video' %}
              <video controls><source src="{{ url_for('serve_post_media', filename=post['media_filename']) }}"></video>
            {% endif %}
          </div>
        {% endif %}
        <div class="flex">
          <span class="small">❤ {{ post['like_count'] }} &nbsp; 💬 {{ post['comment_count'] }}</span>
          <span class="small">{{ post['created_at'][:16].replace('T',' ') }}</span>
          <a class="btn btn-sm" href="{{ url_for('view_post', post_id=post['id']) }}">View</a>
        </div>
      </div>
    {% else %}
      <p class="small">No posts yet.</p>
    {% endfor %}
    """
    return render_page(target["display_name"], body,
                       target=target, is_self=is_self, counts=counts,
                       following_them=following_them, they_follow_me=they_follow_me,
                       are_friends=are_friends, outgoing_req=outgoing_req,
                       incoming_req=incoming_req, online=online,
                       user_posts=user_posts)


@app.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile():
    user = current_user()
    db   = get_db()
    db.execute("UPDATE users SET display_name=?,bio=? WHERE id=?",
               (request.form.get("display_name",user["display_name"]).strip()[:40],
                request.form.get("bio","").strip()[:300],
                user["id"]))
    db.commit()
    flash("Profile updated.","success")
    return redirect(url_for("profile", username=user["username"]))


@app.route("/users/search")
@login_required
def user_search():
    q  = request.args.get("q","").strip()
    me = current_user()
    db = get_db()
    results = []
    if q:
        results = db.execute("""
            SELECT * FROM users
            WHERE (username LIKE ? OR display_name LIKE ?) AND id!=?
            ORDER BY username LIMIT 30
        """, (f"%{q}%",f"%{q}%",me["id"])).fetchall()

    body = """
    <h1>Find People</h1>
    <div class="card">
      <form method="get">
        <label>Search by username or display name</label>
        <input name="q" value="{{ q }}" placeholder="e.g. nova, ghostwire…">
        <button class="btn" type="submit">Search</button>
      </form>
    </div>
    {% if q %}
      <div class="card">
        <h3>Results for "{{ q }}"</h3>
        {% for r in results %}
          <div class="user-list-item">
            <div class="user-mini">
              <div class="avatar-mini">
                {{ r['display_name']|initial }}
                {% if is_online_fn(r['last_seen']) %}<div class="online-dot"></div>{% endif %}
              </div>
              <div>
                <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
                <div class="small">@{{ r['username'] }} · Level {{ r['level'] }}</div>
              </div>
            </div>
            <div class="action-row">
              <a class="btn btn-sm" href="{{ url_for('profile', username=r['username']) }}">Profile</a>
              <a class="btn btn-sm" href="{{ url_for('chat_page', user_id=r['id']) }}">💬 Message</a>
            </div>
          </div>
        {% else %}
          <p class="small">No users found matching "{{ q }}".</p>
        {% endfor %}
      </div>
    {% endif %}
    """
    return render_page("Find People", body, q=q, results=results, is_online_fn=is_online)


@app.route("/profile/<username>/followers")
@login_required
def followers_list(username):
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    rows = db.execute("""
        SELECT u.* FROM followers f JOIN users u ON u.id=f.follower_id
        WHERE f.following_id=? ORDER BY f.created_at DESC
    """,(target["id"],)).fetchall()
    body = """
    <h1>{{ target['display_name'] }}'s Followers</h1>
    <div class="tabs">
      <a class="tab-link active" href="{{ url_for('followers_list', username=target['username']) }}">Followers</a>
      <a class="tab-link" href="{{ url_for('following_list', username=target['username']) }}">Following</a>
      <a class="tab-link" href="{{ url_for('profile', username=target['username']) }}">← Profile</a>
    </div>
    <div class="card">
      {% for r in rows %}
        <div class="user-list-item">
          <div class="user-mini">
            <div class="avatar-mini">{{ r['display_name']|initial }}</div>
            <div>
              <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
              <div class="small">@{{ r['username'] }}</div>
            </div>
          </div>
          <a class="btn btn-sm" href="{{ url_for('profile', username=r['username']) }}">View</a>
        </div>
      {% else %}<p class="small">No followers yet.</p>{% endfor %}
    </div>"""
    return render_page(f"{target['display_name']} · Followers", body, target=target, rows=rows)


@app.route("/profile/<username>/following")
@login_required
def following_list(username):
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    rows = db.execute("""
        SELECT u.* FROM followers f JOIN users u ON u.id=f.following_id
        WHERE f.follower_id=? ORDER BY f.created_at DESC
    """,(target["id"],)).fetchall()
    body = """
    <h1>{{ target['display_name'] }} is Following</h1>
    <div class="tabs">
      <a class="tab-link" href="{{ url_for('followers_list', username=target['username']) }}">Followers</a>
      <a class="tab-link active" href="{{ url_for('following_list', username=target['username']) }}">Following</a>
      <a class="tab-link" href="{{ url_for('profile', username=target['username']) }}">← Profile</a>
    </div>
    <div class="card">
      {% for r in rows %}
        <div class="user-list-item">
          <div class="user-mini">
            <div class="avatar-mini">{{ r['display_name']|initial }}</div>
            <div>
              <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
              <div class="small">@{{ r['username'] }}</div>
            </div>
          </div>
          <a class="btn btn-sm" href="{{ url_for('profile', username=r['username']) }}">View</a>
        </div>
      {% else %}<p class="small">Not following anyone yet.</p>{% endfor %}
    </div>"""
    return render_page(f"{target['display_name']} · Following", body, target=target, rows=rows)


@app.route("/friends")
@login_required
def friends_list():
    me = current_user()
    db = get_db()
    rows = db.execute("""
        SELECT u.* FROM friends f
        JOIN users u ON u.id=(CASE WHEN f.user_id_a=? THEN f.user_id_b ELSE f.user_id_a END)
        WHERE f.user_id_a=? OR f.user_id_b=?
        ORDER BY f.created_at DESC
    """,(me["id"],me["id"],me["id"])).fetchall()
    body = """
    <h1>Your Friends</h1>
    <div class="card">
      {% for r in rows %}
        <div class="user-list-item">
          <div class="user-mini">
            <div class="avatar-mini">{{ r['display_name']|initial }}</div>
            <div>
              <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
              <div class="small">@{{ r['username'] }}</div>
            </div>
          </div>
          <div class="action-row">
            <a class="btn btn-sm" href="{{ url_for('chat_page', user_id=r['id']) }}">💬</a>
            <a class="btn btn-sm" href="{{ url_for('profile', username=r['username']) }}">View</a>
            <form method="post" action="{{ url_for('remove_friend', username=r['username']) }}">
              <button class="btn btn-danger btn-sm" type="submit">Remove</button>
            </form>
          </div>
        </div>
      {% else %}
        <p class="small">No friends yet. <a href="{{ url_for('user_search') }}">Find people to add</a>.</p>
      {% endfor %}
    </div>"""
    return render_page("Friends", body, rows=rows)


@app.route("/friends/requests")
@login_required
def friend_requests_page():
    me = current_user()
    db = get_db()
    incoming = db.execute("""
        SELECT fr.*,u.username,u.display_name FROM friend_requests fr
        JOIN users u ON u.id=fr.sender_id
        WHERE fr.receiver_id=? AND fr.status='pending' ORDER BY fr.created_at DESC
    """,(me["id"],)).fetchall()
    outgoing = db.execute("""
        SELECT fr.*,u.username,u.display_name FROM friend_requests fr
        JOIN users u ON u.id=fr.receiver_id
        WHERE fr.sender_id=? AND fr.status='pending' ORDER BY fr.created_at DESC
    """,(me["id"],)).fetchall()
    body = """
    <h1>Friend Requests</h1>
    <div class="card">
      <h3>Incoming ({{ incoming|length }})</h3>
      {% for r in incoming %}
        <div class="user-list-item">
          <div class="user-mini">
            <div class="avatar-mini">{{ r['display_name']|initial }}</div>
            <div>
              <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
              <div class="small">@{{ r['username'] }} · {{ r['created_at'][:10] }}</div>
            </div>
          </div>
          <div class="action-row">
            <form method="post" action="{{ url_for('respond_friend_request', request_id=r['id'], action='accept') }}">
              <button class="btn btn-yellow btn-sm" type="submit">Accept</button>
            </form>
            <form method="post" action="{{ url_for('respond_friend_request', request_id=r['id'], action='reject') }}">
              <button class="btn btn-danger btn-sm" type="submit">Reject</button>
            </form>
          </div>
        </div>
      {% else %}<p class="small">No incoming requests.</p>{% endfor %}
    </div>
    <div class="card">
      <h3>Sent ({{ outgoing|length }})</h3>
      {% for r in outgoing %}
        <div class="user-list-item">
          <div class="user-mini">
            <div class="avatar-mini">{{ r['display_name']|initial }}</div>
            <div>
              <a href="{{ url_for('profile', username=r['username']) }}"><b>{{ r['display_name'] }}</b></a>
              <div class="small">@{{ r['username'] }} · {{ r['created_at'][:10] }}</div>
            </div>
          </div>
          <form method="post" action="{{ url_for('cancel_friend_request', username=r['username']) }}">
            <button class="btn btn-danger btn-sm" type="submit">Cancel</button>
          </form>
        </div>
      {% else %}<p class="small">No sent requests pending.</p>{% endfor %}
    </div>"""
    return render_page("Friend Requests", body, incoming=incoming, outgoing=outgoing)


@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow_user(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    if target["id"] == me["id"]:
        flash("You can't follow yourself.","error")
        return redirect(url_for("profile", username=username))
    if not is_following(me["id"], target["id"]):
        db.execute("INSERT INTO followers (follower_id,following_id,created_at) VALUES (?,?,?)",
                   (me["id"], target["id"], datetime.utcnow().isoformat()))
        db.commit()
        create_notification(target["id"],"follow",
                            f"{me['display_name']} started following you.",
                            url_for("profile", username=me["username"]))
        flash(f"You are now following {target['display_name']}.","success")
    return redirect(url_for("profile", username=username))


@app.route("/unfollow/<username>", methods=["POST"])
@login_required
def unfollow_user(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    db.execute("DELETE FROM followers WHERE follower_id=? AND following_id=?",(me["id"],target["id"]))
    db.commit()
    flash(f"Unfollowed {target['display_name']}.","success")
    return redirect(url_for("profile", username=username))


@app.route("/friends/request/<username>", methods=["POST"])
@login_required
def send_friend_request(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    if target["id"] == me["id"]:
        flash("You can't send yourself a friend request.","error")
        return redirect(url_for("profile", username=username))
    if is_friend(me["id"], target["id"]):
        flash("You are already friends.","error")
        return redirect(url_for("profile", username=username))
    if pending_friend_request(me["id"], target["id"]):
        flash("Friend request already sent.","error")
        return redirect(url_for("profile", username=username))
    their_request = pending_friend_request(target["id"], me["id"])
    if their_request:
        return respond_friend_request(their_request["id"], "accept")
    db.execute("""INSERT INTO friend_requests (sender_id,receiver_id,status,created_at)
                  VALUES (?,?,'pending',?)""",(me["id"],target["id"],datetime.utcnow().isoformat()))
    db.commit()
    create_notification(target["id"],"friend_request",
                        f"{me['display_name']} sent you a friend request.",
                        url_for("friend_requests_page"))
    flash(f"Friend request sent to {target['display_name']}.","success")
    return redirect(url_for("profile", username=username))


@app.route("/friends/request/<int:request_id>/<action>", methods=["POST"])
@login_required
def respond_friend_request(request_id, action):
    me  = current_user()
    db  = get_db()
    req = db.execute("SELECT * FROM friend_requests WHERE id=?",(request_id,)).fetchone()
    if not req or req["receiver_id"] != me["id"] or req["status"] != "pending":
        abort(404)
    sender = db.execute("SELECT * FROM users WHERE id=?",(req["sender_id"],)).fetchone()

    if action == "accept":
        db.execute("UPDATE friend_requests SET status='accepted',responded_at=? WHERE id=?",
                   (datetime.utcnow().isoformat(), request_id))
        a, b = friend_pair(req["sender_id"], req["receiver_id"])
        if not is_friend(a, b):
            db.execute("INSERT INTO friends (user_id_a,user_id_b,created_at) VALUES (?,?,?)",
                       (a, b, datetime.utcnow().isoformat()))
        for fid, toid in [(me["id"],sender["id"]),(sender["id"],me["id"])]:
            if not is_following(fid, toid):
                db.execute("INSERT INTO followers (follower_id,following_id,created_at) VALUES (?,?,?)",
                           (fid, toid, datetime.utcnow().isoformat()))
        db.commit()
        create_notification(sender["id"],"friend_accepted",
                            f"{me['display_name']} accepted your friend request.",
                            url_for("profile", username=me["username"]))
        flash(f"You are now friends with {sender['display_name']}.","success")
    elif action == "reject":
        db.execute("UPDATE friend_requests SET status='rejected',responded_at=? WHERE id=?",
                   (datetime.utcnow().isoformat(), request_id))
        db.commit()
        flash(f"Rejected friend request from {sender['display_name']}.","success")
    else:
        abort(400)
    return redirect(request.referrer or url_for("friend_requests_page"))


@app.route("/friends/request/cancel/<username>", methods=["POST"])
@login_required
def cancel_friend_request(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    db.execute("""DELETE FROM friend_requests
                  WHERE sender_id=? AND receiver_id=? AND status='pending'""",
               (me["id"], target["id"]))
    db.commit()
    flash("Friend request cancelled.","success")
    return redirect(request.referrer or url_for("profile", username=username))


@app.route("/friends/remove/<username>", methods=["POST"])
@login_required
def remove_friend(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
    if not target: abort(404)
    a, b = friend_pair(me["id"], target["id"])
    db.execute("DELETE FROM friends WHERE user_id_a=? AND user_id_b=?",(a,b))
    db.execute("""DELETE FROM friend_requests WHERE
                  (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)""",
               (me["id"],target["id"],target["id"],me["id"]))
    db.commit()
    flash(f"Removed {target['display_name']} from your friends.","success")
    return redirect(request.referrer or url_for("profile", username=username))


"""
================================================================================
SECTION 8: CHAT / MESSAGING
================================================================================
"""

@app.route("/messages")
@login_required
def messages_list():
    me = current_user()
    db = get_db()
    # Get distinct conversations: for each other user we've exchanged messages with,
    # get the latest message and unread count.
    convos = db.execute("""
        SELECT
          other_user_id,
          u.username, u.display_name, u.last_seen,
          MAX(created_at) AS last_msg_at,
          (SELECT message FROM messages
           WHERE (sender_id=me.id AND receiver_id=other_user_id)
              OR (sender_id=other_user_id AND receiver_id=me.id)
           ORDER BY created_at DESC LIMIT 1) AS last_msg_text,
          (SELECT COUNT(*) FROM messages
           WHERE sender_id=other_user_id AND receiver_id=me.id AND is_read=0) AS unread
        FROM (
          SELECT CASE WHEN sender_id=:me THEN receiver_id ELSE sender_id END AS other_user_id
          FROM messages WHERE sender_id=:me OR receiver_id=:me
        ) AS pairs,
        (SELECT :me AS id) AS me
        JOIN users u ON u.id=other_user_id
        GROUP BY other_user_id
        ORDER BY last_msg_at DESC
    """, {"me": me["id"]}).fetchall()

    body = """
    <h1>💬 Messages</h1>
    {% if convos %}
    <div class="card" style="padding:0;overflow:hidden">
      {% for c in convos %}
        <a class="chat-contact" href="{{ url_for('chat_page', user_id=c['other_user_id']) }}">
          <div class="avatar-mini">
            {{ c['display_name']|initial }}
            {% if is_online_fn(c['last_seen']) %}<div class="online-dot"></div>{% endif %}
          </div>
          <div class="chat-contact-info">
            <b>{{ c['display_name'] }}</b>
            <span>{{ (c['last_msg_text'] or '')[:50] }}</span>
          </div>
          {% if c['unread'] > 0 %}
            <span class="chat-unread-dot">{{ c['unread'] }}</span>
          {% endif %}
        </a>
      {% endfor %}
    </div>
    {% else %}
      <div class="card">
        <p class="small">No conversations yet. <a href="{{ url_for('user_search') }}">Find someone to message →</a></p>
      </div>
    {% endif %}
    """
    return render_page("Messages", body, convos=convos, is_online_fn=is_online)


@app.route("/chat/<int:user_id>", methods=["GET","POST"])
@login_required
def chat_page(user_id):
    me       = current_user()
    db       = get_db()
    other    = db.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not other: abort(404)
    if other["id"] == me["id"]:
        flash("You can't message yourself.","error")
        return redirect(url_for("messages_list"))

    if request.method == "POST":
        msg_text = request.form.get("message","").strip()
        if msg_text:
            db.execute("""INSERT INTO messages (sender_id,receiver_id,message,created_at,is_read)
                          VALUES (?,?,?,?,0)""",
                       (me["id"], user_id, msg_text[:2000], datetime.utcnow().isoformat()))
            db.commit()
            create_notification(user_id,"message",
                                f"{me['display_name']}: {msg_text[:60]}",
                                url_for("chat_page", user_id=me["id"]))
        return redirect(url_for("chat_page", user_id=user_id))

    # Mark messages from other as read
    db.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=? AND is_read=0",
               (user_id, me["id"]))
    db.commit()

    chat_msgs = db.execute("""
        SELECT m.*,u.display_name,u.username FROM messages m
        JOIN users u ON u.id=m.sender_id
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY m.created_at ASC LIMIT 200
    """,(me["id"],user_id,user_id,me["id"])).fetchall()

    # Sidebar: other conversations
    convos = db.execute("""
        SELECT
          other_user_id,
          u.username, u.display_name, u.last_seen,
          (SELECT COUNT(*) FROM messages
           WHERE sender_id=other_user_id AND receiver_id=:me AND is_read=0) AS unread
        FROM (
          SELECT CASE WHEN sender_id=:me THEN receiver_id ELSE sender_id END AS other_user_id
          FROM messages WHERE sender_id=:me OR receiver_id=:me
        ) AS pairs,
        (SELECT :me AS id) AS dummy
        JOIN users u ON u.id=other_user_id
        GROUP BY other_user_id
        ORDER BY MAX(
          (SELECT created_at FROM messages
           WHERE (sender_id=:me AND receiver_id=other_user_id)
              OR (sender_id=other_user_id AND receiver_id=:me)
           ORDER BY created_at DESC LIMIT 1)
        ) DESC
    """, {"me": me["id"]}).fetchall()

    online = is_online(other["last_seen"])
    body = """
    <div class="flex" style="margin-bottom:14px;align-items:center">
      <a href="{{ url_for('messages_list') }}" class="btn btn-sm">← Back</a>
      <h1 style="margin:0 10px">Chat with {{ other['display_name'] }}</h1>
      {% if online %}<span class="badge badge-good">● Online</span>
      {% else %}<span class="small">Last seen {{ other['last_seen'][:16].replace('T',' ') if other['last_seen'] else 'never' }}</span>
      {% endif %}
    </div>
    <div class="chat-layout">
      <div class="card chat-sidebar" style="padding:0;overflow-y:auto">
        {% for c in convos %}
          <a class="chat-contact {% if c['other_user_id']==other['id'] %}active{% endif %}"
             href="{{ url_for('chat_page', user_id=c['other_user_id']) }}">
            <div class="avatar-mini" style="width:28px;height:28px;font-size:11px">
              {{ c['display_name']|initial }}
              {% if is_online_fn(c['last_seen']) %}<div class="online-dot"></div>{% endif %}
            </div>
            <div class="chat-contact-info">
              <b>{{ c['display_name'] }}</b>
            </div>
            {% if c['unread'] > 0 %}<span class="chat-unread-dot">{{ c['unread'] }}</span>{% endif %}
          </a>
        {% endfor %}
        <a class="chat-contact" href="{{ url_for('user_search') }}" style="color:var(--text-dim);font-size:12px">
          + New conversation
        </a>
      </div>
      <div>
        <div class="chat-messages" id="msgs">
          {% for m in chat_msgs %}
            <div class="chat-bubble {% if m['sender_id']==user['id'] %}mine{% else %}theirs{% endif %}">
              <p>{{ m['message'] }}</p>
              <div class="ts">
                {{ m['created_at'][11:16] }}
                {% if m['sender_id']==user['id'] and m['is_read'] %}
                  <span class="read-tick">✓✓</span>
                {% elif m['sender_id']==user['id'] %}
                  <span style="color:var(--text-dim);font-size:10px">✓</span>
                {% endif %}
              </div>
            </div>
          {% else %}
            <p class="small" style="text-align:center;margin-top:auto">
              No messages yet. Say hello!
            </p>
          {% endfor %}
        </div>
        <form method="post" class="chat-input-row">
          <input name="message" placeholder="Type a message…" autocomplete="off" required>
          <button class="btn btn-yellow" type="submit">Send</button>
        </form>
      </div>
    </div>
    <script>
      var msgs = document.getElementById('msgs');
      if(msgs) msgs.scrollTop = msgs.scrollHeight;
    </script>
    """
    return render_page(f"Chat · {other['display_name']}", body,
                       other=other, chat_msgs=chat_msgs, convos=convos,
                       online=online, is_online_fn=is_online)


"""
================================================================================
SECTION 9: SOCIAL FEED (posts, likes, comments)
================================================================================
"""

ALLOWED_POST_EXT_CHECK = ALLOWED_IMAGE_EXT | ALLOWED_VIDEO_EXT

def allowed_post_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_POST_EXT_CHECK

@app.route("/uploads/posts/<filename>")
@login_required
def serve_post_media(filename):
    return send_from_directory(POSTS_UPLOAD_DIR, secure_filename(filename))


def _render_post(post, me_id):
    """Return the HTML snippet for a single post card (used in feed & view)."""
    return f"""
<div class="card post-card" id="post-{post['id']}">
  <div class="post-header">
    <div class="avatar-mini">{post['display_name'][:1].upper()}</div>
    <div class="post-meta">
      <b><a href="/profile/{post['username']}">{post['display_name']}</a></b>
      <span>{post['created_at'][:16].replace('T',' ')}{' (edited)' if post['updated_at'] else ''}</span>
    </div>
    {'<a class="btn btn-sm" href="/post/'+str(post['id'])+'/edit">Edit</a>' if post['user_id']==me_id else ''}
    {'<form method="post" action="/post/'+str(post['id'])+'/delete" style="display:inline"><button class="btn btn-danger btn-sm" type="submit">Delete</button></form>' if post['user_id']==me_id else ''}
  </div>
  {'<p class="post-content">'+post['content']+'</p>' if post['content'] else ''}
"""


@app.route("/feed", methods=["GET","POST"])
@login_required
def feed():
    me = current_user()
    db = get_db()

    if request.method == "POST":
        content        = request.form.get("content","").strip()[:2000]
        media_file     = request.files.get("media_file")
        media_filename = None
        post_type      = "text"

        if media_file and media_file.filename and allowed_post_file(media_file.filename):
            ext  = media_file.filename.rsplit(".",1)[1].lower()
            fname = f"{secrets.token_hex(10)}.{ext}"
            media_file.save(os.path.join(POSTS_UPLOAD_DIR, fname))
            media_filename = fname
            post_type = "image" if ext in ALLOWED_IMAGE_EXT else "video"

        if not content and not media_filename:
            flash("Post must have text or media.","error")
            return redirect(url_for("feed"))

        db.execute("""INSERT INTO posts (user_id,content,post_type,media_filename,created_at)
                      VALUES (?,?,?,?,?)""",
                   (me["id"], content, post_type, media_filename, datetime.utcnow().isoformat()))
        db.commit()
        grant_xp(me["id"], 5)
        flash("Post published!","success")
        return redirect(url_for("feed"))

    posts = db.execute("""
        SELECT p.*,u.username,u.display_name,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id)   AS comment_count,
               (SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=:me) AS i_liked
        FROM posts p JOIN users u ON u.id=p.user_id
        ORDER BY p.created_at DESC LIMIT 40
    """, {"me": me["id"]}).fetchall()

    body = """
    <h1>📰 Feed</h1>
    <div class="card">
      <h3>Create Post</h3>
      <form method="post" enctype="multipart/form-data">
        <textarea name="content" rows="3" placeholder="What's on your mind?"></textarea>
        <label>Attach image or video (optional)</label>
        <input type="file" name="media_file" accept="image/*,video/mp4,video/webm"
               style="background:transparent;border:none;padding:4px 0">
        <button class="btn btn-yellow" type="submit" style="margin-top:4px">Publish</button>
      </form>
    </div>

    {% for post in posts %}
    <div class="card post-card" id="post-{{ post['id'] }}">
      <div class="post-header">
        <div class="avatar-mini">{{ post['display_name']|initial }}</div>
        <div class="post-meta">
          <b><a href="{{ url_for('profile', username=post['username']) }}">{{ post['display_name'] }}</a></b>
          <span>{{ post['created_at'][:16].replace('T',' ') }}{% if post['updated_at'] %} (edited){% endif %}</span>
        </div>
        {% if post['user_id']==user['id'] %}
          <a class="btn btn-sm" href="{{ url_for('edit_post', post_id=post['id']) }}" style="margin-left:auto">Edit</a>
          <form method="post" action="{{ url_for('delete_post', post_id=post['id']) }}" style="display:inline;margin-left:6px">
            <button class="btn btn-danger btn-sm" type="submit">Delete</button>
          </form>
        {% endif %}
      </div>

      {% if post['content'] %}
        <p class="post-content">{{ post['content'] }}</p>
      {% endif %}

      {% if post['media_filename'] %}
        <div class="post-media">
          {% if post['post_type']=='image' %}
            <img src="{{ url_for('serve_post_media', filename=post['media_filename']) }}" alt="post image">
          {% elif post['post_type']=='video' %}
            <video controls><source src="{{ url_for('serve_post_media', filename=post['media_filename']) }}"></video>
          {% endif %}
        </div>
      {% endif %}

      <div class="post-actions">
        <form method="post" action="{{ url_for('toggle_like', post_id=post['id']) }}">
          <button class="btn btn-sm {% if post['i_liked'] %}btn-danger{% endif %}" type="submit">
            {% if post['i_liked'] %}❤ Unlike{% else %}♡ Like{% endif %}
          </button>
        </form>
        <span class="like-count">{{ post['like_count'] }} like{{ 's' if post['like_count']!=1 }}</span>
        <a class="btn btn-sm" href="{{ url_for('view_post', post_id=post['id']) }}">💬 {{ post['comment_count'] }} Comment{{ 's' if post['comment_count']!=1 }}</a>
      </div>
    </div>
    {% else %}
      <div class="card"><p class="small">No posts yet. Be the first to post!</p></div>
    {% endfor %}
    """
    return render_page("Feed", body, posts=posts)


@app.route("/post/<int:post_id>")
@login_required
def view_post(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("""
        SELECT p.*,u.username,u.display_name,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=?) AS i_liked
        FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?
    """,(me["id"], post_id)).fetchone()
    if not post: abort(404)

    comments = db.execute("""
        SELECT c.*,u.username,u.display_name FROM comments c
        JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.created_at ASC
    """,(post_id,)).fetchall()

    body = """
    <a href="{{ url_for('feed') }}" class="btn btn-sm" style="margin-bottom:12px">← Feed</a>
    <div class="card post-card">
      <div class="post-header">
        <div class="avatar-lg">{{ post['display_name']|initial }}</div>
        <div class="post-meta">
          <b><a href="{{ url_for('profile', username=post['username']) }}">{{ post['display_name'] }}</a></b>
          <span>{{ post['created_at'][:16].replace('T',' ') }}{% if post['updated_at'] %} (edited {{ post['updated_at'][:16].replace('T',' ') }}){% endif %}</span>
        </div>
        {% if post['user_id']==user['id'] %}
          <a class="btn btn-sm" href="{{ url_for('edit_post', post_id=post['id']) }}" style="margin-left:auto">Edit</a>
          <form method="post" action="{{ url_for('delete_post', post_id=post['id']) }}" style="display:inline;margin-left:6px">
            <button class="btn btn-danger btn-sm" type="submit">Delete</button>
          </form>
        {% endif %}
      </div>

      {% if post['content'] %}
        <p class="post-content">{{ post['content'] }}</p>
      {% endif %}

      {% if post['media_filename'] %}
        <div class="post-media">
          {% if post['post_type']=='image' %}
            <img src="{{ url_for('serve_post_media', filename=post['media_filename']) }}" alt="">
          {% elif post['post_type']=='video' %}
            <video controls><source src="{{ url_for('serve_post_media', filename=post['media_filename']) }}"></video>
          {% endif %}
        </div>
      {% endif %}

      <div class="post-actions">
        <form method="post" action="{{ url_for('toggle_like', post_id=post['id']) }}">
          <button class="btn btn-sm {% if post['i_liked'] %}btn-danger{% endif %}" type="submit">
            {% if post['i_liked'] %}❤ Unlike{% else %}♡ Like{% endif %}
          </button>
        </form>
        <span class="like-count">{{ post['like_count'] }} like{{ 's' if post['like_count']!=1 }}</span>
      </div>
    </div>

    <h2>Comments ({{ comments|length }})</h2>
    <div class="card">
      {% for c in comments %}
        <div class="comment">
          <div class="avatar-mini" style="width:30px;height:30px;font-size:12px">{{ c['display_name']|initial }}</div>
          <div class="comment-body">
            <b><a href="{{ url_for('profile', username=c['username']) }}">{{ c['display_name'] }}</a></b>
            <p>{{ c['content'] }}</p>
            <span>{{ c['created_at'][:16].replace('T',' ') }}</span>
            {% if c['user_id']==user['id'] or post['user_id']==user['id'] %}
              <form method="post" action="{{ url_for('delete_comment', comment_id=c['id']) }}" style="display:inline;margin-left:8px">
                <button class="btn btn-danger btn-sm" type="submit" style="padding:2px 7px;font-size:11px">✕</button>
              </form>
            {% endif %}
          </div>
        </div>
      {% else %}
        <p class="small">No comments yet.</p>
      {% endfor %}
      <hr class="divider">
      <form method="post" action="{{ url_for('add_comment', post_id=post['id']) }}">
        <textarea name="content" rows="2" placeholder="Write a comment…" required></textarea>
        <button class="btn btn-sm btn-yellow" type="submit">Comment</button>
      </form>
    </div>
    """
    return render_page("Post", body, post=post, comments=comments)


@app.route("/post/<int:post_id>/edit", methods=["GET","POST"])
@login_required
def edit_post(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?",(post_id,)).fetchone()
    if not post or post["user_id"] != me["id"]: abort(403)

    if request.method == "POST":
        content = request.form.get("content","").strip()[:2000]
        db.execute("UPDATE posts SET content=?,updated_at=? WHERE id=?",
                   (content, datetime.utcnow().isoformat(), post_id))
        db.commit()
        flash("Post updated.","success")
        return redirect(url_for("view_post", post_id=post_id))

    body = """
    <h1>Edit Post</h1>
    <div class="card" style="max-width:600px">
      <form method="post">
        <label>Content</label>
        <textarea name="content" rows="5">{{ post['content'] }}</textarea>
        <div class="flex" style="margin-top:4px">
          <button class="btn btn-yellow" type="submit">Save</button>
          <a class="btn" href="{{ url_for('view_post', post_id=post['id']) }}">Cancel</a>
        </div>
      </form>
    </div>"""
    return render_page("Edit Post", body, post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?",(post_id,)).fetchone()
    if not post or (post["user_id"] != me["id"] and not me["is_admin"]): abort(403)
    if post["media_filename"]:
        path = os.path.join(POSTS_UPLOAD_DIR, post["media_filename"])
        if os.path.exists(path): os.remove(path)
    db.execute("DELETE FROM post_likes WHERE post_id=?",(post_id,))
    db.execute("DELETE FROM comments WHERE post_id=?",(post_id,))
    db.execute("DELETE FROM posts WHERE id=?",(post_id,))
    db.commit()
    flash("Post deleted.","success")
    return redirect(url_for("feed"))


@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def toggle_like(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?",(post_id,)).fetchone()
    if not post: abort(404)
    existing = db.execute("SELECT 1 FROM post_likes WHERE user_id=? AND post_id=?",
                           (me["id"], post_id)).fetchone()
    if existing:
        db.execute("DELETE FROM post_likes WHERE user_id=? AND post_id=?",(me["id"],post_id))
        db.commit()
    else:
        db.execute("INSERT INTO post_likes (user_id,post_id,created_at) VALUES (?,?,?)",
                   (me["id"], post_id, datetime.utcnow().isoformat()))
        db.commit()
        if post["user_id"] != me["id"]:
            create_notification(post["user_id"],"like",
                                f"{me['display_name']} liked your post.",
                                url_for("view_post", post_id=post_id))
    return redirect(request.referrer or url_for("feed"))


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    me      = current_user()
    db      = get_db()
    post    = db.execute("SELECT * FROM posts WHERE id=?",(post_id,)).fetchone()
    if not post: abort(404)
    content = request.form.get("content","").strip()[:1000]
    if not content:
        flash("Comment cannot be empty.","error")
        return redirect(url_for("view_post", post_id=post_id))
    db.execute("INSERT INTO comments (user_id,post_id,content,created_at) VALUES (?,?,?,?)",
               (me["id"], post_id, content, datetime.utcnow().isoformat()))
    db.commit()
    if post["user_id"] != me["id"]:
        create_notification(post["user_id"],"comment",
                            f"{me['display_name']} commented on your post: {content[:60]}",
                            url_for("view_post", post_id=post_id))
    return redirect(url_for("view_post", post_id=post_id))


@app.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    me  = current_user()
    db  = get_db()
    c   = db.execute("SELECT * FROM comments WHERE id=?",(comment_id,)).fetchone()
    if not c: abort(404)
    post = db.execute("SELECT * FROM posts WHERE id=?",(c["post_id"],)).fetchone()
    if c["user_id"] != me["id"] and (not post or post["user_id"] != me["id"]) and not me["is_admin"]:
        abort(403)
    db.execute("DELETE FROM comments WHERE id=?",(comment_id,))
    db.commit()
    flash("Comment deleted.","success")
    return redirect(request.referrer or url_for("view_post", post_id=c["post_id"]))


"""
================================================================================
SECTION 10: NOTIFICATIONS
================================================================================
"""

NOTIF_ICONS = {
    "message":        "💬",
    "follow":         "👤",
    "like":           "❤",
    "comment":        "💬",
    "daily_reward":   "🎁",
    "game_sold":      "🎮",
    "friend_request": "🤝",
    "friend_accepted":"✅",
}

@app.route("/notifications")
@login_required
def notifications_page():
    me  = current_user()
    db  = get_db()
    # Mark all as read
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(me["id"],))
    db.commit()
    notifs = db.execute("""SELECT * FROM notifications WHERE user_id=?
                            ORDER BY created_at DESC LIMIT 60""",(me["id"],)).fetchall()
    body = """
    <div class="flex" style="margin-bottom:14px;align-items:center;justify-content:space-between">
      <h1 style="margin:0">🔔 Notifications</h1>
      {% if notifs %}
        <form method="post" action="{{ url_for('clear_notifications') }}">
          <button class="btn btn-danger btn-sm" type="submit">Clear All</button>
        </form>
      {% endif %}
    </div>
    <div class="card">
      {% for n in notifs %}
        <div class="notif-item {% if not n['is_read'] %}unread{% endif %}">
          <div class="notif-icon">{{ icons.get(n['type'],'🔔') }}</div>
          <div class="notif-body">
            <p>{% if n['link'] %}<a href="{{ n['link'] }}">{{ n['message'] }}</a>{% else %}{{ n['message'] }}{% endif %}</p>
            <span>{{ n['created_at'][:16].replace('T',' ') }}</span>
          </div>
          {% if not n['is_read'] %}<div class="notif-unread-dot"></div>{% endif %}
        </div>
      {% else %}
        <p class="small">No notifications yet.</p>
      {% endfor %}
    </div>
    """
    return render_page("Notifications", body, notifs=notifs, icons=NOTIF_ICONS)


@app.route("/notifications/clear", methods=["POST"])
@login_required
def clear_notifications():
    me = current_user()
    get_db().execute("DELETE FROM notifications WHERE user_id=?",(me["id"],))
    get_db().commit()
    flash("All notifications cleared.","success")
    return redirect(url_for("notifications_page"))


"""
================================================================================
SECTION 11: SETTINGS & ACCOUNT RESET
================================================================================
"""

@app.route("/settings", methods=["GET","POST"])
@login_required
def settings_page():
    me = current_user()
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password":
            current_pw = request.form.get("current_password","")
            new_pw     = request.form.get("new_password","")
            if not check_password_hash(me["password_hash"], current_pw):
                flash("Current password is incorrect.","error")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.","error")
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (generate_password_hash(new_pw), me["id"]))
                db.commit()
                flash("Password changed successfully.","success")

        elif action == "reset_account":
            confirm = request.form.get("confirm_text","")
            if confirm != "RESET MY ACCOUNT":
                flash("Confirmation text did not match. Account NOT reset.","error")
            else:
                uid = me["id"]
                # Reset balances
                db.execute("UPDATE balances SET amount=0 WHERE user_id=?",(uid,))
                db.execute("UPDATE balances SET amount=200 WHERE user_id=? AND currency='NEO'",(uid,))
                # Reset stats
                db.execute("UPDATE users SET xp=0,level=1,daily_streak=0,last_daily_claim=NULL WHERE id=?",(uid,))
                # Clear activity
                for tbl in ["transactions","purchases","investments","asset_holdings",
                            "notifications","messages","posts","game_rewards"]:
                    try:
                        if tbl == "messages":
                            db.execute("DELETE FROM messages WHERE sender_id=? OR receiver_id=?",(uid,uid))
                        elif tbl == "posts":
                            # Also clear likes and comments on own posts
                            own_posts = db.execute("SELECT id FROM posts WHERE user_id=?",(uid,)).fetchall()
                            for p in own_posts:
                                db.execute("DELETE FROM post_likes WHERE post_id=?",(p["id"],))
                                db.execute("DELETE FROM comments WHERE post_id=?",(p["id"],))
                            db.execute("DELETE FROM posts WHERE user_id=?",(uid,))
                            db.execute("DELETE FROM post_likes WHERE user_id=?",(uid,))
                            db.execute("DELETE FROM comments WHERE user_id=?",(uid,))
                        elif tbl == "transactions":
                            db.execute("DELETE FROM transactions WHERE user_id=?",(uid,))
                        elif tbl == "purchases":
                            db.execute("DELETE FROM purchases WHERE user_id=?",(uid,))
                        elif tbl == "investments":
                            db.execute("DELETE FROM investments WHERE user_id=?",(uid,))
                        elif tbl == "asset_holdings":
                            db.execute("DELETE FROM asset_holdings WHERE user_id=?",(uid,))
                        elif tbl == "notifications":
                            db.execute("DELETE FROM notifications WHERE user_id=?",(uid,))
                        elif tbl == "game_rewards":
                            db.execute("DELETE FROM game_rewards WHERE user_id=?",(uid,))
                    except Exception:
                        pass
                db.commit()
                flash("Your account has been reset to its initial state. You have 200 Neo.","success")
                return redirect(url_for("index"))

        return redirect(url_for("settings_page"))

    body = """
    <h1>⚙ Settings</h1>
    <div class="card">
      <div class="settings-section">
        <h3>Change Password</h3>
        <form method="post">
          <input type="hidden" name="action" value="change_password">
          <label>Current Password</label>
          <input type="password" name="current_password" required>
          <label>New Password</label>
          <input type="password" name="new_password" required>
          <button class="btn" type="submit">Update Password</button>
        </form>
      </div>

      <div class="settings-section">
        <h3>Account Information</h3>
        <p class="small">Username: <b>{{ user['username'] }}</b></p>
        <p class="small">Email: <b>{{ user['email'] }}</b></p>
        <p class="small">Member since: <b>{{ user['created_at'][:10] }}</b></p>
      </div>

      <div class="settings-section">
        <h3 class="text-danger">⚠ Danger Zone: Reset Account</h3>
        <p class="small" style="margin-bottom:10px">
          This will permanently reset your balances to 200 Neo starter grant, reset XP, level,
          and streak to zero, and erase your posts, messages, purchases, investments, and notifications.
          <b>This action cannot be undone.</b>
        </p>
        <form method="post" onsubmit="return confirm('Are you absolutely sure? This cannot be undone.')">
          <input type="hidden" name="action" value="reset_account">
          <label>Type <b>RESET MY ACCOUNT</b> to confirm</label>
          <input name="confirm_text" placeholder="RESET MY ACCOUNT" style="border-color:var(--danger)">
          <button class="btn btn-danger" type="submit">Reset My Account</button>
        </form>
      </div>
    </div>
    """
    return render_page("Settings", body)


"""
================================================================================
SECTION 12: WALLET
================================================================================
"""

@app.route("/wallet", methods=["GET","POST"])
@login_required
def wallet():
    user = current_user()
    if request.method == "POST":
        target_currency = request.form.get("currency")
        try:    neo_amount = int(request.form.get("neo_amount","0"))
        except: neo_amount = 0
        if target_currency not in OTHER_CURRENCIES or neo_amount <= 0:
            flash("Invalid conversion request.","error")
        else:
            bal = get_balances(user["id"])
            if bal["NEO"] < neo_amount:
                flash("Not enough Neo for that conversion.","error")
            else:
                rate   = CURRENCIES[target_currency]["rate_from_neo"]
                gained = neo_amount * rate
                adjust_balance(user["id"],"NEO",-neo_amount,f"Converted to {target_currency}")
                adjust_balance(user["id"],target_currency,gained,"Converted from Neo")
                flash(f"Converted {neo_amount} Neo → {gained} {CURRENCIES[target_currency]['name']}.","success")
        return redirect(url_for("wallet"))

    bal     = get_balances(user["id"])
    db      = get_db()
    history = db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
                          (user["id"],)).fetchall()
    body = """
    <h1>Wallet</h1>
    <div class="card">
      <h3>Balances</h3>
      {% for code, info in currencies.items() %}
        <div class="currency-row">
          <span>{{ info['name'] }}{% if info.get('master') %} <span class="small">(master)</span>{% endif %}</span>
          <b>{{ bal[code] }}</b>
        </div>
      {% endfor %}
    </div>
    <div class="card">
      <h3>Convert Neo → Other Currency</h3>
      <p class="small">One-way conversion. All currencies are fictional and have no real-world value.</p>
      <form method="post">
        <label>Amount of Neo</label>
        <input type="number" name="neo_amount" min="1" required>
        <label>Target currency</label>
        <select name="currency">
          {% for code in other_currencies %}
            <option value="{{ code }}">{{ currencies[code]['name'] }} (rate 1 Neo = {{ currencies[code]['rate_from_neo'] }})</option>
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
        {% else %}<tr><td colspan="5" class="small">No transactions yet.</td></tr>{% endfor %}
      </table>
    </div>
    """
    return render_page("Wallet", body, bal=bal, currencies=CURRENCIES,
                        other_currencies=OTHER_CURRENCIES, history=history)


"""
================================================================================
SECTION 13: DAILY REWARDS (infinite streak)
================================================================================
"""

@app.route("/rewards/daily", methods=["GET","POST"])
@login_required
def daily_reward():
    user = current_user()
    can_claim, streak = daily_reward_status(user)
    base_amount = daily_reward_amount(streak)

    if request.method == "POST":
        if not can_claim:
            flash("You already claimed today's reward.","error")
            return redirect(url_for("daily_reward"))

        lucky  = random.random() < LUCKY_CHANCE
        amount = base_amount * LUCKY_MULTIPLIER if lucky else base_amount
        new_streak = streak + 1

        db = get_db()
        db.execute("UPDATE users SET daily_streak=?,last_daily_claim=? WHERE id=?",
                   (new_streak, date.today().isoformat(), user["id"]))
        db.commit()
        adjust_balance(user["id"],"NEO", amount, f"Daily reward streak day {new_streak}")
        grant_xp(user["id"], 15)

        if lucky:
            flash(f"🌟 LUCKY BONUS! Claimed {amount} Neo (x{LUCKY_MULTIPLIER}) · Streak: {new_streak} days","success")
        else:
            flash(f"🎁 Claimed {amount} Neo · Streak: {new_streak} days","success")
        return redirect(url_for("daily_reward"))

    next_amount   = base_amount
    lucky_amount  = base_amount * LUCKY_MULTIPLIER
    # Preview: next few days
    previews = [(i+1, daily_reward_amount(streak+i)) for i in range(7)]

    body = """
    <h1>🎁 Daily Reward</h1>
    <div class="card" style="max-width:500px">
      <div class="reward-progress">
        <div class="flex" style="justify-content:space-between;margin-bottom:8px">
          <span>Current Streak</span>
          <b style="color:var(--accent-yellow)">{{ streak }} days</b>
        </div>
        <div class="reward-bar-wrap">
          <div class="reward-bar" style="width:{{ [(streak % 10)*10, 100]|min }}%"></div>
        </div>
        <p class="small" style="margin-top:6px">
          Rewards grow with every consecutive day. Missing a day resets your streak!
        </p>
      </div>

      {% if can_claim %}
        <div style="text-align:center;margin:16px 0">
          <div style="font-size:36px;color:var(--accent-yellow);font-weight:900">
            +{{ next_amount }} Neo
          </div>
          <p class="small">{{ (lucky_chance*100)|round }}% chance of 🌟 Lucky x{{ lucky_mult }} (→ {{ lucky_amount }} Neo)</p>
          <form method="post" style="margin-top:12px">
            <button class="btn btn-yellow" type="submit" style="font-size:16px;padding:12px 28px">
              Claim Day {{ streak+1 }} Reward
            </button>
          </form>
        </div>
      {% else %}
        <div style="text-align:center;margin:16px 0">
          <p class="text-good" style="font-size:16px">✓ Claimed today!</p>
          <p class="small">Come back tomorrow for +{{ daily_reward_amount(streak+1) }} Neo</p>
        </div>
      {% endif %}

      <h3 style="margin-top:14px">Upcoming Rewards</h3>
      {% for day, amt in previews %}
        <div class="currency-row">
          <span class="small">Day {{ streak + day }}</span>
          <b style="color:var(--neon)">+{{ amt }} Neo</b>
        </div>
      {% endfor %}
    </div>
    """
    return render_page("Daily Reward", body,
                       streak=streak, can_claim=can_claim,
                       next_amount=next_amount, lucky_amount=lucky_amount,
                       previews=previews, lucky_chance=LUCKY_CHANCE,
                       lucky_mult=LUCKY_MULTIPLIER,
                       daily_reward_amount=daily_reward_amount)


"""
================================================================================
SECTION 14: GAME MARKETPLACE (multi-currency pricing + play rewards)
================================================================================
"""

def allowed_game_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_GAME_EXT


@app.route("/games")
@login_required
def games_list():
    db       = get_db()
    category = request.args.get("category","")
    q        = request.args.get("q","").strip()
    query = """SELECT g.*,u.display_name AS dev_name FROM games g
               JOIN users u ON g.developer_id=u.id WHERE 1=1"""
    params = []
    if category:
        query += " AND g.category=?"; params.append(category)
    if q:
        query += " AND g.title LIKE ?"; params.append(f"%{q}%")
    query += " ORDER BY g.created_at DESC"
    games = db.execute(query, params).fetchall()

    body = """
    <h1>🎮 Game Marketplace</h1>
    <div class="card">
      <form method="get" class="responsive-row">
        <div><label>Search</label><input name="q" value="{{ request.args.get('q','') }}"></div>
        <div>
          <label>Category</label>
          <select name="category">
            <option value="">All</option>
            {% for c in categories %}
              <option value="{{ c }}" {% if c==category %}selected{% endif %}>{{ c }}</option>
            {% endfor %}
          </select>
        </div>
        <div><button class="btn" type="submit" style="margin-bottom:12px">Filter</button></div>
      </form>
    </div>
    <p style="margin-bottom:12px"><a class="btn btn-yellow" href="{{ url_for('upload_game') }}">+ Upload a Game</a></p>
    <div class="grid">
      {% for game in games %}
        <div class="card game-card">
          <b>{{ game['title'] }}</b>
          <span class="small">{{ game['category'] }} · by {{ game['dev_name'] }} · {{ game['play_count'] }} plays</span>
          <span class="badge {% if game['price']==0 %}badge-good{% else %}badge-yellow{% endif %}" style="width:fit-content">
            {% if game['price'] > 0 %}{{ game['price'] }} {{ currencies[game['price_currency']]['name'] }}{% else %}Free{% endif %}
          </span>
          <span class="small">{{ game['description'] }}</span>
          <a class="btn" style="margin-top:4px" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
        </div>
      {% else %}<p>No games found.</p>{% endfor %}
    </div>
    """
    return render_page("Games", body, games=games, categories=GAME_CATEGORIES,
                        category=category, currencies=CURRENCIES)


@app.route("/games/upload", methods=["GET","POST"])
@login_required
def upload_game():
    user = current_user()
    if request.method == "POST":
        title       = request.form.get("title","").strip()[:60]
        description = request.form.get("description","").strip()[:300]
        category    = request.form.get("category")
        file        = request.files.get("game_file")
        price_currency = request.form.get("price_currency","NEO")
        try:    price = int(request.form.get("price","0"))
        except: price = -1

        if not title or category not in GAME_CATEGORIES:
            flash("Title and valid category are required.","error")
            return redirect(url_for("upload_game"))
        if price < 0:
            flash("Price must be 0 or positive.","error")
            return redirect(url_for("upload_game"))
        if price_currency not in CURRENCIES:
            flash("Invalid currency selected.","error")
            return redirect(url_for("upload_game"))
        if not file or file.filename=="" or not allowed_game_file(file.filename):
            flash("Please upload a single .html file.","error")
            return redirect(url_for("upload_game"))

        db = get_db()
        if not user["is_developer"]:
            db.execute("UPDATE users SET is_developer=1 WHERE id=?",(user["id"],))
            db.commit()

        safe_name   = secure_filename(file.filename)
        unique_name = f"{secrets.token_hex(8)}_{safe_name}"
        file.save(os.path.join(UPLOAD_DIR, unique_name))
        db.execute("""INSERT INTO games
                      (developer_id,title,description,category,filename,price,price_currency,play_count,created_at)
                      VALUES (?,?,?,?,?,?,?,0,?)""",
                   (user["id"],title,description,category,unique_name,price,price_currency,
                    datetime.utcnow().isoformat()))
        db.commit()
        flash("Game uploaded and now live in the marketplace!","success")
        return redirect(url_for("games_list"))

    body = """
    <h1>Upload a Game</h1>
    <div class="card" style="max-width:520px">
      <p class="small">Single .html file only (max 32MB). Runs in a sandboxed iframe.</p>
      <form method="post" enctype="multipart/form-data">
        <label>Title</label><input name="title" required>
        <label>Description</label><textarea name="description" rows="3"></textarea>
        <label>Category</label>
        <select name="category">
          {% for c in categories %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
        </select>
        <label>Price</label>
        <input type="number" name="price" min="0" value="0" required>
        <label>Price Currency</label>
        <select name="price_currency">
          {% for code, info in currencies.items() %}
            <option value="{{ code }}">{{ info['name'] }}</option>
          {% endfor %}
        </select>
        <p class="small" style="margin-top:-6px">Players pay once in the selected currency. 0 = free.</p>
        <label>Game File (.html)</label>
        <input type="file" name="game_file" accept=".html,.htm" required style="background:transparent;border:none;padding:4px 0">
        <button class="btn btn-yellow" type="submit" style="margin-top:8px">Publish Game</button>
      </form>
    </div>
    """
    return render_page("Upload Game", body, categories=GAME_CATEGORIES, currencies=CURRENCIES)


@app.route("/games/play/<int:game_id>", methods=["GET","POST"])
@login_required
def play_game(game_id):
    db   = get_db()
    game = db.execute("""SELECT g.*,u.display_name AS dev_name FROM games g
                          JOIN users u ON g.developer_id=u.id WHERE g.id=?""",(game_id,)).fetchone()
    if not game: abort(404)
    user = current_user()

    already_owned  = db.execute("SELECT 1 FROM purchases WHERE user_id=? AND game_id=?",
                                 (user["id"], game_id)).fetchone() is not None
    is_exempt      = (game["price"]==0) or (game["developer_id"]==user["id"]) or bool(user["is_admin"])
    can_play       = already_owned or is_exempt

    if not can_play:
        if request.method == "POST":
            bal = get_balances(user["id"])
            price_cur = game["price_currency"] or "NEO"
            if bal[price_cur] < game["price"]:
                flash(f"You need {game['price']} {CURRENCIES[price_cur]['name']} to buy this game.","error")
                return redirect(url_for("play_game", game_id=game_id))
            adjust_balance(user["id"], price_cur, -game["price"], f"Purchased: {game['title']}")
            adjust_balance(game["developer_id"], price_cur, game["price"], f"Sale: {game['title']}")
            db.execute("INSERT INTO purchases (user_id,game_id,price_paid,purchased_at) VALUES (?,?,?,?)",
                       (user["id"], game_id, game["price"], datetime.utcnow().isoformat()))
            db.commit()
            create_notification(game["developer_id"],"game_sold",
                                f"Your game '{game['title']}' was purchased by {user['display_name']}.",
                                url_for("games_list"))
            flash(f"Purchased {game['title']}!","success")
            can_play = True
        else:
            price_cur = game["price_currency"] or "NEO"
            body = """
            <h1>{{ game['title'] }}</h1>
            <div class="card" style="max-width:480px">
              <p class="small">{{ game['category'] }} · by {{ game['dev_name'] }}</p>
              <p style="margin:8px 0">{{ game['description'] }}</p>
              <p>Price: <b>{{ game['price'] }} {{ currencies[price_cur]['name'] }}</b></p>
              <form method="post">
                <button class="btn btn-yellow" type="submit">
                  Buy & Play for {{ game['price'] }} {{ currencies[price_cur]['name'] }}
                </button>
              </form>
              <p style="margin-top:8px"><a href="{{ url_for('games_list') }}">← Back to Marketplace</a></p>
            </div>
            """
            return render_page(game["title"], body, game=game, currencies=CURRENCIES, price_cur=price_cur)

    # Record play count
    db.execute("UPDATE games SET play_count=play_count+1 WHERE id=?",(game_id,))
    db.commit()

    # Award Neo + XP for playing (first 20 plays/day)
    plays_today = get_game_plays_today(user["id"], game_id)
    neo_earned, xp_earned = record_game_play_reward(user["id"], game_id)
    remaining_plays = max(0, GAME_DAILY_PLAY_LIMIT - plays_today - 1)

    body = """
    <div class="flex" style="align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
      <h1 style="margin:0">{{ game['title'] }}</h1>
      <span class="badge">{{ game['category'] }}</span>
      <span class="small">by {{ game['dev_name'] }} · {{ game['play_count'] }} plays</span>
    </div>
    {% if neo_earned > 0 %}
      <div class="flash flash-success">
        +{{ neo_earned }} Neo &amp; +{{ xp_earned }} XP earned for playing!
        {% if remaining_plays > 0 %}({{ remaining_plays }} reward plays left today){% else %}(daily limit reached){% endif %}
      </div>
    {% elif plays_today >= game_limit %}
      <p class="small" style="margin-bottom:8px;color:var(--text-dim)">Daily play reward limit reached for this game.</p>
    {% endif %}
    <div class="game-iframe-wrap">
      <iframe src="{{ url_for('serve_game_file', filename=game['filename']) }}"
              sandbox="allow-scripts allow-forms"></iframe>
    </div>
    <p style="margin-top:8px"><a href="{{ url_for('games_list') }}">← Back to Marketplace</a></p>
    """
    return render_page(game["title"], body, game=game, neo_earned=neo_earned,
                        xp_earned=xp_earned, plays_today=plays_today,
                        remaining_plays=remaining_plays,
                        game_limit=GAME_DAILY_PLAY_LIMIT)


@app.route("/uploads/games/<filename>")
@login_required
def serve_game_file(filename):
    return send_from_directory(UPLOAD_DIR, secure_filename(filename), mimetype="text/html")


"""
================================================================================
SECTION 15: LOTTERY
================================================================================
"""

@app.route("/lottery", methods=["GET","POST"])
@login_required
def lottery():
    user = current_user()
    db   = get_db()

    if request.method == "POST":
        currency = request.form.get("currency")
        if currency not in CURRENCIES:
            flash("Invalid currency.","error")
            return redirect(url_for("lottery"))
        bal = get_balances(user["id"])
        if bal[currency] < LOTTERY_BATCH_COST:
            flash(f"You need {LOTTERY_BATCH_COST} {CURRENCIES[currency]['name']} for a batch.","error")
            return redirect(url_for("lottery"))
        adjust_balance(user["id"],currency,-LOTTERY_BATCH_COST,
                        f"Bought {LOTTERY_CARD_COUNT} scratch cards")
        cur = db.execute("INSERT INTO lottery_batches (user_id,currency,cost_paid,created_at) VALUES (?,?,?,?)",
                          (user["id"],currency,LOTTERY_BATCH_COST,datetime.utcnow().isoformat()))
        db.commit()
        batch_id = cur.lastrowid
        for i in range(LOTTERY_CARD_COUNT):
            db.execute("INSERT INTO lottery_cards (batch_id,slot_index,value,revealed) VALUES (?,?,?,0)",
                       (batch_id, i, random.randint(LOTTERY_CARD_MIN,LOTTERY_CARD_MAX)))
        db.commit()
        flash(f"Bought {LOTTERY_CARD_COUNT} cards! Scratch them one by one.","success")
        return redirect(url_for("lottery_batch", batch_id=batch_id))

    batches = db.execute("""
        SELECT b.*,
               (SELECT COUNT(*) FROM lottery_cards c WHERE c.batch_id=b.id AND c.revealed=0) AS unrevealed,
               (SELECT COALESCE(SUM(value),0) FROM lottery_cards c WHERE c.batch_id=b.id AND c.revealed=1) AS total
        FROM lottery_batches b WHERE b.user_id=? ORDER BY b.created_at DESC LIMIT 15
    """,(user["id"],)).fetchall()

    body = """
    <h1>🎰 Lottery: Scratch Cards</h1>
    <div class="card" style="max-width:480px">
      <p class="small">Buy {{ count }} cards. Each hides a random value {{ min_v }} to {{ max_v }} of
        the currency you pay with. Scratch one at a time!</p>
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
    <h2>Recent Batches</h2>
    <div class="grid">
      {% for b in batches %}
        <div class="card">
          <b>Batch #{{ b['id'] }}</b> &middot; {{ b['currency'] }}<br>
          <span class="small">{{ b['created_at'][:10] }}</span><br>
          {% if b['unrevealed'] > 0 %}
            <span class="badge">{{ b['unrevealed'] }} cards left</span>
          {% else %}
            <span class="badge {% if b['total'] >= 0 %}badge-good{% else %}badge-yellow{% endif %}">
              Net: {{ '+' if b['total']>=0 else '' }}{{ b['total'] }}
            </span>
          {% endif %}<br>
          <a class="btn btn-sm" style="margin-top:8px" href="{{ url_for('lottery_batch', batch_id=b['id']) }}">View</a>
        </div>
      {% else %}<p>No batches yet.</p>{% endfor %}
    </div>
    """
    return render_page("Lottery", body, currencies=CURRENCIES, count=LOTTERY_CARD_COUNT,
                        cost=LOTTERY_BATCH_COST, min_v=LOTTERY_CARD_MIN,
                        max_v=LOTTERY_CARD_MAX, batches=batches)


@app.route("/lottery/batch/<int:batch_id>")
@login_required
def lottery_batch(batch_id):
    user  = current_user()
    db    = get_db()
    batch = db.execute("SELECT * FROM lottery_batches WHERE id=?",(batch_id,)).fetchone()
    if not batch or (batch["user_id"]!=user["id"] and not user["is_admin"]): abort(404)
    cards = db.execute("SELECT * FROM lottery_cards WHERE batch_id=? ORDER BY slot_index",(batch_id,)).fetchall()
    revealed_total = sum(c["value"] for c in cards if c["revealed"])
    all_revealed   = all(c["revealed"] for c in cards)
    body = """
    <h1>Scratch Card Batch #{{ batch['id'] }}</h1>
    <p class="small">Currency: {{ batch['currency'] }} · Paid: {{ batch['cost_paid'] }} · {{ batch['created_at'][:10] }}</p>
    <div class="reward-grid">
      {% for c in cards %}
        {% if c['revealed'] %}
          <div class="reward-slot {% if c['value']<0 %}penalty{% endif %} done">
            #{{ c['slot_index']+1 }}<br>{{ '+' if c['value']>=0 else '' }}{{ c['value'] }}
          </div>
        {% else %}
          <form method="post" action="{{ url_for('lottery_scratch', batch_id=batch['id'], card_id=c['id']) }}">
            <button class="reward-slot next" type="submit" style="width:100%;cursor:pointer">
              #{{ c['slot_index']+1 }}<br>Scratch
            </button>
          </form>
        {% endif %}
      {% endfor %}
    </div>
    <div class="card" style="max-width:380px">
      <p>Revealed total: <b>{{ '+' if revealed_total>=0 else '' }}{{ revealed_total }} {{ batch['currency'] }}</b></p>
      {% if all_revealed %}<p class="small text-good">All cards revealed!</p>{% endif %}
    </div>
    <p><a href="{{ url_for('lottery') }}">← Back to Lottery</a></p>
    """
    return render_page("Scratch Cards", body, batch=batch, cards=cards,
                        revealed_total=revealed_total, all_revealed=all_revealed)


@app.route("/lottery/scratch/<int:batch_id>/<int:card_id>", methods=["POST"])
@login_required
def lottery_scratch(batch_id, card_id):
    user  = current_user()
    db    = get_db()
    batch = db.execute("SELECT * FROM lottery_batches WHERE id=?",(batch_id,)).fetchone()
    if not batch or batch["user_id"]!=user["id"]: abort(404)
    card = db.execute("SELECT * FROM lottery_cards WHERE id=? AND batch_id=?",(card_id,batch_id)).fetchone()
    if not card: abort(404)
    if not card["revealed"]:
        db.execute("UPDATE lottery_cards SET revealed=1 WHERE id=?",(card_id,))
        db.commit()
        v = card["value"]
        if v > 0:
            adjust_balance(user["id"],batch["currency"],v,
                           f"Lottery win batch#{batch_id} card#{card['slot_index']+1}")
            flash(f"Card #{card['slot_index']+1}: Won {v} {batch['currency']}! 🎉","success")
        elif v < 0:
            cur_amt = get_balances(user["id"])[batch["currency"]]
            loss    = -min(abs(v), cur_amt)
            if loss != 0:
                adjust_balance(user["id"],batch["currency"],loss,
                               f"Lottery loss batch#{batch_id} card#{card['slot_index']+1}")
            flash(f"Card #{card['slot_index']+1}: Lost {abs(loss)} {batch['currency']}.","error")
        else:
            flash(f"Card #{card['slot_index']+1}: Empty.","success")
    return redirect(url_for("lottery_batch", batch_id=batch_id))


"""
================================================================================
SECTION 16: INVESTMENT
================================================================================
"""

@app.route("/investment", methods=["GET","POST"])
@login_required
def investment():
    user = current_user()
    db   = get_db()

    if request.method == "POST":
        currency = request.form.get("currency")
        try:    amount = int(request.form.get("amount","0"))
        except: amount = 0
        if currency not in CURRENCIES or amount <= 0:
            flash("Enter a valid amount and currency.","error")
            return redirect(url_for("investment"))
        bal = get_balances(user["id"])
        if bal[currency] < amount:
            flash("Not enough balance.","error")
            return redirect(url_for("investment"))

        adjust_balance(user["id"],currency,-amount,"Investment stake")
        multiplier = round(random.uniform(INVEST_MIN_MULTIPLIER, INVEST_MAX_MULTIPLIER), 2)
        profit     = round(amount * multiplier)
        payout     = max(0, amount + profit)
        if payout > 0:
            adjust_balance(user["id"],currency,payout,f"Investment payout (x{multiplier})")
        db.execute("""INSERT INTO investments (user_id,currency,amount_staked,multiplier,payout,created_at)
                      VALUES (?,?,?,?,?,?)""",
                   (user["id"],currency,amount,multiplier,payout,datetime.utcnow().isoformat()))
        db.commit()
        net = payout - amount
        if net >= 0:
            flash(f"x{multiplier}: staked {amount}, got back {payout} (net +{net}) {currency}!","success")
        else:
            flash(f"x{multiplier}: staked {amount}, got back {payout} (net {net}) {currency}.","error")
        return redirect(url_for("investment"))

    history = db.execute("SELECT * FROM investments WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
                          (user["id"],)).fetchall()
    body = """
    <h1>📈 Investment</h1>
    <div class="card" style="max-width:420px">
      <p class="small">Stake any currency amount and instantly get a result between
        {{ min_m }}x and {{ max_m }}x. Payout never goes negative on your total balance.</p>
      <form method="post">
        <label>Currency</label>
        <select name="currency">
          {% for code, info in currencies.items() %}
            <option value="{{ code }}">{{ info['name'] }}</option>
          {% endfor %}
        </select>
        <label>Amount to invest</label>
        <input type="number" name="amount" min="1" required>
        <button class="btn btn-yellow" type="submit">Invest Now</button>
      </form>
    </div>
    <h2>Recent Investments</h2>
    <table>
      <tr><th>Date</th><th>Currency</th><th>Staked</th><th>Multiplier</th><th>Payout</th><th>Net</th></tr>
      {% for inv in history %}
        <tr>
          <td class="small">{{ inv['created_at'][:10] }}</td>
          <td>{{ inv['currency'] }}</td>
          <td>{{ inv['amount_staked'] }}</td>
          <td>x{{ inv['multiplier'] }}</td>
          <td>{{ inv['payout'] }}</td>
          <td class="{% if inv['payout']-inv['amount_staked']>=0 %}text-good{% else %}text-danger{% endif %}">
            {{ '+' if inv['payout']-inv['amount_staked']>=0 else '' }}{{ inv['payout']-inv['amount_staked'] }}
          </td>
        </tr>
      {% else %}<tr><td colspan="6" class="small">No investments yet.</td></tr>{% endfor %}
    </table>
    """
    return render_page("Investment", body, currencies=CURRENCIES, history=history,
                        min_m=INVEST_MIN_MULTIPLIER, max_m=INVEST_MAX_MULTIPLIER)


"""
================================================================================
SECTION 17: ASSET MARKET
================================================================================
"""

@app.route("/market")
@login_required
def asset_market():
    user = current_user()
    db   = get_db()
    for a in db.execute("SELECT * FROM assets").fetchall():
        pct = random.uniform(-ASSET_JITTER_PCT, ASSET_JITTER_PCT)
        db.execute("UPDATE assets SET current_price=? WHERE id=?",
                   (max(1, round(a["current_price"]*(1+pct))), a["id"]))
    db.commit()
    holdings    = get_asset_holdings(user["id"])
    neo_balance = get_balances(user["id"])["NEO"]
    body = """
    <h1>📊 Asset Market</h1>
    <p class="small">Prices fluctuate on every page load. Settled in Neo.
      Your Neo: <b style="color:var(--neon)">{{ neo_balance }}</b></p>
    <table>
      <tr><th>Asset</th><th>Price (Neo)</th><th>Owned</th><th>Buy</th><th>Sell</th></tr>
      {% for h in holdings %}
        <tr>
          <td>{{ h['name'] }} <span class="small">({{ h['symbol'] }})</span></td>
          <td>{{ h['current_price'] }}</td>
          <td>{{ h['quantity'] }}</td>
          <td>
            <form method="post" action="{{ url_for('market_buy', asset_id=h['id']) }}" style="display:flex;gap:4px">
              <input type="number" name="qty" min="1" value="1" style="width:64px;margin:0">
              <button class="btn btn-sm" type="submit">Buy</button>
            </form>
          </td>
          <td>
            <form method="post" action="{{ url_for('market_sell', asset_id=h['id']) }}" style="display:flex;gap:4px">
              <input type="number" name="qty" min="1" value="1" style="width:64px;margin:0">
              <button class="btn btn-sm btn-danger" type="submit" {% if h['quantity']==0 %}disabled{% endif %}>Sell</button>
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
    user  = current_user()
    db    = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone()
    if not asset: abort(404)
    try:    qty = int(request.form.get("qty","0"))
    except: qty = 0
    if qty <= 0:
        flash("Enter a valid quantity.","error")
        return redirect(url_for("asset_market"))
    cost = asset["current_price"] * qty
    bal  = get_balances(user["id"])
    if bal["NEO"] < cost:
        flash(f"Need {cost} Neo to buy {qty} x {asset['name']}.","error")
        return redirect(url_for("asset_market"))
    adjust_balance(user["id"],"NEO",-cost,f"Bought {qty} x {asset['name']}")
    row = db.execute("SELECT quantity FROM asset_holdings WHERE user_id=? AND asset_id=?",
                      (user["id"],asset_id)).fetchone()
    if row:
        db.execute("UPDATE asset_holdings SET quantity=quantity+? WHERE user_id=? AND asset_id=?",
                   (qty,user["id"],asset_id))
    else:
        db.execute("INSERT INTO asset_holdings (user_id,asset_id,quantity) VALUES (?,?,?)",
                   (user["id"],asset_id,qty))
    db.commit()
    flash(f"Bought {qty} x {asset['name']} for {cost} Neo.","success")
    return redirect(url_for("asset_market"))


@app.route("/market/sell/<int:asset_id>", methods=["POST"])
@login_required
def market_sell(asset_id):
    user  = current_user()
    db    = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone()
    if not asset: abort(404)
    try:    qty = int(request.form.get("qty","0"))
    except: qty = 0
    row   = db.execute("SELECT quantity FROM asset_holdings WHERE user_id=? AND asset_id=?",
                        (user["id"],asset_id)).fetchone()
    owned = row["quantity"] if row else 0
    if qty <= 0 or qty > owned:
        flash("Invalid sell quantity.","error")
        return redirect(url_for("asset_market"))
    proceeds = asset["current_price"] * qty
    db.execute("UPDATE asset_holdings SET quantity=quantity-? WHERE user_id=? AND asset_id=?",
               (qty,user["id"],asset_id))
    adjust_balance(user["id"],"NEO",proceeds,f"Sold {qty} x {asset['name']}")
    db.commit()
    flash(f"Sold {qty} x {asset['name']} for {proceeds} Neo.","success")
    return redirect(url_for("asset_market"))


"""
================================================================================
SECTION 18: ADMIN PANEL
================================================================================
"""

@app.route("/admin")
@admin_required
def admin_panel():
    db    = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    games = db.execute("""SELECT g.*,u.display_name AS dev_name FROM games g
                           JOIN users u ON g.developer_id=u.id ORDER BY g.created_at DESC""").fetchall()
    post_count   = db.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"]
    msg_count    = db.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    body = """
    <h1>Admin Panel</h1>
    <div class="grid" style="margin-bottom:14px">
      <div class="card"><h3>Users</h3><b style="font-size:24px;color:var(--neon)">{{ users|length }}</b></div>
      <div class="card"><h3>Games</h3><b style="font-size:24px;color:var(--neon)">{{ games|length }}</b></div>
      <div class="card"><h3>Posts</h3><b style="font-size:24px;color:var(--neon)">{{ post_count }}</b></div>
      <div class="card"><h3>Messages</h3><b style="font-size:24px;color:var(--neon)">{{ msg_count }}</b></div>
    </div>
    <div class="card">
      <h3>Users</h3>
      <table>
        <tr><th>Username</th><th>Level</th><th>Roles</th><th>Joined</th><th>Action</th></tr>
        {% for u in users %}
          <tr>
            <td><a href="{{ url_for('profile', username=u['username']) }}">{{ u['username'] }}</a></td>
            <td>{{ u['level'] }}</td>
            <td>{% if u['is_admin'] %}Admin {% endif %}{% if u['is_developer'] %}Dev{% endif %}</td>
            <td class="small">{{ u['created_at'][:10] }}</td>
            <td>
              <form method="post" action="{{ url_for('admin_toggle_admin', user_id=u['id']) }}" style="display:inline">
                <button class="btn btn-sm" type="submit">Toggle Admin</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    <div class="card">
      <h3>Games</h3>
      <table>
        <tr><th>Title</th><th>Dev</th><th>Category</th><th>Plays</th><th>Price</th><th>Action</th></tr>
        {% for g in games %}
          <tr>
            <td>{{ g['title'] }}</td>
            <td>{{ g['dev_name'] }}</td>
            <td>{{ g['category'] }}</td>
            <td>{{ g['play_count'] }}</td>
            <td>{{ g['price'] }} {{ g['price_currency'] }}</td>
            <td>
              <form method="post" action="{{ url_for('admin_delete_game', game_id=g['id']) }}" style="display:inline">
                <button class="btn btn-danger btn-sm" type="submit">Remove</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_page("Admin", body, users=users, games=games,
                        post_count=post_count, msg_count=msg_count)


@app.route("/admin/users/<int:user_id>/toggle_admin", methods=["POST"])
@admin_required
def admin_toggle_admin(user_id):
    db = get_db()
    u  = db.execute("SELECT is_admin FROM users WHERE id=?",(user_id,)).fetchone()
    if u:
        db.execute("UPDATE users SET is_admin=? WHERE id=?",(0 if u["is_admin"] else 1, user_id))
        db.commit()
        flash("User updated.","success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/games/<int:game_id>/delete", methods=["POST"])
@admin_required
def admin_delete_game(game_id):
    db   = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?",(game_id,)).fetchone()
    if game:
        path = os.path.join(UPLOAD_DIR, game["filename"])
        if os.path.exists(path): os.remove(path)
        db.execute("DELETE FROM purchases WHERE game_id=?",(game_id,))
        db.execute("DELETE FROM game_rewards WHERE game_id=?",(game_id,))
        db.execute("DELETE FROM games WHERE id=?",(game_id,))
        db.commit()
        flash("Game removed.","success")
    return redirect(url_for("admin_panel"))


"""
================================================================================
SECTION 19: ERROR HANDLERS & STARTUP
================================================================================
"""

@app.errorhandler(403)
def forbidden(e):
    return render_page("Forbidden",
        "<div class='card'><h2>403 — Forbidden</h2><p>You don't have access to this page.</p></div>"), 403

@app.errorhandler(404)
def not_found(e):
    return render_page("Not Found",
        "<div class='card'><h2>404 — Not Found</h2><p>That page doesn't exist.</p></div>"), 404


if __name__ == "__main__":
    init_db()
    seed_admin_and_demo()
    seed_assets()
    seed_demo_social_users()
    print("NeoVerse v2.0 running at http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
