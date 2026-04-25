-- crm_auth.db schema  (unified web + mobile auth)
-- Used by: app.py (web), backend/main.py (mobile API)
-- Managed by: utils/auth.py — init_auth_db(), migrate_auth_db()
-- Run db_example/setup.py to create this database locally with sample users.
--
-- Password hash format: "{salt_hex}:{dk_hex}"
--   PBKDF2-HMAC-SHA256, 260 000 iterations, random 32-byte hex salt per user.
--   Default password for sample users = their employee ID.
--
-- Note: mobile_auth.db (fixed-salt, INTEGER PK) is retired. All users are now in crm_auth.db.

CREATE TABLE IF NOT EXISTS users (
    id                   TEXT    PRIMARY KEY,          -- secrets.token_hex(16)
    employee_id          TEXT    UNIQUE NOT NULL,      -- e.g. RWSIPL007
    name                 TEXT    NOT NULL,
    email                TEXT    UNIQUE,
    phone                TEXT    UNIQUE,
    password_hash        TEXT,                         -- "{salt_hex}:{dk_hex}" or NULL (OAuth-only)
    google_id            TEXT    UNIQUE,
    zoho_id              TEXT    UNIQUE,
    is_admin             INTEGER DEFAULT 0,
    is_active            INTEGER DEFAULT 1,
    branch               TEXT    DEFAULT '',
    department           TEXT    DEFAULT '',
    designation          TEXT    DEFAULT '',
    must_change_password INTEGER DEFAULT 0,            -- 1 on first login with seeded default password
    created_at           TEXT    DEFAULT (datetime('now')),
    last_login           TEXT                          -- NULL until first login
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT    NOT NULL,
    channel    TEXT    NOT NULL,                       -- 'email' | 'phone'
    code       TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    used       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,                    -- secrets.token_urlsafe(32)
    user_id    TEXT    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now')),
    expires_at TEXT    NOT NULL
);

-- Example users (password_hash shown is a placeholder — run setup.py to generate real hashes)
-- Admin employees are also defined by ADMIN_EMPLOYEE_IDS env var for real-time fallback.
INSERT OR IGNORE INTO users
    (id, employee_id, name, branch, department, designation, password_hash, is_admin, must_change_password)
VALUES
    ('<token>', 'RWSIPL001', 'Priya Sharma',  'Pune', 'Engineering', 'Software Engineer', '<run setup.py>', 0, 1),
    ('<token>', 'RWSIPL002', 'Rahul Verma',   'Pune', 'Engineering', 'Team Lead',         '<run setup.py>', 0, 1),
    ('<token>', 'RWSIPL003', 'Anita Desai',   'Pune', 'Design',      'UI/UX Designer',    '<run setup.py>', 0, 1),
    ('<token>', 'RWSIPL493', 'Admin User',    'Pune', 'Management',  'Manager',           '<run setup.py>', 1, 1),
    ('<token>', 'TRWSIPL834','Admin Two',     'Pune', 'Management',  'Senior Manager',    '<run setup.py>', 1, 1);

-- To generate a valid password_hash in Python:
-- import secrets, hashlib
-- salt = secrets.token_hex(32)
-- dk = hashlib.pbkdf2_hmac("sha256", b"RWSIPL001", salt.encode(), 260000).hex()
-- stored = f"{salt}:{dk}"
