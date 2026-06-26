"""
================================================================================
 NEOVERSE - Cyberpunk Virtual Universe Platform v3.0 - ADMIN EDITION
================================================================================
Single-file Flask + SQLite application with ADVANCED ADMIN SYSTEM.

RUN:
    pip install flask --break-system-packages
    python app.py
    -> http://127.0.0.1:5000

ADMIN ACCOUNT: username: admin, password: admin123
================================================================================
SECTION 1: IMPORTS & CONFIG
================================================================================
"""
import os
import sqlite3
import random
import secrets
import string
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, g,
    render_template_string, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DB_PATH          = os.path.join(BASE_DIR, "neoverse.db")
UPLOAD_DIR       = os.path.join(BASE_DIR, "uploads", "games")
POSTS_UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "posts")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(POSTS_UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("NEOVERSE_SECRET", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

CURRENCIES = {
    "NEO":          {"name": "Neo",          "master": True},
    "CYBER_DOLLAR": {"name": "Cyber Dollar", "rate_from_neo": 10},
    "QUANTUM_COIN": {"name": "Quantum Coin", "rate_from_neo": 5},
    "ARC_TOKEN":    {"name": "Arc Token",    "rate_from_neo": 8},
    "NANO_UNIT":    {"name": "Nano Unit",    "rate_from_neo": 20},
}
OTHER_CURRENCIES = [c for c in CURRENCIES if c != "NEO"]

# Admin roles with permissions (hierarchical)
ADMIN_ROLES = {
    "super_admin": {
        "label": "Super Admin",
        "permissions": ["all"],
        "color": "#ff4d6d"
    },
    "senior_admin": {
        "label": "Senior Admin",
        "permissions": ["user_manage", "economy_manage", "content_moderate",
                        "chat_moderate", "game_manage", "view_analytics",
                        "manage_settings"],
        "color": "#ff7a9f"
    },
    "moderator": {
        "label": "Moderator",
        "permissions": ["content_moderate", "chat_moderate", "user_manage_basic"],
        "color": "#00e5ff"
    },
    "economy_manager": {
        "label": "Economy Manager",
        # FIX: added game_manage so economy_manager can also manage games
        "permissions": ["economy_manage", "view_analytics", "game_manage"],
        "color": "#ffe066"
    },
    "content_moderator": {
        "label": "Content Moderator",
        "permissions": ["content_moderate"],
        "color": "#34f5b0"
    },
    "support_staff": {
        "label": "Support Staff",
        "permissions": ["user_manage_basic", "view_analytics"],
        "color": "#b14dff"
    }
}

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
    "Arcade", "Racing", "Action", "RPG", "Puzzle",
    "Adventure", "Strategy", "Simulation", "Educational", "Casual",
]

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
        admin_role TEXT,
        daily_streak INTEGER NOT NULL DEFAULT 0,
        last_daily_claim TEXT,
        last_seen TEXT,
        is_banned INTEGER NOT NULL DEFAULT 0,
        is_suspended INTEGER NOT NULL DEFAULT 0,
        is_muted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS balances (
        user_id INTEGER NOT NULL,
        currency TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        is_frozen INTEGER NOT NULL DEFAULT 0,
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
        is_hidden INTEGER NOT NULL DEFAULT 0,
        is_featured INTEGER NOT NULL DEFAULT 0,
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

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        post_type TEXT NOT NULL DEFAULT 'text',
        media_filename TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        is_hidden INTEGER NOT NULL DEFAULT 0,
        is_pinned INTEGER NOT NULL DEFAULT 0,
        is_featured INTEGER NOT NULL DEFAULT 0,
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
        is_hidden INTEGER NOT NULL DEFAULT 0,
        is_locked INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (post_id) REFERENCES posts(id)
    );

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

    CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        target_user_id INTEGER,
        target_type TEXT,
        target_id INTEGER,
        previous_value TEXT,
        new_value TEXT,
        reason TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (admin_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_by_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        FOREIGN KEY (created_by_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_by_id INTEGER,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (updated_by_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS site_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_by_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        reward_currency TEXT,
        reward_amount INTEGER,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        FOREIGN KEY (created_by_id) REFERENCES users(id)
    );

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
    CREATE INDEX IF NOT EXISTS idx_admin_logs_admin    ON admin_logs(admin_id);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_target   ON admin_logs(target_user_id);
    CREATE INDEX IF NOT EXISTS idx_admin_logs_created  ON admin_logs(created_at);
    """)
    conn.commit()

    # Non-destructive column migrations
    migrations = [
        "ALTER TABLE users ADD COLUMN last_seen TEXT",
        "ALTER TABLE games ADD COLUMN price_currency TEXT NOT NULL DEFAULT 'NEO'",
        "ALTER TABLE users ADD COLUMN admin_role TEXT",
        "ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_suspended INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_muted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE balances ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE posts ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE comments ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE comments ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE site_events ADD COLUMN created_by_id INTEGER NOT NULL DEFAULT 1",
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
                               avatar_seed,xp,level,is_admin,is_developer,admin_role,
                               daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,?,?,?,?,1,1,'super_admin',0,NULL,?)
        """, ("admin", "admin@neoverse.local", generate_password_hash(pw),
              "NeoVerse Admin", "System administrator account.", "admin",
              0, 1, datetime.utcnow().isoformat()))
        admin_id = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,'NEO',100000)", (admin_id,))
        for cur in OTHER_CURRENCIES:
            conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,0)", (admin_id, cur))
        conn.commit()
        print("=" * 60)
        print(" NEOVERSE v3.0: admin account created")
        print(" username: admin")
        print(" password: admin123")
        print("=" * 60)

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
        ("nova", "nova@neoverse.local", "Nova Sek"),
        ("ghostwire", "ghostwire@neoverse.local", "Ghostwire"),
        ("kira", "kira@neoverse.local", "Kira Vance"),
    ]
    for username, email, display_name in demo_users:
        if conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
            continue
        avatar_seed = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        conn.execute("""
            INSERT INTO users (username,email,password_hash,display_name,bio,avatar_seed,
                               xp,level,is_admin,is_developer,admin_role,daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,'',?,0,1,0,0,NULL,0,NULL,?)
        """, (username, email, generate_password_hash("password123"),
              display_name, avatar_seed, datetime.utcnow().isoformat()))
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        for cur in CURRENCIES:
            conn.execute("INSERT INTO balances (user_id,currency,amount) VALUES (?,?,?)",
                         (uid, cur, 200 if cur == "NEO" else 0))
        conn.commit()
    conn.close()


"""
================================================================================
SECTION 3: ADMIN HELPERS & PERMISSION SYSTEM
================================================================================
"""

def admin_log(action, target_user_id=None, target_type=None, target_id=None,
              previous_value=None, new_value=None, reason=None):
    """Log all admin actions for audit trail."""
    me = current_user()
    if not me:
        return
    try:
        get_db().execute("""
            INSERT INTO admin_logs (admin_id,action,target_user_id,target_type,target_id,
                                    previous_value,new_value,reason,ip_address,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (me["id"], action, target_user_id, target_type, target_id,
              previous_value, new_value, reason,
              request.remote_addr, datetime.utcnow().isoformat()))
        get_db().commit()
    except Exception:
        pass


def has_permission(user, permission):
    """Check if user has a specific permission."""
    if not user or not user["is_admin"]:
        return False

    role = user["admin_role"]
    if not role:
        # Legacy is_admin=1 without role → treat as Super Admin
        return True

    role_data = ADMIN_ROLES.get(role, {})
    permissions = role_data.get("permissions", [])

    if "all" in permissions:
        return True
    return permission in permissions


def check_permission(permission):
    """Decorator to check admin permission."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            u = current_user()
            if not u or not has_permission(u, permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


"""
================================================================================
SECTION 4: HELPERS
================================================================================
"""

def current_user():
    if "user_id" not in session:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()


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


# ── Balance / XP ──────────────────────────────────────────────────────────────

def get_balances(user_id):
    rows = get_db().execute(
        "SELECT currency,amount FROM balances WHERE user_id=?", (user_id,)
    ).fetchall()
    bal = {c: 0 for c in CURRENCIES}
    for r in rows:
        if r["currency"] in bal:
            bal[r["currency"]] = r["amount"]
    return bal


def adjust_balance(user_id, currency, delta, note=""):
    db = get_db()
    row = db.execute(
        "SELECT amount FROM balances WHERE user_id=? AND currency=?", (user_id, currency)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO balances (user_id,currency,amount) VALUES (?,?,0)", (user_id, currency)
        )
        current = 0
    else:
        current = row["amount"]
    new_amount = current + delta
    if new_amount < 0:
        raise ValueError("Insufficient balance")
    db.execute(
        "UPDATE balances SET amount=? WHERE user_id=? AND currency=?",
        (new_amount, user_id, currency)
    )
    db.execute(
        """INSERT INTO transactions (user_id,type,currency,amount,note,created_at)
           VALUES (?,?,?,?,?,?)""",
        (user_id, "credit" if delta >= 0 else "debit", currency, delta, note,
         datetime.utcnow().isoformat())
    )
    db.commit()


def grant_xp(user_id, amount):
    db = get_db()
    u = db.execute("SELECT xp,level FROM users WHERE id=?", (user_id,)).fetchone()
    new_xp = u["xp"] + amount
    new_level = min(1000, 1 + new_xp // 500)
    leveled_up = new_level > u["level"]
    db.execute("UPDATE users SET xp=?,level=? WHERE id=?", (new_xp, new_level, user_id))
    db.commit()
    if leveled_up:
        adjust_balance(user_id, "NEO", new_level * 10, f"Level up bonus (level {new_level})")
    return leveled_up, new_level


# ── Infinite daily reward ─────────────────────────────────────────────────────

def daily_reward_amount(streak):
    """streak is 0-based (0 = first ever claim). Returns Neo to award."""
    return DAILY_BASE_REWARD + streak * DAILY_STREAK_BONUS


def daily_reward_status(user):
    today = date.today()
    last = user["last_daily_claim"]
    last_date = date.fromisoformat(last) if last else None
    can_claim = (last_date is None) or (last_date < today)
    streak = user["daily_streak"]
    if last_date is not None and (today - last_date).days > 1:
        streak = 0
    return can_claim, streak


# ── Game play rewards ─────────────────────────────────────────────────────────

def get_game_plays_today(user_id, game_id):
    today = date.today().isoformat()
    row = get_db().execute(
        "SELECT plays_today FROM game_rewards WHERE user_id=? AND game_id=? AND play_date=?",
        (user_id, game_id, today)
    ).fetchone()
    return row["plays_today"] if row else 0


def record_game_play_reward(user_id, game_id):
    """Returns (neo_earned, xp_earned). 0,0 if daily limit reached."""
    today = date.today().isoformat()
    plays = get_game_plays_today(user_id, game_id)
    if plays >= GAME_DAILY_PLAY_LIMIT:
        return 0, 0
    db = get_db()
    if plays > 0:
        db.execute(
            "UPDATE game_rewards SET plays_today=plays_today+1 WHERE user_id=? AND game_id=? AND play_date=?",
            (user_id, game_id, today)
        )
    else:
        db.execute(
            "INSERT INTO game_rewards (user_id,game_id,play_date,plays_today) VALUES (?,?,?,1)",
            (user_id, game_id, today)
        )
    db.commit()
    adjust_balance(user_id, "NEO", GAME_PLAY_NEO_REWARD, "Game play reward")
    grant_xp(user_id, GAME_PLAY_XP_REWARD)
    return GAME_PLAY_NEO_REWARD, GAME_PLAY_XP_REWARD


# ── Social helpers ────────────────────────────────────────────────────────────

def friend_pair(a, b):
    return (a, b) if a < b else (b, a)


def is_following(follower_id, following_id):
    return get_db().execute(
        "SELECT 1 FROM followers WHERE follower_id=? AND following_id=?",
        (follower_id, following_id)
    ).fetchone() is not None


def is_friend(a, b):
    x, y = friend_pair(a, b)
    return get_db().execute(
        "SELECT 1 FROM friends WHERE user_id_a=? AND user_id_b=?", (x, y)
    ).fetchone() is not None


def follower_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=?", (user_id,)
    ).fetchone()["c"]


def following_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM followers WHERE follower_id=?", (user_id,)
    ).fetchone()["c"]


def friend_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM friends WHERE user_id_a=? OR user_id_b=?",
        (user_id, user_id)
    ).fetchone()["c"]


def social_counts(user_id):
    return {
        "followers": follower_count(user_id),
        "following": following_count(user_id),
        "friends":   friend_count(user_id),
    }


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
    try:
        get_db().execute(
            "INSERT INTO notifications (user_id,type,message,link,is_read,created_at) VALUES (?,?,?,?,0,?)",
            (user_id, notif_type, message, link, datetime.utcnow().isoformat())
        )
        get_db().commit()
    except Exception:
        pass


def unread_notification_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (user_id,)
    ).fetchone()["c"]


def unread_message_count(user_id):
    return get_db().execute(
        "SELECT COUNT(*) AS c FROM messages WHERE receiver_id=? AND is_read=0 AND is_deleted=0",
        (user_id,)
    ).fetchone()["c"]


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
SECTION 5: CSS & BASE TEMPLATE
================================================================================
"""

BASE_CSS = """
:root{
  --bg-deep:#05060f; --bg-panel:rgba(10,14,32,0.72); --neon:#00bfff; --neon-soft:#00bfff44;
  --accent-yellow:#ffd700; --text:#d8f4ff; --text-dim:#7a8aa0;
  --danger:#ff4d6d; --good:#34f5b0; --neon-purple:#b14dff;
  --neon-purple-soft:#b14dff44; --card-shadow:0 0 28px -8px #00bfff33;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  min-height:100vh; font-family:'Segoe UI',system-ui,sans-serif; color:var(--text);
  background:radial-gradient(circle at 20% 20%,#0d1442 0%,#05060f 45%,#03040a 100%);
  background-attachment:fixed;
}
a{color:var(--neon);text-decoration:none}
a:hover{opacity:.85}
.small{font-size:12px;color:var(--text-dim)}

.admin-wrap{display:grid;grid-template-columns:240px 1fr;gap:14px;min-height:calc(100vh - 60px)}
.admin-sidebar{
  background:rgba(10,14,32,0.5);border-right:1px solid var(--neon-soft);
  padding:14px 0;max-height:calc(100vh - 60px);overflow-y:auto;position:sticky;top:60px;
}
.admin-sidebar a,.admin-sidebar button{
  display:block;width:100%;text-align:left;padding:10px 16px;
  border:none;background:none;color:var(--text);font-size:13px;
  cursor:pointer;transition:.15s;border-left:3px solid transparent;
}
.admin-sidebar a:hover,.admin-sidebar button:hover{
  background:rgba(0,191,255,.1);border-left-color:var(--neon);color:var(--neon);
}
.admin-sidebar a.active,.admin-sidebar button.active{
  background:rgba(0,191,255,.15);border-left-color:var(--neon);
  color:var(--neon);font-weight:600;
}
.admin-section-label{
  padding:12px 16px 6px;font-size:11px;color:var(--text-dim);
  text-transform:uppercase;letter-spacing:.8px;font-weight:600;
}
.admin-main{padding:14px;overflow-y:auto}

.admin-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
.admin-stat-card{
  background:linear-gradient(135deg,rgba(0,191,255,.1),rgba(177,77,255,.05));
  border:1px solid var(--neon-soft);border-radius:12px;padding:16px;
  text-align:center;
}
.admin-stat-card b{display:block;font-size:28px;color:var(--neon);margin-bottom:6px}
.admin-stat-card span{font-size:11px;color:var(--text-dim);text-transform:uppercase}

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

.wrap{max-width:1200px;margin:0 auto;padding:20px 16px}

.card{
  background:var(--bg-panel);border:1px solid var(--neon-soft);border-radius:14px;
  padding:18px;margin-bottom:14px;backdrop-filter:blur(8px);
  box-shadow:var(--card-shadow);
}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
h1{font-size:26px;color:var(--text);text-shadow:0 0 12px var(--neon-soft);margin-bottom:12px}
h2{font-size:18px;color:var(--text);margin-bottom:10px}
h3{font-size:15px;color:var(--text);margin-bottom:8px}

.btn{
  display:inline-block;background:linear-gradient(135deg,#0a1640,#0d2050);
  color:var(--neon);border:1px solid var(--neon);padding:8px 16px;border-radius:8px;
  cursor:pointer;font-weight:600;font-size:12px;letter-spacing:.4px;
  transition:.15s;text-align:center;
}
.btn:hover{box-shadow:0 0 14px var(--neon);transform:translateY(-1px)}
.btn-yellow{border-color:var(--accent-yellow);color:var(--accent-yellow)}
.btn-yellow:hover{box-shadow:0 0 14px var(--accent-yellow)}
.btn-danger{border-color:var(--danger);color:var(--danger)}
.btn-danger:hover{box-shadow:0 0 14px var(--danger)}
.btn-good{border-color:var(--good);color:var(--good)}
.btn-good:hover{box-shadow:0 0 14px var(--good)}
.btn-sm{padding:5px 10px;font-size:11px}

input,textarea,select{
  width:100%;padding:8px 10px;margin:4px 0 10px;border-radius:8px;
  border:1px solid #1c2a55;background:#070b1d;color:var(--text);font-size:13px;
}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--neon)}
label{font-size:12px;color:var(--text-dim);display:block;margin-bottom:3px}

.flash{padding:8px 12px;border-radius:8px;margin-bottom:12px;font-size:12px}
.flash-error{background:#3a0f1a;border:1px solid var(--danger);color:#ffb3c1}
.flash-success{background:#0d2e23;border:1px solid var(--good);color:#bdfde6}

table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:8px;border-bottom:1px solid #14204a}
th{color:var(--text-dim);font-weight:600;background:rgba(0,0,0,.2)}
tr:hover{background:rgba(0,191,255,.05)}

.badge{display:inline-block;padding:2px 7px;border-radius:14px;font-size:10px;
       border:1px solid var(--neon-soft)}
.badge-yellow{border-color:var(--accent-yellow);color:var(--accent-yellow)}
.badge-danger{border-color:var(--danger);color:var(--danger)}
.badge-good{border-color:var(--good);color:var(--good)}

.status-online{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good)}
.status-offline{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--text-dim)}

@media(max-width:900px){
  .admin-wrap{grid-template-columns:200px 1fr}
  .admin-sidebar{font-size:12px}
}
@media(max-width:768px){
  .admin-wrap{grid-template-columns:1fr}
  .admin-sidebar{display:none}
  table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .admin-stats{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:600px){
  .wrap{padding:10px 8px}
  h1{font-size:18px}
  .card{padding:12px;border-radius:10px}
}
"""

# FIX: Moved admin sidebar to a Jinja2 template macro instead of a Python
# f-string helper, so url_for() resolves correctly at render time.
ADMIN_SIDEBAR_TEMPLATE = """
<div class="admin-sidebar">
  <div class="admin-section-label">Admin Menu</div>
  <a href="{{ url_for('admin_dashboard') }}"   {% if active=='admin_dashboard'   %}class="active"{% endif %}>📊 Dashboard</a>
  <a href="{{ url_for('admin_users') }}"        {% if active=='admin_users'        %}class="active"{% endif %}>👥 User Management</a>
  <a href="{{ url_for('admin_economy') }}"      {% if active=='admin_economy'      %}class="active"{% endif %}>💰 Economy Control</a>
  <a href="{{ url_for('admin_transactions') }}" {% if active=='admin_transactions' %}class="active"{% endif %}>📈 Transactions</a>
  <a href="{{ url_for('admin_assets') }}"       {% if active=='admin_assets'       %}class="active"{% endif %}>📦 Asset Management</a>
  <a href="{{ url_for('admin_posts') }}"        {% if active=='admin_posts'        %}class="active"{% endif %}>📝 Post Moderation</a>
  <a href="{{ url_for('admin_games') }}"        {% if active=='admin_games'        %}class="active"{% endif %}>🎮 Game Management</a>
  <a href="{{ url_for('admin_audit_log') }}"    {% if active=='admin_audit_log'    %}class="active"{% endif %}>📋 Audit Log</a>
  <a href="{{ url_for('admin_analytics') }}"    {% if active=='admin_analytics'    %}class="active"{% endif %}>📊 Analytics</a>
  <a href="{{ url_for('admin_settings') }}"     {% if active=='admin_settings'     %}class="active"{% endif %}>⚙ Settings</a>
</div>
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
  <div class="nav-right">
    {% if user %}
      <a href="{{ url_for('index') }}">Dashboard</a>
      <a href="{{ url_for('feed') }}">Feed</a>
      <a href="{{ url_for('games_list') }}">Games</a>
      <a href="{{ url_for('wallet') }}">Wallet</a>
      <a href="{{ url_for('daily_reward') }}">Daily</a>
      <a href="{{ url_for('messages_list') }}">💬
        {% if unread_msg_count and unread_msg_count > 0 %}
          <span class="nav-badge">{{ unread_msg_count }}</span>
        {% endif %}
      </a>
      <a href="{{ url_for('notifications_page') }}">🔔
        {% if unread_notif_count and unread_notif_count > 0 %}
          <span class="nav-badge">{{ unread_notif_count }}</span>
        {% endif %}
      </a>
      <a href="{{ url_for('profile', username=user['username']) }}">{{ user['display_name'] }}</a>
      <a href="{{ url_for('settings_page') }}">⚙</a>
      {% if user['is_admin'] %}
        <a href="{{ url_for('admin_dashboard') }}" style="color:var(--accent-yellow)">👑 Admin</a>
      {% endif %}
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
    umc = unread_message_count(u["id"]) if u else 0
    unc = unread_notification_count(u["id"]) if u else 0
    # FIX: expose ADMIN_SIDEBAR_TEMPLATE as a variable so admin pages can
    # include it via Jinja2 rendering rather than relying on the broken
    # f-string _admin_sidebar() helper.
    body = render_template_string(
        body_html,
        user=u,
        unread_msg_count=umc,
        unread_notif_count=unc,
        admin_sidebar_tpl=ADMIN_SIDEBAR_TEMPLATE,
        **extra
    )
    return render_template_string(
        NAV_TEMPLATE,
        title=title,
        css=BASE_CSS,
        body=body,
        user=u,
        unread_msg_count=umc,
        unread_notif_count=unc
    )


@app.template_filter("initial")
def initial_filter(name):
    return (name or "?")[:1].upper()


@app.template_filter("admin_role_label")
def admin_role_label_filter(role):
    if not role:
        return "User"
    return ADMIN_ROLES.get(role, {}).get("label", role)


"""
================================================================================
SECTION 6: AUTH ROUTES
================================================================================
"""

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username     = request.form.get("username", "").strip().lower()
        email        = request.form.get("email", "").strip().lower()
        password     = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip() or username

        if not (3 <= len(username) <= 20) or not username.isalnum():
            flash("Username must be 3-20 alphanumeric characters.", "error")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("register"))

        db = get_db()
        if db.execute(
            "SELECT 1 FROM users WHERE username=? OR email=?", (username, email)
        ).fetchone():
            flash("Username or email already in use.", "error")
            return redirect(url_for("register"))

        avatar_seed = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        db.execute("""
            INSERT INTO users (username,email,password_hash,display_name,bio,avatar_seed,
                               xp,level,is_admin,is_developer,admin_role,daily_streak,last_daily_claim,created_at)
            VALUES (?,?,?,?,?,?,0,1,0,0,NULL,0,NULL,?)
        """, (username, email, generate_password_hash(password), display_name, "",
              avatar_seed, datetime.utcnow().isoformat()))
        db.commit()
        uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        for cur in CURRENCIES:
            db.execute(
                "INSERT INTO balances (user_id,currency,amount) VALUES (?,?,?)",
                (uid, cur, 200 if cur == "NEO" else 0)
            )
        db.commit()
        session["user_id"] = uid
        flash("Welcome to NeoVerse! You received 200 Neo to get started.", "success")
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            if user["is_banned"]:
                flash("This account has been banned.", "error")
                return redirect(url_for("login"))
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['display_name']}.", "success")
            return redirect(url_for("index"))
        flash("Invalid username or password.", "error")
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
    flash("Logged out.", "success")
    return redirect(url_for("login"))


"""
================================================================================
SECTION 7: DASHBOARD
================================================================================
"""

@app.route("/")
@login_required
def index():
    user = current_user()
    bal  = get_balances(user["id"])
    can_claim, streak = daily_reward_status(user)
    db = get_db()

    trending_games = db.execute("""
        SELECT g.*,u.display_name AS dev_name FROM games g
        JOIN users u ON g.developer_id=u.id WHERE g.is_hidden=0
        ORDER BY g.play_count DESC LIMIT 4
    """).fetchall()

    richest = db.execute("""
        SELECT u.username,u.display_name,b.amount FROM balances b
        JOIN users u ON u.id=b.user_id
        WHERE b.currency='NEO' AND u.is_banned=0 ORDER BY b.amount DESC LIMIT 5
    """).fetchall()

    counts      = social_counts(user["id"])
    unread_msgs = unread_message_count(user["id"])
    unread_notifs = unread_notification_count(user["id"])

    body = """
    <h1>Welcome, {{ user['display_name'] }} ⚡</h1>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div class="card">
        <h3>Level {{ user['level'] }}</h3>
        <p style="font-size:12px;color:var(--text-dim)">{{ user['xp'] }} XP</p>
        <span class="badge badge-yellow">{{ bal['NEO'] }} Neo</span>
      </div>
      <div class="card">
        <h3>Daily Reward</h3>
        <p style="font-size:12px">Streak: <b>{{ streak }}</b></p>
        {% if can_claim %}
          <a class="btn btn-yellow btn-sm" href="{{ url_for('daily_reward') }}">Claim ✦</a>
        {% else %}
          <p class="small">Claimed ✓</p>
        {% endif %}
      </div>
      <div class="card">
        <h3>Friends</h3>
        <b style="color:var(--neon)">{{ counts['friends'] }}</b>
        <p class="small">Followers: {{ counts['followers'] }}</p>
      </div>
      <div class="card">
        <h3>Inbox</h3>
        {% if unread_msgs > 0 %}
          <span class="badge">{{ unread_msgs }} msg</span>
        {% endif %}
        {% if unread_notifs > 0 %}
          <span class="badge badge-yellow">{{ unread_notifs }} notif</span>
        {% endif %}
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
      <div>
        <h2>🔥 Trending Games</h2>
        {% for game in trending_games %}
          <div class="card" style="padding:10px;margin-bottom:8px">
            <b>{{ game['title'] }}</b>
            <div class="small">{{ game['play_count'] }} plays · {{ game['dev_name'] }}</div>
            <a class="btn btn-sm" style="margin-top:6px" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
          </div>
        {% endfor %}
      </div>
      <div>
        <h2>👑 Leaderboard</h2>
        <div class="card">
          {% for r in richest %}
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #14204a;font-size:12px">
              <a href="{{ url_for('profile', username=r['username']) }}">{{ r['display_name'] }}</a>
              <b>{{ r['amount'] }} Neo</b>
            </div>
          {% endfor %}
        </div>
      </div>
    </div>
    """
    return render_page("Dashboard", body, bal=bal, can_claim=can_claim, streak=streak,
                       counts=counts, trending_games=trending_games, richest=richest,
                       unread_msgs=unread_msgs, unread_notifs=unread_notifs)


"""
================================================================================
SECTION 8: PROFILE & SOCIAL
================================================================================
"""

@app.route("/profile/<username>")
@login_required
def profile(username):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        abort(404)
    me = current_user()
    is_self = me["username"] == username

    if target["is_banned"] and not me["is_admin"]:
        abort(404)

    counts         = social_counts(target["id"])
    following_them = is_following(me["id"], target["id"])
    they_follow_me = is_following(target["id"], me["id"])
    are_friends    = is_friend(me["id"], target["id"])
    online         = is_online(target["last_seen"])

    user_posts = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id AND c.is_hidden=0) AS comment_count
        FROM posts p WHERE p.user_id=? AND p.is_hidden=0 ORDER BY p.created_at DESC LIMIT 10
    """, (target["id"],)).fetchall()

    body = """
    <div class="card">
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div style="width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,var(--neon),var(--neon-purple));
                    display:flex;align-items:center;justify-content:center;color:#05060f;font-weight:800;flex-shrink:0">
          {{ target['display_name']|initial }}
        </div>
        <div style="flex:1">
          <h1 style="margin:0">{{ target['display_name'] }}</h1>
          <p style="font-size:12px;color:var(--text-dim)">@{{ target['username'] }}</p>
          <div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">
            <span class="badge">Level {{ target['level'] }}</span>
            {% if target['is_developer'] %}<span class="badge badge-yellow">Dev</span>{% endif %}
            {% if target['is_admin'] %}<span class="badge badge-danger">Admin</span>{% endif %}
            {% if online %}<span class="badge badge-good">● Online</span>{% endif %}
          </div>
        </div>
      </div>
      {% if not is_self %}
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
        {% if following_them %}
          <form method="post" action="{{ url_for('unfollow_user', username=target['username']) }}" style="display:inline">
            <button class="btn btn-sm" type="submit">Unfollow</button>
          </form>
        {% else %}
          <form method="post" action="{{ url_for('follow_user', username=target['username']) }}" style="display:inline">
            <button class="btn btn-yellow btn-sm" type="submit">Follow</button>
          </form>
        {% endif %}
        <a class="btn btn-sm" href="{{ url_for('chat_page', user_id=target['id']) }}">💬 Message</a>
      </div>
      {% endif %}
    </div>

    <h2>Posts ({{ user_posts|length }})</h2>
    {% for post in user_posts %}
      <div class="card" style="margin-bottom:10px">
        <p style="white-space:pre-wrap">{{ post['content'][:200] }}</p>
        <div style="font-size:11px;color:var(--text-dim)">
          {{ post['created_at'][:16].replace('T',' ') }}
        </div>
      </div>
    {% else %}
      <p class="small">No posts yet.</p>
    {% endfor %}
    """
    return render_page(target["display_name"], body, target=target, is_self=is_self,
                       counts=counts, following_them=following_them,
                       they_follow_me=they_follow_me, are_friends=are_friends,
                       online=online, user_posts=user_posts)


@app.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile():
    user = current_user()
    db   = get_db()
    db.execute("UPDATE users SET display_name=?,bio=? WHERE id=?",
               (request.form.get("display_name", user["display_name"]).strip()[:40],
                request.form.get("bio", "").strip()[:300],
                user["id"]))
    db.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("profile", username=user["username"]))


@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow_user(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        abort(404)
    if target["id"] == me["id"]:
        flash("You can't follow yourself.", "error")
        return redirect(url_for("profile", username=username))
    if not is_following(me["id"], target["id"]):
        db.execute(
            "INSERT INTO followers (follower_id,following_id,created_at) VALUES (?,?,?)",
            (me["id"], target["id"], datetime.utcnow().isoformat())
        )
        db.commit()
        create_notification(target["id"], "follow",
                            f"{me['display_name']} started following you.",
                            url_for("profile", username=me["username"]))
        flash(f"You are now following {target['display_name']}.", "success")
    return redirect(url_for("profile", username=username))


@app.route("/unfollow/<username>", methods=["POST"])
@login_required
def unfollow_user(username):
    me     = current_user()
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        abort(404)
    db.execute(
        "DELETE FROM followers WHERE follower_id=? AND following_id=?",
        (me["id"], target["id"])
    )
    db.commit()
    flash(f"Unfollowed {target['display_name']}.", "success")
    return redirect(url_for("profile", username=username))


"""
================================================================================
SECTION 9: CHAT / MESSAGES
================================================================================
"""

@app.route("/messages")
@login_required
def messages_list():
    me = current_user()
    db = get_db()
    # FIX: Corrected subquery — wrapped OR branches in parentheses so
    # AND is_deleted=0 applies to both sides of the OR.
    convos = db.execute("""
        SELECT
          other_user_id,
          u.username, u.display_name, u.last_seen,
          MAX(created_at) AS last_msg_at,
          (SELECT message FROM messages
           WHERE ((sender_id=:me AND receiver_id=other_user_id)
              OR  (sender_id=other_user_id AND receiver_id=:me))
             AND is_deleted=0
           ORDER BY created_at DESC LIMIT 1) AS last_msg_text,
          (SELECT COUNT(*) FROM messages
           WHERE sender_id=other_user_id AND receiver_id=:me
             AND is_read=0 AND is_deleted=0) AS unread
        FROM (
          SELECT CASE WHEN sender_id=:me THEN receiver_id ELSE sender_id END AS other_user_id
          FROM messages WHERE (sender_id=:me OR receiver_id=:me) AND is_deleted=0
        ) AS pairs,
        (SELECT :me AS id) AS me_alias
        JOIN users u ON u.id=other_user_id
        GROUP BY other_user_id
        ORDER BY last_msg_at DESC
    """, {"me": me["id"]}).fetchall()

    body = """
    <h1>💬 Messages</h1>
    {% if convos %}
    <div class="card" style="padding:0;overflow:hidden">
      {% for c in convos %}
        <a href="{{ url_for('chat_page', user_id=c['other_user_id']) }}" style="
           display:flex;align-items:center;gap:10px;padding:10px 14px;
           border-bottom:1px solid #14204a;text-decoration:none;color:var(--text);transition:.15s">
          <div style="width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--neon),var(--neon-purple));
                      display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0">
            {{ c['display_name']|initial }}
          </div>
          <div style="flex:1">
            <b style="display:block;font-size:13px">{{ c['display_name'] }}</b>
            <span style="font-size:11px;color:var(--text-dim)">{{ (c['last_msg_text'] or '')[:40] }}</span>
          </div>
          {% if c['unread'] > 0 %}
            <span style="background:var(--neon);color:#05060f;padding:2px 6px;border-radius:10px;font-size:10px;font-weight:700">{{ c['unread'] }}</span>
          {% endif %}
        </a>
      {% endfor %}
    </div>
    {% else %}
      <div class="card"><p class="small">No conversations yet.</p></div>
    {% endif %}
    """
    return render_page("Messages", body, convos=convos)


@app.route("/chat/<int:user_id>", methods=["GET", "POST"])
@login_required
def chat_page(user_id):
    me    = current_user()
    db    = get_db()
    other = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not other:
        abort(404)
    if other["id"] == me["id"]:
        flash("You can't message yourself.", "error")
        return redirect(url_for("messages_list"))

    if request.method == "POST":
        msg_text = request.form.get("message", "").strip()
        if msg_text:
            if me["is_muted"]:
                flash("You are muted and cannot send messages.", "error")
            else:
                db.execute(
                    """INSERT INTO messages (sender_id,receiver_id,message,created_at,is_read,is_deleted)
                       VALUES (?,?,?,?,0,0)""",
                    (me["id"], user_id, msg_text[:2000], datetime.utcnow().isoformat())
                )
                db.commit()
                create_notification(user_id, "message",
                                    f"{me['display_name']}: {msg_text[:60]}",
                                    url_for("chat_page", user_id=me["id"]))
        return redirect(url_for("chat_page", user_id=user_id))

    db.execute(
        "UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=? AND is_read=0 AND is_deleted=0",
        (user_id, me["id"])
    )
    db.commit()

    chat_msgs = db.execute("""
        SELECT m.*,u.display_name FROM messages m
        JOIN users u ON u.id=m.sender_id
        WHERE ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)) AND is_deleted=0
        ORDER BY m.created_at ASC LIMIT 200
    """, (me["id"], user_id, user_id, me["id"])).fetchall()

    online = is_online(other["last_seen"])
    body = """
    <a href="{{ url_for('messages_list') }}" class="btn btn-sm" style="margin-bottom:10px">← Back</a>
    <h1 style="display:inline;margin-left:8px">{{ other['display_name'] }}</h1>
    {% if online %}<span class="badge badge-good">● Online</span>{% endif %}

    <div class="card" style="max-width:600px;margin-top:12px">
      <div style="background:#060810;border-radius:10px;border:1px solid var(--neon-soft);padding:10px;
                  height:300px;overflow-y:auto;margin-bottom:10px">
        {% for m in chat_msgs %}
          <div style="margin-bottom:8px;{% if m['sender_id']==user['id'] %}text-align:right{% endif %}">
            <div style="display:inline-block;max-width:70%;
                        background:{% if m['sender_id']==user['id'] %}linear-gradient(135deg,#082060,#0a1840){% else %}#0d1028{% endif %};
                        border:1px solid {% if m['sender_id']==user['id'] %}var(--neon-soft){% else %}#1c2a55{% endif %};
                        padding:8px 12px;border-radius:12px;font-size:13px">
              {{ m['message'] }}
              <div style="font-size:10px;color:var(--text-dim);margin-top:3px">
                {{ m['created_at'][11:16] }}
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
      <form method="post">
        <input name="message" placeholder="Type message…" required style="margin:0">
        <button class="btn btn-yellow" type="submit" style="margin-top:8px;width:100%">Send</button>
      </form>
    </div>
    """
    return render_page(f"Chat with {other['display_name']}", body,
                       other=other, chat_msgs=chat_msgs, online=online)


"""
================================================================================
SECTION 10: FEED / POSTS
================================================================================
"""

@app.route("/feed", methods=["GET", "POST"])
@login_required
def feed():
    me = current_user()
    db = get_db()

    if request.method == "POST":
        content = request.form.get("content", "").strip()[:2000]
        if not content:
            flash("Post must have content.", "error")
            return redirect(url_for("feed"))
        db.execute(
            "INSERT INTO posts (user_id,content,post_type,created_at) VALUES (?,?,'text',?)",
            (me["id"], content, datetime.utcnow().isoformat())
        )
        db.commit()
        grant_xp(me["id"], 5)
        flash("Post published!", "success")
        return redirect(url_for("feed"))

    posts = db.execute("""
        SELECT p.*,u.username,u.display_name,
               (SELECT COUNT(*) FROM post_likes l WHERE l.post_id=p.id) AS like_count,
               (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.id AND c.is_hidden=0) AS comment_count,
               (SELECT 1 FROM post_likes l WHERE l.post_id=p.id AND l.user_id=:me) AS i_liked
        FROM posts p JOIN users u ON u.id=p.user_id
        WHERE p.is_hidden=0 ORDER BY p.created_at DESC LIMIT 40
    """, {"me": me["id"]}).fetchall()

    body = """
    <h1>📰 Feed</h1>
    <div class="card">
      <h3>Create Post</h3>
      <form method="post">
        <textarea name="content" rows="3" placeholder="What's on your mind?" required></textarea>
        <button class="btn btn-yellow" type="submit">Publish</button>
      </form>
    </div>

    {% for post in posts %}
    <div class="card">
      <div style="display:flex;gap:10px;margin-bottom:8px">
        <div style="width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--neon),var(--neon-purple));
                    display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0">
          {{ post['display_name']|initial }}
        </div>
        <div style="flex:1">
          <b><a href="{{ url_for('profile', username=post['username']) }}">{{ post['display_name'] }}</a></b>
          <div style="font-size:11px;color:var(--text-dim)">{{ post['created_at'][:16].replace('T',' ') }}</div>
        </div>
      </div>
      <p style="white-space:pre-wrap;margin:8px 0;font-size:13px">{{ post['content'] }}</p>
      <div style="display:flex;gap:8px;align-items:center;padding-top:8px;border-top:1px solid #14204a;flex-wrap:wrap">
        <form method="post" action="{{ url_for('toggle_like', post_id=post['id']) }}" style="display:inline">
          <button class="btn btn-sm {% if post['i_liked'] %}btn-danger{% endif %}" type="submit">
            {% if post['i_liked'] %}❤{% else %}♡{% endif %}
          </button>
        </form>
        <span class="small">{{ post['like_count'] }} · {{ post['comment_count'] }} comments</span>
        <a class="btn btn-sm" href="{{ url_for('view_post', post_id=post['id']) }}">View</a>
        {% if post['user_id']==user['id'] %}
          <form method="post" action="{{ url_for('delete_post', post_id=post['id']) }}" style="display:inline;margin-left:auto">
            <button class="btn btn-danger btn-sm" type="submit">Delete</button>
          </form>
        {% endif %}
      </div>
    </div>
    {% else %}<p class="small">No posts yet.</p>{% endfor %}
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
        FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=? AND p.is_hidden=0
    """, (me["id"], post_id)).fetchone()
    if not post:
        abort(404)

    comments = db.execute("""
        SELECT c.*,u.username,u.display_name FROM comments c
        JOIN users u ON u.id=c.user_id WHERE c.post_id=? AND c.is_hidden=0 ORDER BY c.created_at ASC
    """, (post_id,)).fetchall()

    body = """
    <a href="{{ url_for('feed') }}" class="btn btn-sm">← Feed</a>
    <div class="card" style="max-width:600px;margin-top:10px">
      <div style="display:flex;gap:10px;margin-bottom:10px">
        <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--neon),var(--neon-purple));
                    display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0">
          {{ post['display_name']|initial }}
        </div>
        <div style="flex:1">
          <b><a href="{{ url_for('profile', username=post['username']) }}">{{ post['display_name'] }}</a></b>
          <div style="font-size:11px;color:var(--text-dim)">{{ post['created_at'][:16].replace('T',' ') }}</div>
        </div>
      </div>
      <p style="white-space:pre-wrap;font-size:14px;line-height:1.6">{{ post['content'] }}</p>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <form method="post" action="{{ url_for('toggle_like', post_id=post['id']) }}" style="display:inline">
          <button class="btn btn-sm {% if post['i_liked'] %}btn-danger{% endif %}" type="submit">
            {% if post['i_liked'] %}❤ Unlike{% else %}♡ Like{% endif %}
          </button>
        </form>
        <span class="small">{{ post['like_count'] }} likes</span>
      </div>
    </div>

    <h2 style="margin-top:14px">Comments ({{ comments|length }})</h2>
    <div class="card">
      {% for c in comments %}
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <div style="width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--neon),var(--neon-purple));
                      display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0">
            {{ c['display_name']|initial }}
          </div>
          <div style="flex:1">
            <b><a href="{{ url_for('profile', username=c['username']) }}">{{ c['display_name'] }}</a></b>
            <p style="font-size:12px;margin:2px 0">{{ c['content'] }}</p>
            <span style="font-size:10px;color:var(--text-dim)">{{ c['created_at'][:16].replace('T',' ') }}</span>
          </div>
        </div>
      {% endfor %}
      <div style="border-top:1px solid #14204a;padding-top:10px;margin-top:10px">
        <form method="post" action="{{ url_for('add_comment', post_id=post['id']) }}">
          <textarea name="content" rows="2" placeholder="Write comment…" required></textarea>
          <button class="btn btn-sm btn-yellow" type="submit">Comment</button>
        </form>
      </div>
    </div>
    """
    return render_page("Post", body, post=post, comments=comments)


@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def toggle_like(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        abort(404)
    existing = db.execute(
        "SELECT 1 FROM post_likes WHERE user_id=? AND post_id=?", (me["id"], post_id)
    ).fetchone()
    if existing:
        db.execute("DELETE FROM post_likes WHERE user_id=? AND post_id=?", (me["id"], post_id))
        db.commit()
    else:
        db.execute(
            "INSERT INTO post_likes (user_id,post_id,created_at) VALUES (?,?,?)",
            (me["id"], post_id, datetime.utcnow().isoformat())
        )
        db.commit()
        if post["user_id"] != me["id"]:
            create_notification(post["user_id"], "like",
                                f"{me['display_name']} liked your post.",
                                url_for("view_post", post_id=post_id))
    return redirect(request.referrer or url_for("feed"))


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    me      = current_user()
    db      = get_db()
    post    = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        abort(404)
    content = request.form.get("content", "").strip()[:1000]
    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("view_post", post_id=post_id))
    db.execute(
        "INSERT INTO comments (user_id,post_id,content,created_at) VALUES (?,?,?,?)",
        (me["id"], post_id, content, datetime.utcnow().isoformat())
    )
    db.commit()
    if post["user_id"] != me["id"]:
        create_notification(post["user_id"], "comment",
                            f"{me['display_name']} commented: {content[:60]}",
                            url_for("view_post", post_id=post_id))
    return redirect(url_for("view_post", post_id=post_id))


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    me = current_user()
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post or (post["user_id"] != me["id"] and not me["is_admin"]):
        abort(403)
    db.execute("DELETE FROM post_likes WHERE post_id=?", (post_id,))
    db.execute("DELETE FROM comments WHERE post_id=?", (post_id,))
    db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    db.commit()
    admin_log("delete_post", target_id=post_id, target_type="post")
    flash("Post deleted.", "success")
    return redirect(url_for("feed"))


"""
================================================================================
SECTION 11: NOTIFICATIONS
================================================================================
"""

@app.route("/notifications")
@login_required
def notifications_page():
    me  = current_user()
    db  = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (me["id"],))
    db.commit()
    notifs = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 60",
        (me["id"],)
    ).fetchall()
    body = """
    <h1>🔔 Notifications</h1>
    <div class="card">
      {% for n in notifs %}
        <div style="padding:8px 0;border-bottom:1px solid #14204a">
          <p style="margin:0;font-size:13px">
            {% if n['link'] %}<a href="{{ n['link'] }}">{{ n['message'] }}</a>{% else %}{{ n['message'] }}{% endif %}
          </p>
          <span class="small">{{ n['created_at'][:16].replace('T',' ') }}</span>
        </div>
      {% else %}<p class="small">No notifications.</p>{% endfor %}
    </div>
    """
    return render_page("Notifications", body, notifs=notifs)


"""
================================================================================
SECTION 12: WALLET
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
        except (ValueError, TypeError):
            neo_amount = 0
        if target_currency not in OTHER_CURRENCIES or neo_amount <= 0:
            flash("Invalid conversion request.", "error")
        else:
            bal = get_balances(user["id"])
            if bal["NEO"] < neo_amount:
                flash("Not enough Neo for that conversion.", "error")
            else:
                rate   = CURRENCIES[target_currency]["rate_from_neo"]
                gained = neo_amount * rate
                adjust_balance(user["id"], "NEO", -neo_amount, f"Converted to {target_currency}")
                adjust_balance(user["id"], target_currency, gained, "Converted from Neo")
                flash(f"Converted {neo_amount} Neo → {gained} {CURRENCIES[target_currency]['name']}.", "success")
        return redirect(url_for("wallet"))

    bal     = get_balances(user["id"])
    db      = get_db()
    history = db.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
        (user["id"],)
    ).fetchall()
    body = """
    <h1>Wallet</h1>
    <div class="card">
      <h3>Balances</h3>
      {% for code, info in currencies.items() %}
        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #14204a">
          <span>{{ info['name'] }}</span>
          <b>{{ bal[code] }}</b>
        </div>
      {% endfor %}
    </div>
    <div class="card">
      <h3>Convert to Other Currencies</h3>
      <form method="post">
        <label>Target Currency</label>
        <select name="currency">
          {% for code in other_currencies %}
            <option value="{{ code }}">{{ currencies[code]['name'] }}</option>
          {% endfor %}
        </select>
        <label>Neo Amount</label>
        <input type="number" name="neo_amount" min="1" required>
        <button class="btn btn-yellow" type="submit" style="margin-top:8px">Convert</button>
      </form>
    </div>
    <div class="card">
      <h3>Recent Transactions</h3>
      <table>
        <tr><th>Date</th><th>Type</th><th>Currency</th><th>Amount</th><th>Note</th></tr>
        {% for t in history %}
          <tr>
            <td class="small">{{ t['created_at'][:16].replace('T',' ') }}</td>
            <td><span class="badge">{{ t['type'] }}</span></td>
            <td>{{ t['currency'] }}</td>
            <td><b>{{ '+' if t['amount']>0 else '' }}{{ t['amount'] }}</b></td>
            <td class="small">{{ t['note'] or '' }}</td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_page("Wallet", body, bal=bal, currencies=CURRENCIES,
                       other_currencies=OTHER_CURRENCIES, history=history)


"""
================================================================================
SECTION 13: DAILY REWARD
================================================================================
"""

@app.route("/rewards/daily", methods=["GET", "POST"])
@login_required
def daily_reward():
    user = current_user()
    can_claim, streak = daily_reward_status(user)
    # FIX: compute next_reward in Python and pass to template.
    # Templates cannot call arbitrary Python functions directly.
    next_reward = daily_reward_amount(streak)

    if request.method == "POST":
        if not can_claim:
            flash("You already claimed today's reward.", "error")
            return redirect(url_for("daily_reward"))

        lucky      = random.random() < LUCKY_CHANCE
        amount     = next_reward * LUCKY_MULTIPLIER if lucky else next_reward
        new_streak = streak + 1

        db = get_db()
        db.execute(
            "UPDATE users SET daily_streak=?,last_daily_claim=? WHERE id=?",
            (new_streak, date.today().isoformat(), user["id"])
        )
        db.commit()
        adjust_balance(user["id"], "NEO", amount, f"Daily reward streak day {new_streak}")
        grant_xp(user["id"], 15)

        if lucky:
            flash(f"🌟 LUCKY! Claimed {amount} Neo (x{LUCKY_MULTIPLIER}) · Streak: {new_streak} days", "success")
        else:
            flash(f"🎁 Claimed {amount} Neo · Streak: {new_streak} days", "success")
        return redirect(url_for("daily_reward"))

    body = """
    <h1>🎁 Daily Reward</h1>
    <div class="card" style="max-width:500px">
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px">
          <span>Streak</span>
          <b style="color:var(--accent-yellow)">{{ streak }} days</b>
        </div>
        <div style="background:#0a0f2a;border:1px solid var(--neon-soft);border-radius:20px;height:8px">
          <div style="background:linear-gradient(90deg,var(--neon),var(--neon-purple));height:100%;
                      border-radius:20px;width:{{ [streak*10,100]|min }}%"></div>
        </div>
      </div>
      {% if can_claim %}
        <div style="text-align:center;padding:16px 0">
          <div style="font-size:32px;color:var(--accent-yellow);font-weight:900">+{{ next_reward }} Neo</div>
          <form method="post" style="margin-top:10px">
            <button class="btn btn-yellow" type="submit" style="font-size:14px;padding:10px 24px">
              Claim Day {{ streak+1 }} ✦
            </button>
          </form>
        </div>
      {% else %}
        <p style="text-align:center;color:var(--good)">✓ Claimed today!</p>
        <p style="text-align:center;font-size:12px;color:var(--text-dim)">Come back tomorrow for +{{ next_reward }} Neo</p>
      {% endif %}
    </div>
    """
    return render_page("Daily Reward", body, streak=streak, can_claim=can_claim,
                       next_reward=next_reward)


"""
================================================================================
SECTION 14: GAMES
================================================================================
"""

@app.route("/games")
@login_required
def games_list():
    db       = get_db()
    category = request.args.get("category", "")
    q        = request.args.get("q", "").strip()
    query  = """SELECT g.*,u.display_name AS dev_name FROM games g
                JOIN users u ON g.developer_id=u.id WHERE g.is_hidden=0"""
    params = []
    if category:
        query += " AND g.category=?"
        params.append(category)
    if q:
        query += " AND g.title LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY g.created_at DESC"
    games = db.execute(query, params).fetchall()

    body = """
    <h1>🎮 Game Marketplace</h1>
    <div class="card">
      <form method="get" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
        <div style="flex:1;min-width:150px">
          <label>Search</label>
          <input name="q" value="{{ request.args.get('q','') }}" placeholder="Game title…">
        </div>
        <div style="flex:1;min-width:150px">
          <label>Category</label>
          <select name="category">
            <option value="">All</option>
            {% for c in categories %}
              <option value="{{ c }}" {% if c==category %}selected{% endif %}>{{ c }}</option>
            {% endfor %}
          </select>
        </div>
        <button class="btn" type="submit">Filter</button>
      </form>
    </div>
    <a class="btn btn-yellow" href="{{ url_for('upload_game') }}" style="display:inline-block;margin-bottom:10px">+ Upload</a>
    <div class="grid">
      {% for game in games %}
        <div class="card">
          <b>{{ game['title'] }}</b>
          <p class="small" style="margin:4px 0">{{ game['category'] }}</p>
          {% if game['price'] > 0 %}
            <span class="badge badge-yellow">{{ game['price'] }} {{ game['price_currency'] }}</span>
          {% else %}
            <span class="badge badge-good">Free</span>
          {% endif %}
          <a class="btn btn-sm" style="margin-top:6px" href="{{ url_for('play_game', game_id=game['id']) }}">Play</a>
        </div>
      {% else %}<p>No games found.</p>{% endfor %}
    </div>
    """
    return render_page("Games", body, games=games, categories=GAME_CATEGORIES,
                       category=category)


@app.route("/games/upload", methods=["GET", "POST"])
@login_required
def upload_game():
    user = current_user()
    if request.method == "POST":
        title          = request.form.get("title", "").strip()[:60]
        description    = request.form.get("description", "").strip()[:300]
        category       = request.form.get("category")
        price_currency = request.form.get("price_currency", "NEO")
        try:
            price = int(request.form.get("price", "0"))
        except (ValueError, TypeError):
            price = -1

        if not title or category not in GAME_CATEGORIES:
            flash("Title and valid category are required.", "error")
            return redirect(url_for("upload_game"))
        if price < 0:
            flash("Price must be 0 or positive.", "error")
            return redirect(url_for("upload_game"))
        if price_currency not in CURRENCIES:
            flash("Invalid currency selected.", "error")
            return redirect(url_for("upload_game"))

        db = get_db()
        if not user["is_developer"]:
            db.execute("UPDATE users SET is_developer=1 WHERE id=?", (user["id"],))
            db.commit()

        db.execute("""
            INSERT INTO games (developer_id,title,description,category,filename,
                               price,price_currency,play_count,created_at)
            VALUES (?,?,?,?,?,?,?,0,?)
        """, (user["id"], title, description, category, "demo.html",
              price, price_currency, datetime.utcnow().isoformat()))
        db.commit()
        flash("Game uploaded!", "success")
        return redirect(url_for("games_list"))

    body = """
    <h1>Upload a Game</h1>
    <div class="card" style="max-width:480px">
      <form method="post">
        <label>Title</label><input name="title" required>
        <label>Description</label><textarea name="description" rows="3"></textarea>
        <label>Category</label>
        <select name="category">
          {% for c in categories %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
        </select>
        <label>Price</label>
        <input type="number" name="price" min="0" value="0">
        <label>Currency</label>
        <select name="price_currency">
          {% for code, info in currencies.items() %}
            <option value="{{ code }}">{{ info['name'] }}</option>
          {% endfor %}
        </select>
        <button class="btn btn-yellow" type="submit">Publish</button>
      </form>
    </div>
    """
    return render_page("Upload Game", body, categories=GAME_CATEGORIES, currencies=CURRENCIES)


@app.route("/games/play/<int:game_id>")
@login_required
def play_game(game_id):
    db   = get_db()
    game = db.execute("""
        SELECT g.*,u.display_name AS dev_name FROM games g
        JOIN users u ON g.developer_id=u.id WHERE g.id=? AND g.is_hidden=0
    """, (game_id,)).fetchone()
    if not game:
        abort(404)
    user = current_user()

    db.execute("UPDATE games SET play_count=play_count+1 WHERE id=?", (game_id,))
    record_game_play_reward(user["id"], game_id)
    db.commit()

    body = """
    <h1>{{ game['title'] }}</h1>
    <p class="small">{{ game['category'] }} · by {{ game['dev_name'] }} · {{ game['play_count'] }} plays</p>
    <div style="background:linear-gradient(135deg,#0d1442,#05060f);border:1px solid var(--neon-soft);
                border-radius:10px;padding:20px;text-align:center">
      <p>Game embed placeholder</p>
    </div>
    <p style="margin-top:10px"><a href="{{ url_for('games_list') }}">← Back to Games</a></p>
    """
    return render_page(game["title"], body, game=game)


"""
================================================================================
SECTION 15: SETTINGS
================================================================================
"""

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    me = current_user()
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password":
            current_pw = request.form.get("current_password", "")
            new_pw     = request.form.get("new_password", "")
            if not check_password_hash(me["password_hash"], current_pw):
                flash("Current password is incorrect.", "error")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "error")
            else:
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new_pw), me["id"])
                )
                db.commit()
                flash("Password changed.", "success")

        elif action == "reset_account":
            confirm = request.form.get("confirm_text", "")
            if confirm != "RESET MY ACCOUNT":
                flash("Confirmation text did not match.", "error")
            else:
                uid = me["id"]
                db.execute("UPDATE balances SET amount=0 WHERE user_id=?", (uid,))
                db.execute("UPDATE balances SET amount=200 WHERE user_id=? AND currency='NEO'", (uid,))
                db.execute(
                    "UPDATE users SET xp=0,level=1,daily_streak=0,last_daily_claim=NULL WHERE id=?",
                    (uid,)
                )
                db.commit()
                flash("Account reset to initial state.", "success")
                return redirect(url_for("index"))

        return redirect(url_for("settings_page"))

    body = """
    <h1>⚙ Settings</h1>
    <div class="card">
      <h3>Change Password</h3>
      <form method="post">
        <input type="hidden" name="action" value="change_password">
        <label>Current Password</label>
        <input type="password" name="current_password" required>
        <label>New Password</label>
        <input type="password" name="new_password" required>
        <button class="btn" type="submit">Update</button>
      </form>
    </div>
    <div class="card">
      <h3 style="color:var(--danger)">⚠ Reset Account</h3>
      <p class="small">Resets balances, XP, level, and streak.</p>
      <form method="post">
        <input type="hidden" name="action" value="reset_account">
        <input name="confirm_text" placeholder="Type: RESET MY ACCOUNT" style="border-color:var(--danger)">
        <button class="btn btn-danger" type="submit">Reset</button>
      </form>
    </div>
    """
    return render_page("Settings", body)


"""
================================================================================
SECTION 16: ADVANCED ADMIN PANEL
================================================================================
"""

# FIX: Replaced all admin pages that used the broken _admin_sidebar() f-string
# helper with inline Jinja2 sidebar template rendering via the
# admin_sidebar_tpl variable passed through render_page().
# All admin routes now use:
#   {% set active = 'endpoint_name' %}
#   {% with sidebar_html = admin_sidebar_tpl %}
#     {{ sidebar_html | replace("active=='admin_foo'", ...) | safe }}
#   {% endwith %}
# But the cleanest fix is to use a single Jinja2 template string that
# accepts an `active` variable, rendered once via render_template_string.

def render_admin_page(title, active_key, main_content_html, **extra):
    """
    Renders an admin page with the sidebar already resolved.
    active_key: the endpoint name string to mark as active in the sidebar.
    """
    # Build combined template: sidebar + main in admin-wrap grid
    full_body = (
        '<div class="admin-wrap">'
        + ADMIN_SIDEBAR_TEMPLATE
        + '<div class="admin-main">'
        + main_content_html
        + '</div></div>'
    )
    u = current_user()
    umc = unread_message_count(u["id"]) if u else 0
    unc = unread_notification_count(u["id"]) if u else 0

    body_rendered = render_template_string(
        full_body,
        user=u,
        active=active_key,
        unread_msg_count=umc,
        unread_notif_count=unc,
        **extra
    )
    return render_template_string(
        NAV_TEMPLATE,
        title=title,
        css=BASE_CSS,
        body=body_rendered,
        user=u,
        unread_msg_count=umc,
        unread_notif_count=unc
    )


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()

    user_count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    active_today = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE last_seen >= datetime('now', '-1 day')"
    ).fetchone()["c"]
    post_count = db.execute("SELECT COUNT(*) AS c FROM posts WHERE is_hidden=0").fetchone()["c"]
    msg_count  = db.execute("SELECT COUNT(*) AS c FROM messages WHERE is_deleted=0").fetchone()["c"]
    game_count = db.execute("SELECT COUNT(*) AS c FROM games WHERE is_hidden=0").fetchone()["c"]
    neo_total  = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM balances WHERE currency='NEO'"
    ).fetchone()["total"]

    recent_logs = db.execute("""
        SELECT al.*, u.username FROM admin_logs al
        JOIN users u ON u.id=al.admin_id
        ORDER BY al.created_at DESC LIMIT 10
    """).fetchall()

    main = """
    <h1>Admin Dashboard</h1>
    <div class="admin-stats">
      <div class="admin-stat-card"><b>{{ user_count }}</b><span>Total Users</span></div>
      <div class="admin-stat-card"><b>{{ active_today }}</b><span>Active Today</span></div>
      <div class="admin-stat-card"><b>{{ neo_total }}</b><span>Neo in Circulation</span></div>
      <div class="admin-stat-card"><b>{{ post_count }}</b><span>Posts</span></div>
      <div class="admin-stat-card"><b>{{ msg_count }}</b><span>Messages</span></div>
      <div class="admin-stat-card"><b>{{ game_count }}</b><span>Games</span></div>
    </div>
    <h2>Recent Admin Actions</h2>
    <div class="card">
      <table>
        <tr><th>Admin</th><th>Action</th><th>Target</th><th>Time</th></tr>
        {% for log in recent_logs %}
          <tr>
            <td class="small">{{ log['username'] }}</td>
            <td class="small">{{ log['action'] }}</td>
            <td class="small">{{ log['target_user_id'] or log['target_type'] or '-' }}</td>
            <td class="small">{{ log['created_at'][:19].replace('T',' ') }}</td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Admin Dashboard", "admin_dashboard", main,
                             user_count=user_count, active_today=active_today,
                             neo_total=neo_total, post_count=post_count,
                             msg_count=msg_count, game_count=game_count,
                             recent_logs=recent_logs)


@app.route("/admin/users")
@admin_required
def admin_users():
    db     = get_db()
    search = request.args.get("search", "")
    query  = "SELECT * FROM users WHERE 1=1"
    params = []

    if search:
        query += " AND (username LIKE ? OR display_name LIKE ? OR email LIKE ?)"
        params = [f"%{search}%", f"%{search}%", f"%{search}%"]

    query += " ORDER BY created_at DESC LIMIT 100"
    users = db.execute(query, params).fetchall()

    main = """
    <h1>User Management</h1>
    <div class="card">
      <form method="get" style="display:flex;gap:8px">
        <input name="search" value="{{ search }}" placeholder="Search username, name, email…" style="flex:1">
        <button class="btn" type="submit">Search</button>
      </form>
    </div>
    <div class="card">
      <table>
        <tr>
          <th>Username</th><th>Display Name</th><th>Level</th>
          <th>Role</th><th>Status</th><th>Joined</th><th>Actions</th>
        </tr>
        {% for u in users %}
          <tr>
            <td><a href="{{ url_for('profile', username=u['username']) }}">{{ u['username'] }}</a></td>
            <td>{{ u['display_name'] }}</td>
            <td>{{ u['level'] }}</td>
            <td><span class="badge">{{ u['admin_role']|admin_role_label }}</span></td>
            <td>
              {% if u['is_banned'] %}<span class="badge badge-danger">BANNED</span>{% endif %}
              {% if u['is_suspended'] %}<span class="badge badge-danger">SUSPENDED</span>{% endif %}
              {% if u['is_muted'] %}<span class="badge badge-yellow">MUTED</span>{% endif %}
            </td>
            <td class="small">{{ u['created_at'][:10] }}</td>
            <td><a class="btn btn-sm" href="{{ url_for('admin_user_detail', user_id=u['id']) }}">View</a></td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("User Management", "admin_users", main,
                             users=users, search=search)


@app.route("/admin/user/<int:user_id>", methods=["GET", "POST"])
@admin_required
def admin_user_detail(user_id):
    db          = get_db()
    target_user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not target_user:
        abort(404)

    if request.method == "POST":
        action = request.form.get("action")
        me     = current_user()

        if target_user["admin_role"] == "super_admin" and me["admin_role"] != "super_admin":
            flash("Cannot modify Super Admin accounts.", "error")
            return redirect(url_for("admin_user_detail", user_id=user_id))

        if action == "ban":
            db.execute("UPDATE users SET is_banned=1 WHERE id=?", (user_id,))
            admin_log("ban_user", target_user_id=user_id, new_value="banned",
                     reason=request.form.get("reason"))
            flash("User banned.", "success")
        elif action == "unban":
            db.execute("UPDATE users SET is_banned=0 WHERE id=?", (user_id,))
            admin_log("unban_user", target_user_id=user_id)
            flash("User unbanned.", "success")
        elif action == "suspend":
            db.execute("UPDATE users SET is_suspended=1 WHERE id=?", (user_id,))
            admin_log("suspend_user", target_user_id=user_id)
            flash("User suspended.", "success")
        elif action == "unsuspend":
            db.execute("UPDATE users SET is_suspended=0 WHERE id=?", (user_id,))
            admin_log("unsuspend_user", target_user_id=user_id)
            flash("User unsuspended.", "success")
        elif action == "mute":
            db.execute("UPDATE users SET is_muted=1 WHERE id=?", (user_id,))
            admin_log("mute_user", target_user_id=user_id)
            flash("User muted.", "success")
        elif action == "unmute":
            db.execute("UPDATE users SET is_muted=0 WHERE id=?", (user_id,))
            admin_log("unmute_user", target_user_id=user_id)
            flash("User unmuted.", "success")
        elif action == "reset_xp":
            old_xp = target_user["xp"]
            db.execute("UPDATE users SET xp=0,level=1 WHERE id=?", (user_id,))
            admin_log("reset_xp", target_user_id=user_id,
                     previous_value=str(old_xp), new_value="0")
            flash("User XP reset.", "success")
        elif action == "reset_password":
            new_pw = secrets.token_urlsafe(12)
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(new_pw), user_id))
            admin_log("reset_password", target_user_id=user_id)
            flash(f"Password reset. New temporary password: {new_pw}", "success")
        elif action == "set_role":
            new_role = request.form.get("new_role", "")
            if new_role and new_role not in ADMIN_ROLES:
                flash("Invalid role.", "error")
            else:
                old_role = target_user["admin_role"]
                db.execute(
                    "UPDATE users SET admin_role=?,is_admin=? WHERE id=?",
                    (new_role if new_role else None, 1 if new_role else 0, user_id)
                )
                admin_log("set_admin_role", target_user_id=user_id,
                         previous_value=old_role, new_value=new_role)
                flash("Admin role updated.", "success")

        db.commit()
        return redirect(url_for("admin_user_detail", user_id=user_id))

    balances = get_balances(user_id)
    posts    = db.execute(
        "SELECT COUNT(*) AS c FROM posts WHERE user_id=? AND is_hidden=0", (user_id,)
    ).fetchone()["c"]
    friends  = friend_count(user_id)

    main = """
    <a href="{{ url_for('admin_users') }}" class="btn btn-sm">← Back</a>
    <h1 style="display:inline;margin-left:8px">{{ target_user['display_name'] }}</h1>

    <div class="card" style="margin-top:12px">
      <h3>Account Information</h3>
      <table style="width:auto">
        <tr><td>Username:</td><td><b>{{ target_user['username'] }}</b></td></tr>
        <tr><td>Email:</td><td>{{ target_user['email'] }}</td></tr>
        <tr><td>Level:</td><td>{{ target_user['level'] }}</td></tr>
        <tr><td>XP:</td><td>{{ target_user['xp'] }}</td></tr>
        <tr><td>Role:</td><td><span class="badge">{{ target_user['admin_role']|admin_role_label }}</span></td></tr>
        <tr><td>Status:</td><td>
          {% if target_user['is_banned'] %}<span class="badge badge-danger">BANNED</span>{% endif %}
          {% if target_user['is_suspended'] %}<span class="badge badge-danger">SUSPENDED</span>{% endif %}
          {% if target_user['is_muted'] %}<span class="badge badge-yellow">MUTED</span>{% endif %}
          {% if not target_user['is_banned'] and not target_user['is_suspended'] %}
            <span class="badge badge-good">Active</span>
          {% endif %}
        </td></tr>
        <tr><td>Posts:</td><td>{{ posts }}</td></tr>
        <tr><td>Friends:</td><td>{{ friends }}</td></tr>
        <tr><td>Joined:</td><td>{{ target_user['created_at'][:10] }}</td></tr>
      </table>
    </div>

    <div class="card">
      <h3>Balances</h3>
      <table style="width:auto">
        {% for code, amount in balances.items() %}
          <tr>
            <td>{{ currencies[code]['name'] }}:</td>
            <td><b>{{ amount }}</b></td>
          </tr>
        {% endfor %}
      </table>
    </div>

    <div class="card">
      <h3>Moderation Actions</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        {% if not target_user['is_banned'] %}
          <form method="post">
            <input type="hidden" name="action" value="ban">
            <input name="reason" placeholder="Reason (optional)" style="margin-bottom:6px">
            <button class="btn btn-danger" type="submit"
                    onclick="return confirm('Ban this user?')">Ban User</button>
          </form>
        {% else %}
          <form method="post">
            <input type="hidden" name="action" value="unban">
            <button class="btn btn-good" type="submit">Unban User</button>
          </form>
        {% endif %}

        {% if not target_user['is_suspended'] %}
          <form method="post">
            <input type="hidden" name="action" value="suspend">
            <button class="btn btn-danger" type="submit">Suspend User</button>
          </form>
        {% else %}
          <form method="post">
            <input type="hidden" name="action" value="unsuspend">
            <button class="btn btn-good" type="submit">Unsuspend User</button>
          </form>
        {% endif %}

        {% if not target_user['is_muted'] %}
          <form method="post">
            <input type="hidden" name="action" value="mute">
            <button class="btn btn-danger" type="submit">Mute User</button>
          </form>
        {% else %}
          <form method="post">
            <input type="hidden" name="action" value="unmute">
            <button class="btn btn-good" type="submit">Unmute User</button>
          </form>
        {% endif %}

        <form method="post">
          <input type="hidden" name="action" value="reset_xp">
          <button class="btn btn-yellow" type="submit">Reset XP</button>
        </form>

        <form method="post" style="grid-column:span 2">
          <input type="hidden" name="action" value="reset_password">
          <button class="btn btn-yellow" type="submit">Reset Password</button>
        </form>

        <form method="post" style="grid-column:span 2">
          <label>Set Admin Role</label>
          <select name="new_role">
            <option value="">None (Remove Admin)</option>
            {% for role_key, role_info in admin_roles.items() %}
              <option value="{{ role_key }}"
                      {% if role_key==target_user['admin_role'] %}selected{% endif %}>
                {{ role_info['label'] }}
              </option>
            {% endfor %}
          </select>
          <input type="hidden" name="action" value="set_role">
          <button class="btn" type="submit" style="margin-top:8px;width:100%">Update Role</button>
        </form>
      </div>
    </div>
    """
    return render_admin_page(f"User: {target_user['display_name']}", "admin_users", main,
                             target_user=target_user, balances=balances,
                             posts=posts, friends=friends,
                             admin_roles=ADMIN_ROLES, currencies=CURRENCIES)


@app.route("/admin/economy", methods=["GET", "POST"])
@check_permission("economy_manage")
def admin_economy():
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_neo":
            try:
                target_id = int(request.form.get("target_user_id"))
                amount    = int(request.form.get("amount"))
                if amount <= 0:
                    raise ValueError("Amount must be positive.")
                reason = request.form.get("reason", "Admin adjustment")
                adjust_balance(target_id, "NEO", amount, reason)
                admin_log("add_balance", target_user_id=target_id,
                         new_value=str(amount), reason=reason)
                flash(f"Added {amount} Neo to user {target_id}.", "success")
            except (ValueError, TypeError) as e:
                flash(f"Error: {e}", "error")

        elif action == "remove_neo":
            try:
                target_id = int(request.form.get("target_user_id"))
                amount    = int(request.form.get("amount"))
                if amount <= 0:
                    raise ValueError("Amount must be positive.")
                reason = request.form.get("reason", "Admin adjustment")
                adjust_balance(target_id, "NEO", -amount, reason)
                admin_log("remove_balance", target_user_id=target_id,
                         new_value=str(-amount), reason=reason)
                flash(f"Removed {amount} Neo from user {target_id}.", "success")
            except (ValueError, TypeError) as e:
                flash(f"Error: {e}", "error")

        elif action == "set_balance":
            try:
                target_id  = int(request.form.get("target_user_id"))
                new_amount = int(request.form.get("new_amount"))
                currency   = request.form.get("currency", "NEO")
                if currency not in CURRENCIES:
                    raise ValueError("Invalid currency.")
                if new_amount < 0:
                    raise ValueError("Balance cannot be negative.")
                old   = get_balances(target_id).get(currency, 0)
                delta = new_amount - old
                # FIX: delta could be negative (reducing balance). adjust_balance
                # raises ValueError("Insufficient balance") only if final < 0,
                # which can't happen since new_amount >= 0 and old >= 0. Safe.
                adjust_balance(target_id, currency, delta, "Admin balance set")
                admin_log("set_balance", target_user_id=target_id,
                         previous_value=str(old), new_value=str(new_amount))
                flash(f"Set {currency} balance to {new_amount}.", "success")
            except (ValueError, TypeError) as e:
                flash(f"Error: {e}", "error")

        elif action == "reward_all_users":
            try:
                amount   = int(request.form.get("amount"))
                currency = request.form.get("currency", "NEO")
                if amount <= 0:
                    raise ValueError("Amount must be positive.")
                if currency not in CURRENCIES:
                    raise ValueError("Invalid currency.")
                reason   = request.form.get("reason", "Global reward")
                all_users = db.execute("SELECT id FROM users WHERE is_banned=0").fetchall()
                count = 0
                for u in all_users:
                    try:
                        adjust_balance(u["id"], currency, amount, reason)
                        count += 1
                    except ValueError:
                        pass
                admin_log("reward_all_users", new_value=f"{amount} {currency}", reason=reason)
                flash(f"Rewarded {amount} {currency} to {count} users.", "success")
            except (ValueError, TypeError) as e:
                flash(f"Error: {e}", "error")

        db.commit()
        return redirect(url_for("admin_economy"))

    richest = db.execute("""
        SELECT u.id, u.username, u.display_name, b.amount
        FROM balances b JOIN users u ON u.id=b.user_id
        WHERE b.currency='NEO' ORDER BY b.amount DESC LIMIT 10
    """).fetchall()

    total_neo = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM balances WHERE currency='NEO'"
    ).fetchone()["total"]

    main = """
    <h1>💰 Economy Control</h1>
    <div class="admin-stats">
      <div class="admin-stat-card">
        <b>{{ total_neo }}</b><span>Neo in Circulation</span>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div class="card">
        <h3>Add Balance</h3>
        <form method="post">
          <input type="hidden" name="action" value="add_neo">
          <label>User ID</label>
          <input type="number" name="target_user_id" required>
          <label>Amount to Add</label>
          <input type="number" name="amount" min="1" required>
          <label>Reason</label>
          <input name="reason" placeholder="Admin adjustment…">
          <button class="btn btn-yellow" type="submit" style="margin-top:8px;width:100%">Add Neo</button>
        </form>
      </div>

      <div class="card">
        <h3>Remove Balance</h3>
        <form method="post">
          <input type="hidden" name="action" value="remove_neo">
          <label>User ID</label>
          <input type="number" name="target_user_id" required>
          <label>Amount to Remove</label>
          <input type="number" name="amount" min="1" required>
          <label>Reason</label>
          <input name="reason" placeholder="Admin adjustment…">
          <button class="btn btn-danger" type="submit" style="margin-top:8px;width:100%">Remove Neo</button>
        </form>
      </div>

      <div class="card">
        <h3>Set Exact Balance</h3>
        <form method="post">
          <input type="hidden" name="action" value="set_balance">
          <label>User ID</label>
          <input type="number" name="target_user_id" required>
          <label>Currency</label>
          <select name="currency">
            {% for code, info in currencies.items() %}
              <option value="{{ code }}">{{ info['name'] }}</option>
            {% endfor %}
          </select>
          <label>New Amount</label>
          <input type="number" name="new_amount" min="0" required>
          <button class="btn" type="submit" style="margin-top:8px;width:100%">Set Balance</button>
        </form>
      </div>

      <div class="card">
        <h3>Global Reward</h3>
        <form method="post">
          <input type="hidden" name="action" value="reward_all_users">
          <label>Amount per User</label>
          <input type="number" name="amount" min="1" required>
          <label>Currency</label>
          <select name="currency">
            {% for code, info in currencies.items() %}
              <option value="{{ code }}">{{ info['name'] }}</option>
            {% endfor %}
          </select>
          <label>Reason</label>
          <input name="reason" placeholder="Reason for reward…">
          <button class="btn btn-good" type="submit" style="margin-top:8px;width:100%">Reward All</button>
        </form>
      </div>
    </div>

    <h2 style="margin-top:14px">Richest Players</h2>
    <div class="card">
      <table>
        <tr><th>Rank</th><th>Username</th><th>Neo</th></tr>
        {% for r in richest %}
          <tr>
            <td>#{{ loop.index }}</td>
            <td><a href="{{ url_for('admin_user_detail', user_id=r['id']) }}">{{ r['display_name'] }}</a></td>
            <td><b>{{ r['amount'] }}</b></td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Economy Control", "admin_economy", main,
                             richest=richest, total_neo=total_neo, currencies=CURRENCIES)


@app.route("/admin/transactions")
@check_permission("economy_manage")
def admin_transactions():
    db = get_db()

    user_filter     = request.args.get("user", "")
    currency_filter = request.args.get("currency", "")
    date_filter     = request.args.get("date", "")

    query  = """SELECT t.*, u.username, u.display_name
                FROM transactions t JOIN users u ON u.id=t.user_id WHERE 1=1"""
    params = []

    if user_filter:
        query += " AND (u.username LIKE ? OR u.display_name LIKE ?)"
        params.extend([f"%{user_filter}%", f"%{user_filter}%"])
    if currency_filter:
        query += " AND t.currency=?"
        params.append(currency_filter)
    if date_filter:
        query += " AND DATE(t.created_at)=?"
        params.append(date_filter)

    query += " ORDER BY t.created_at DESC LIMIT 200"
    transactions = db.execute(query, params).fetchall()

    main = """
    <h1>📈 Transaction Monitoring</h1>
    <div class="card">
      <form method="get" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">
        <div>
          <label>User</label>
          <input name="user" value="{{ user_filter }}" placeholder="Username…">
        </div>
        <div>
          <label>Currency</label>
          <select name="currency">
            <option value="">All</option>
            {% for code in currencies.keys() %}
              <option value="{{ code }}" {% if code==currency_filter %}selected{% endif %}>{{ code }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label>Date</label>
          <input type="date" name="date" value="{{ date_filter }}">
        </div>
        <div style="display:flex;align-items:flex-end">
          <button class="btn" type="submit">Filter</button>
        </div>
      </form>
    </div>
    <div class="card">
      <table>
        <tr><th>Date</th><th>User</th><th>Type</th><th>Currency</th><th>Amount</th><th>Note</th></tr>
        {% for t in transactions %}
          <tr>
            <td class="small">{{ t['created_at'][:19].replace('T',' ') }}</td>
            <td><a href="{{ url_for('admin_user_detail', user_id=t['user_id']) }}">{{ t['display_name'] }}</a></td>
            <td><span class="badge">{{ t['type'] }}</span></td>
            <td>{{ t['currency'] }}</td>
            <td><b>{{ '+' if t['amount']>0 else '' }}{{ t['amount'] }}</b></td>
            <td class="small">{{ t['note'] or '' }}</td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Transactions", "admin_transactions", main,
                             transactions=transactions, user_filter=user_filter,
                             currency_filter=currency_filter, date_filter=date_filter,
                             currencies=CURRENCIES)


@app.route("/admin/assets")
@check_permission("economy_manage")
def admin_assets():
    db     = get_db()
    assets = db.execute("SELECT * FROM assets ORDER BY name").fetchall()

    main = """
    <h1>📦 Asset Management</h1>
    <div class="card">
      <table>
        <tr><th>Symbol</th><th>Name</th><th>Current Price (Neo)</th><th>Actions</th></tr>
        {% for a in assets %}
          <tr>
            <td><b>{{ a['symbol'] }}</b></td>
            <td>{{ a['name'] }}</td>
            <td>{{ a['current_price'] }}</td>
            <td>
              <a class="btn btn-sm" href="{{ url_for('admin_edit_asset', asset_id=a['id']) }}">Edit Price</a>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Asset Management", "admin_assets", main, assets=assets)


@app.route("/admin/asset/<int:asset_id>/edit", methods=["GET", "POST"])
@check_permission("economy_manage")
def admin_edit_asset(asset_id):
    db    = get_db()
    asset = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not asset:
        abort(404)

    if request.method == "POST":
        try:
            new_price = int(request.form.get("price", ""))
            if new_price < 0:
                raise ValueError("Price cannot be negative.")
            old_price = asset["current_price"]
            db.execute("UPDATE assets SET current_price=? WHERE id=?", (new_price, asset_id))
            admin_log("edit_asset_price", target_id=asset_id, target_type="asset",
                     previous_value=str(old_price), new_value=str(new_price))
            db.commit()
            flash(f"Price for {asset['name']} updated to {new_price} Neo.", "success")
        except (ValueError, TypeError) as e:
            flash(f"Error: {e}", "error")
        return redirect(url_for("admin_assets"))

    main = """
    <a href="{{ url_for('admin_assets') }}" class="btn btn-sm">← Assets</a>
    <h1 style="margin-top:10px">Edit: {{ asset['name'] }}</h1>
    <div class="card" style="max-width:400px;margin-top:12px">
      <form method="post">
        <label>Symbol</label>
        <input value="{{ asset['symbol'] }}" disabled>
        <label>Current Price (Neo)</label>
        <input type="number" name="price" value="{{ asset['current_price'] }}" min="0" required>
        <button class="btn btn-yellow" type="submit" style="margin-top:8px;width:100%">Save Price</button>
      </form>
    </div>
    """
    return render_admin_page(f"Edit Asset: {asset['name']}", "admin_assets", main, asset=asset)


@app.route("/admin/posts")
@check_permission("content_moderate")
def admin_posts():
    db = get_db()

    hidden = db.execute("""
        SELECT p.*, u.display_name FROM posts p
        JOIN users u ON u.id=p.user_id
        WHERE p.is_hidden=1 ORDER BY p.created_at DESC LIMIT 50
    """).fetchall()

    recent = db.execute("""
        SELECT p.*, u.display_name, COUNT(DISTINCT l.user_id) AS like_count
        FROM posts p
        JOIN users u ON u.id=p.user_id
        LEFT JOIN post_likes l ON l.post_id=p.id
        WHERE p.is_hidden=0
        GROUP BY p.id
        ORDER BY p.created_at DESC LIMIT 30
    """).fetchall()

    main = """
    <h1>📝 Post Moderation</h1>
    {% if hidden %}
    <h2>Hidden Posts ({{ hidden|length }})</h2>
    <div class="card">
      <table>
        <tr><th>Author</th><th>Content</th><th>Date</th><th>Actions</th></tr>
        {% for p in hidden %}
          <tr>
            <td><a href="{{ url_for('admin_user_detail', user_id=p['user_id']) }}">{{ p['display_name'] }}</a></td>
            <td class="small">{{ p['content'][:80] }}…</td>
            <td class="small">{{ p['created_at'][:10] }}</td>
            <td>
              <form method="post" action="{{ url_for('admin_moderate_post', post_id=p['id']) }}" style="display:inline">
                <input type="hidden" name="action" value="show">
                <button class="btn btn-sm btn-good" type="submit">Restore</button>
              </form>
              <form method="post" action="{{ url_for('admin_moderate_post', post_id=p['id']) }}" style="display:inline">
                <input type="hidden" name="action" value="delete">
                <button class="btn btn-sm btn-danger" type="submit"
                        onclick="return confirm('Delete permanently?')">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    {% endif %}

    <h2>Recent Posts</h2>
    <div class="card">
      <table>
        <tr><th>Author</th><th>Content</th><th>Likes</th><th>Date</th><th>Actions</th></tr>
        {% for p in recent %}
          <tr>
            <td><a href="{{ url_for('admin_user_detail', user_id=p['user_id']) }}">{{ p['display_name'] }}</a></td>
            <td class="small">{{ p['content'][:60] }}…</td>
            <td>{{ p['like_count'] }}</td>
            <td class="small">{{ p['created_at'][:10] }}</td>
            <td>
              <form method="post" action="{{ url_for('admin_moderate_post', post_id=p['id']) }}" style="display:inline">
                <input type="hidden" name="action" value="hide">
                <button class="btn btn-danger btn-sm" type="submit">Hide</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Post Moderation", "admin_posts", main,
                             hidden=hidden, recent=recent)


@app.route("/admin/post/<int:post_id>/moderate", methods=["POST"])
@check_permission("content_moderate")
def admin_moderate_post(post_id):
    db   = get_db()
    post = db.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        abort(404)

    action = request.form.get("action")
    if action == "hide":
        db.execute("UPDATE posts SET is_hidden=1 WHERE id=?", (post_id,))
        admin_log("hide_post", target_id=post_id, target_type="post")
        flash("Post hidden.", "success")
    elif action == "show":
        db.execute("UPDATE posts SET is_hidden=0 WHERE id=?", (post_id,))
        admin_log("unhide_post", target_id=post_id, target_type="post")
        flash("Post restored.", "success")
    elif action == "delete":
        db.execute("DELETE FROM post_likes WHERE post_id=?", (post_id,))
        db.execute("DELETE FROM comments WHERE post_id=?", (post_id,))
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
        admin_log("delete_post", target_id=post_id, target_type="post")
        flash("Post permanently deleted.", "success")

    db.commit()
    return redirect(url_for("admin_posts"))


@app.route("/admin/games")
@check_permission("game_manage")
def admin_games():
    db    = get_db()
    games = db.execute("""
        SELECT g.*, u.display_name FROM games g
        JOIN users u ON u.id=g.developer_id
        ORDER BY g.created_at DESC
    """).fetchall()

    main = """
    <h1>🎮 Game Management</h1>
    <div class="card">
      <table>
        <tr>
          <th>Title</th><th>Developer</th><th>Category</th>
          <th>Plays</th><th>Price</th><th>Status</th><th>Actions</th>
        </tr>
        {% for g in games %}
          <tr>
            <td>{{ g['title'] }}</td>
            <td>{{ g['display_name'] }}</td>
            <td>{{ g['category'] }}</td>
            <td>{{ g['play_count'] }}</td>
            <td>{{ g['price'] }} {{ g['price_currency'] }}</td>
            <td>
              {% if g['is_featured'] %}<span class="badge badge-good">Featured</span>{% endif %}
              {% if g['is_hidden'] %}<span class="badge badge-danger">Hidden</span>{% endif %}
              {% if not g['is_hidden'] and not g['is_featured'] %}
                <span class="badge">Active</span>
              {% endif %}
            </td>
            <td style="display:flex;gap:4px;flex-wrap:wrap">
              {% if not g['is_featured'] %}
                <form method="post" action="{{ url_for('admin_manage_game', game_id=g['id']) }}" style="display:inline">
                  <input type="hidden" name="action" value="feature">
                  <button class="btn btn-sm btn-good" type="submit">Feature</button>
                </form>
              {% else %}
                <form method="post" action="{{ url_for('admin_manage_game', game_id=g['id']) }}" style="display:inline">
                  <input type="hidden" name="action" value="unfeature">
                  <button class="btn btn-sm btn-yellow" type="submit">Unfeature</button>
                </form>
              {% endif %}
              {% if not g['is_hidden'] %}
                <form method="post" action="{{ url_for('admin_manage_game', game_id=g['id']) }}" style="display:inline">
                  <input type="hidden" name="action" value="hide">
                  <button class="btn btn-sm btn-danger" type="submit">Hide</button>
                </form>
              {% else %}
                <form method="post" action="{{ url_for('admin_manage_game', game_id=g['id']) }}" style="display:inline">
                  <input type="hidden" name="action" value="show">
                  <button class="btn btn-sm btn-good" type="submit">Show</button>
                </form>
              {% endif %}
              <form method="post" action="{{ url_for('admin_manage_game', game_id=g['id']) }}" style="display:inline">
                <input type="hidden" name="action" value="delete">
                <button class="btn btn-danger btn-sm" type="submit"
                        onclick="return confirm('Delete permanently?')">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Game Management", "admin_games", main, games=games)


@app.route("/admin/game/<int:game_id>/manage", methods=["POST"])
@check_permission("game_manage")
def admin_manage_game(game_id):
    db   = get_db()
    game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    if not game:
        abort(404)

    action = request.form.get("action")
    if action == "delete":
        db.execute("DELETE FROM purchases WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM game_rewards WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM games WHERE id=?", (game_id,))
        admin_log("delete_game", target_id=game_id, target_type="game")
        flash("Game deleted.", "success")
    elif action == "feature":
        db.execute("UPDATE games SET is_featured=1 WHERE id=?", (game_id,))
        admin_log("feature_game", target_id=game_id, target_type="game")
        flash("Game featured.", "success")
    elif action == "unfeature":
        db.execute("UPDATE games SET is_featured=0 WHERE id=?", (game_id,))
        admin_log("unfeature_game", target_id=game_id, target_type="game")
        flash("Game unfeatured.", "success")
    elif action == "hide":
        db.execute("UPDATE games SET is_hidden=1 WHERE id=?", (game_id,))
        admin_log("hide_game", target_id=game_id, target_type="game")
        flash("Game hidden.", "success")
    elif action == "show":
        db.execute("UPDATE games SET is_hidden=0 WHERE id=?", (game_id,))
        admin_log("show_game", target_id=game_id, target_type="game")
        flash("Game restored.", "success")

    db.commit()
    return redirect(url_for("admin_games"))


@app.route("/admin/audit-log")
@check_permission("view_analytics")
def admin_audit_log():
    db = get_db()

    admin_filter  = request.args.get("admin", "")
    action_filter = request.args.get("action", "")
    date_filter   = request.args.get("date", "")

    query  = """SELECT al.*, ua.username AS admin_username, ut.username AS target_username
                FROM admin_logs al
                JOIN users ua ON ua.id=al.admin_id
                LEFT JOIN users ut ON ut.id=al.target_user_id
                WHERE 1=1"""
    params = []

    if admin_filter:
        query += " AND ua.username LIKE ?"
        params.append(f"%{admin_filter}%")
    if action_filter:
        query += " AND al.action LIKE ?"
        params.append(f"%{action_filter}%")
    if date_filter:
        query += " AND DATE(al.created_at)=?"
        params.append(date_filter)

    query += " ORDER BY al.created_at DESC LIMIT 500"
    logs = db.execute(query, params).fetchall()

    main = """
    <h1>📋 Audit Log</h1>
    <div class="card">
      <form method="get" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">
        <div>
          <label>Admin</label>
          <input name="admin" value="{{ admin_filter }}" placeholder="Admin username…">
        </div>
        <div>
          <label>Action</label>
          <input name="action" value="{{ action_filter }}" placeholder="Action…">
        </div>
        <div>
          <label>Date</label>
          <input type="date" name="date" value="{{ date_filter }}">
        </div>
        <div style="display:flex;align-items:flex-end">
          <button class="btn" type="submit">Filter</button>
        </div>
      </form>
    </div>
    <div class="card">
      <table>
        <tr><th>Date/Time</th><th>Admin</th><th>Action</th><th>Target</th><th>Details</th></tr>
        {% for log in logs %}
          <tr>
            <td class="small">{{ log['created_at'][:19].replace('T',' ') }}</td>
            <td><a href="{{ url_for('admin_user_detail', user_id=log['admin_id']) }}">{{ log['admin_username'] }}</a></td>
            <td><span class="badge">{{ log['action'] }}</span></td>
            <td class="small">
              {% if log['target_user_id'] %}
                <a href="{{ url_for('admin_user_detail', user_id=log['target_user_id']) }}">{{ log['target_username'] or log['target_user_id'] }}</a>
              {% else %}
                {{ log['target_type'] or '-' }}
              {% endif %}
            </td>
            <td class="small">{{ log['reason'] or log['new_value'] or '-' }}</td>
          </tr>
        {% endfor %}
      </table>
    </div>
    """
    return render_admin_page("Audit Log", "admin_audit_log", main,
                             logs=logs, admin_filter=admin_filter,
                             action_filter=action_filter, date_filter=date_filter)


@app.route("/admin/analytics")
@check_permission("view_analytics")
def admin_analytics():
    db = get_db()

    total_users  = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    active_today = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE last_seen >= datetime('now', '-1 day')"
    ).fetchone()["c"]
    new_today = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE DATE(created_at)=DATE('now')"
    ).fetchone()["c"]
    posts_total    = db.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"]
    messages_total = db.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    games_total    = db.execute("SELECT COUNT(*) AS c FROM games").fetchone()["c"]
    neo_total      = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM balances WHERE currency='NEO'"
    ).fetchone()["total"]
    assets_held    = db.execute(
        "SELECT COALESCE(SUM(quantity),0) AS total FROM asset_holdings"
    ).fetchone()["total"]

    main = """
    <h1>📊 Analytics</h1>
    <div class="admin-stats">
      <div class="admin-stat-card"><b>{{ total_users }}</b><span>Total Users</span></div>
      <div class="admin-stat-card"><b>{{ active_today }}</b><span>Active Today</span></div>
      <div class="admin-stat-card"><b>{{ new_today }}</b><span>New Today</span></div>
      <div class="admin-stat-card"><b>{{ neo_total }}</b><span>Neo in Circulation</span></div>
      <div class="admin-stat-card"><b>{{ posts_total }}</b><span>Posts</span></div>
      <div class="admin-stat-card"><b>{{ messages_total }}</b><span>Messages</span></div>
      <div class="admin-stat-card"><b>{{ games_total }}</b><span>Games</span></div>
      <div class="admin-stat-card"><b>{{ assets_held }}</b><span>Assets Held</span></div>
    </div>
    """
    return render_admin_page("Analytics", "admin_analytics", main,
                             total_users=total_users, active_today=active_today,
                             new_today=new_today, neo_total=neo_total,
                             posts_total=posts_total, messages_total=messages_total,
                             games_total=games_total, assets_held=assets_held)


# FIX: Permission changed from "view_analytics" to "manage_settings" so only
# admins with settings authority (super_admin, senior_admin) can access this.
@app.route("/admin/settings", methods=["GET", "POST"])
@check_permission("manage_settings")
def admin_settings():
    db = get_db()

    if request.method == "POST":
        action = request.form.get("action")
        me     = current_user()

        if action == "update_setting":
            key   = request.form.get("key", "").strip()
            value = request.form.get("value", "").strip()
            if key:
                db.execute(
                    """INSERT OR REPLACE INTO site_settings (key,value,updated_by_id,updated_at)
                       VALUES (?,?,?,?)""",
                    (key, value, me["id"], datetime.utcnow().isoformat())
                )
                admin_log("update_setting", new_value=value, reason=f"Set {key}")
                db.commit()
                flash("Setting updated.", "success")

        return redirect(url_for("admin_settings"))

    settings = db.execute("SELECT * FROM site_settings ORDER BY key").fetchall()

    main = """
    <h1>⚙ Admin Settings</h1>
    {% if settings %}
    <div class="card">
      <h3>Current Settings</h3>
      <table>
        <tr><th>Key</th><th>Value</th><th>Last Updated</th></tr>
        {% for s in settings %}
          <tr>
            <td>{{ s['key'] }}</td>
            <td>{{ s['value'] }}</td>
            <td class="small">{{ s['updated_at'][:16].replace('T',' ') }}</td>
          </tr>
        {% endfor %}
      </table>
    </div>
    {% endif %}

    <div class="card">
      <h3>Update Setting</h3>
      <form method="post">
        <input type="hidden" name="action" value="update_setting">
        <label>Key</label>
        <input name="key" placeholder="e.g. maintenance_mode" required>
        <label>Value</label>
        <input name="value" placeholder="e.g. 0 or 1" required>
        <button class="btn btn-yellow" type="submit" style="margin-top:8px">Save Setting</button>
      </form>
    </div>
    """
    return render_admin_page("Admin Settings", "admin_settings", main, settings=settings)


"""
================================================================================
SECTION 17: ERROR HANDLERS & STARTUP
================================================================================
"""

@app.errorhandler(403)
def forbidden(e):
    return render_page(
        "Forbidden",
        "<div class='card'><h2>403 — Forbidden</h2><p>You don't have access to this page.</p></div>"
    ), 403


@app.errorhandler(404)
def not_found(e):
    return render_page(
        "Not Found",
        "<div class='card'><h2>404 — Not Found</h2><p>That page doesn't exist.</p></div>"
    ), 404


# ── Startup ───────────────────────────────────────────────────────────────────
init_db()
seed_admin_and_demo()
seed_assets()
seed_demo_social_users()

print("=" * 70)
print(" NEOVERSE v3.0 ADMIN EDITION - Running at http://127.0.0.1:5000")
print("=" * 70)
print(" Admin account: username 'admin' / password 'admin123'")
print(" Features: Advanced roles, economy control, moderation, analytics, audit logs")
print("=" * 70)

if __name__ == "__main__":
    app.run(debug=True)
