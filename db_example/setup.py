"""
Fresh database setup script.
Creates conference_rooms.db and crm_auth.db from scratch with sample data.
Run from the project root: python db_example/setup.py

Password hashing matches utils/auth.py exactly:
  PBKDF2-HMAC-SHA256, 260 000 iterations, random 32-byte hex salt per user.
  Stored as  "{salt_hex}:{dk_hex}"
  Default password for each sample user = their employee ID.
"""
import os
import secrets
import sqlite3
import sys
from datetime import datetime
from hashlib import pbkdf2_hmac

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _hash_pw(password: str) -> tuple[str, str]:
    """Return (dk_hex, salt_hex) — same logic as utils/auth.py _hash_pw()."""
    salt = secrets.token_hex(32)
    dk = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
    return dk, salt


def setup_rooms_db():
    path = os.path.join(ROOT, "conference_rooms.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id    INTEGER NOT NULL,
            date       TEXT    NOT NULL,
            start_time TEXT    NOT NULL,
            end_time   TEXT    NOT NULL,
            booked_by  TEXT    NOT NULL,
            purpose    TEXT,
            booked_at  TEXT    NOT NULL,
            UNIQUE(room_id, date, start_time, end_time)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_room_date ON bookings(room_id, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date      ON bookings(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booked_by ON bookings(booked_by)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS room_overrides (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id       INTEGER NOT NULL UNIQUE,
            reason        TEXT    NOT NULL DEFAULT 'Maintenance',
            overridden_by TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        )
    """)

    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().isoformat()
    sample_bookings = [
        (5, today, "09:00", "10:00", "Priya Sharma",  "Sprint planning", now),
        (5, today, "14:00", "15:00", "Rahul Verma",   "Client call",     now),
        (4, today, "10:00", "11:00", "Anita Desai",   "Design review",   now),
        (3, today, "11:00", "12:00", "Suresh Nair",   "Team standup",    now),
        (2, today, "15:00", "16:00", "Meena Pillai",  "HR interview",    now),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO bookings (room_id,date,start_time,end_time,booked_by,purpose,booked_at) VALUES (?,?,?,?,?,?,?)",
        sample_bookings,
    )
    conn.commit()
    conn.close()
    print(f"Created: {path}")


def setup_crm_auth_db():
    """
    Unified auth database for both the web app (app.py) and mobile API (backend/main.py).
    Schema mirrors utils/auth.py init_auth_db().
    """
    path = os.path.join(ROOT, "crm_auth.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                   TEXT    PRIMARY KEY,
            employee_id          TEXT    UNIQUE NOT NULL,
            name                 TEXT    NOT NULL,
            email                TEXT    UNIQUE,
            phone                TEXT    UNIQUE,
            password_hash        TEXT,
            google_id            TEXT    UNIQUE,
            zoho_id              TEXT    UNIQUE,
            is_admin             INTEGER DEFAULT 0,
            is_active            INTEGER DEFAULT 1,
            branch               TEXT    DEFAULT '',
            department           TEXT    DEFAULT '',
            designation          TEXT    DEFAULT '',
            must_change_password INTEGER DEFAULT 0,
            created_at           TEXT    DEFAULT (datetime('now')),
            last_login           TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS otp_codes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT    NOT NULL,
            channel    TEXT    NOT NULL,
            code       TEXT    NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT    PRIMARY KEY,
            user_id    TEXT    NOT NULL,
            created_at TEXT    DEFAULT (datetime('now')),
            expires_at TEXT    NOT NULL
        )
    """)

    # Sample employees — admin users match ADMIN_EMPLOYEE_IDS default in .env.example
    sample_employees = [
        ("RWSIPL001", "Priya Sharma",   "Pune", "Engineering", "Software Engineer",  False),
        ("RWSIPL002", "Rahul Verma",    "Pune", "Engineering", "Team Lead",           False),
        ("RWSIPL003", "Anita Desai",    "Pune", "Design",      "UI/UX Designer",      False),
        ("RWSIPL004", "Suresh Nair",    "Pune", "Operations",  "Operations Manager",  False),
        ("RWSIPL493", "Admin User",     "Pune", "Management",  "Manager",             True),
        ("TRWSIPL834","Admin Two",      "Pune", "Management",  "Senior Manager",      True),
    ]

    for code, name, branch, dept, desig, is_admin in sample_employees:
        already = conn.execute(
            "SELECT 1 FROM users WHERE employee_id = ?", (code,)
        ).fetchone()
        if not already:
            user_id = secrets.token_hex(16)
            dk, salt = _hash_pw(code)          # default password = employee ID
            pw_stored = f"{salt}:{dk}"
            conn.execute(
                """INSERT INTO users
                   (id, employee_id, name, branch, department, designation,
                    password_hash, is_admin, must_change_password)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (user_id, code, name, branch, dept, desig, pw_stored, int(is_admin)),
            )
            print(f"  User: {code} / {name}  (default password: {code}){' [admin]' if is_admin else ''}")

    conn.commit()
    conn.close()
    print(f"Created: {path}")


if __name__ == "__main__":
    print("Setting up databases...")
    setup_rooms_db()
    setup_crm_auth_db()
    print("\nDone. Start the app with: python start.py")
    print("Admin employees: RWSIPL493, TRWSIPL834  (set ADMIN_EMPLOYEE_IDS in .env to change)")
    print("\nNote: mobile_auth.db is retired. Both web and mobile now share crm_auth.db.")
