"""
RWS Conference Room Manager — FastAPI Backend
Serves the React Native mobile app.
Run: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import logging
import os
import sys
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_AUTH  = os.path.join(BASE_DIR, "crm_auth.db")   # unified — shared with web app
DB_ROOMS = os.path.join(BASE_DIR, "conference_rooms.db")

# ── Auth helpers from shared utils ────────────────────────────────────────────
from utils.auth import (
    init_auth_db    as _auth_init,
    migrate_auth_db as _auth_migrate,
    sync_admin_flags as _auth_sync_admin,
    seed_employee   as _auth_seed_employee,
    verify_password as _auth_verify_password,
    update_user     as _auth_update_user,
)

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET environment variable is not set. "
        "Add it to your .env file before starting the server."
    )

ALGORITHM          = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7
ADMIN_IDS          = {
    e.strip().upper()
    for e in os.environ.get("ADMIN_EMPLOYEE_IDS", "RWSIPL493,TRWSIPL834").split(",")
    if e.strip()
}

ROOMS = {
    5: {"name": "5th Floor - Large Conference Room", "floor": 5, "size": "Large", "amenities": ["TV", "Whiteboard"]},
    4: {"name": "4th Floor - Large Conference Room", "floor": 4, "size": "Large", "amenities": ["TV", "Whiteboard"]},
    3: {"name": "3rd Floor - Small Conference Room",  "floor": 3, "size": "Small", "amenities": ["Whiteboard"]},
    2: {"name": "2nd Floor - Small Conference Room",  "floor": 2, "size": "Small", "amenities": ["Whiteboard"]},
}

TIME_SLOTS = [
    "8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "1:00 PM", "2:00 PM",  "3:00 PM",  "4:00 PM",  "5:00 PM",
    "6:00 PM", "7:00 PM",  "8:00 PM",
]

# ── App ────────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="RWS Conference Room Manager API", version="1.2.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["http://localhost:8501", "http://127.0.0.1:8501"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

security = HTTPBearer()

# ── Database helpers ───────────────────────────────────────────────────────────

@contextmanager
def auth_db():
    conn = sqlite3.connect(DB_AUTH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def rooms_db():
    conn = sqlite3.connect(DB_ROOMS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── JWT helpers ────────────────────────────────────────────────────────────────

def create_token(user_id: str, employee_id: str) -> str:
    payload = {
        "sub":  str(user_id),
        "code": employee_id,          # "code" kept for mobile backward-compat
        "exp":  datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat":  datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = str(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid token — please sign in again.")

    with auth_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="User not found or deactivated.")

    user = dict(row)
    # Real-time admin check: DB column OR env var (same logic as web app)
    user["is_admin"] = bool(user.get("is_admin")) or user["employee_id"].upper() in ADMIN_IDS
    return user


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return current_user


# ── Time helpers ───────────────────────────────────────────────────────────────

def to_24hr(time_str: str) -> str:
    return datetime.strptime(time_str, "%I:%M %p").strftime("%H:%M")


def to_12hr(time_str: str) -> str:
    dt = datetime.strptime(time_str, "%H:%M")
    formatted = dt.strftime("%I:%M %p")
    return formatted.lstrip("0") or formatted


# ── Room status (checks overrides first) ───────────────────────────────────────

def get_room_status(room_id: int) -> tuple[str, dict | None]:
    now_iso = datetime.now().isoformat()
    with rooms_db() as conn:
        # Auto-delete expired overrides
        conn.execute(
            "DELETE FROM room_overrides WHERE room_id = ? AND expires_at IS NOT NULL AND expires_at <= ?",
            (room_id, now_iso),
        )
        override = conn.execute(
            "SELECT * FROM room_overrides WHERE room_id = ?", (room_id,)
        ).fetchone()

    if override:
        ov = dict(override)
        return "occupied", {
            "id": None,
            "start_time":    "00:00",
            "end_time":      "23:59",
            "booked_by":     f"[Override] {ov['reason']}",
            "purpose":       ov["reason"],
            "is_override":   True,
            "overridden_by": ov["overridden_by"],
        }

    now        = datetime.now()
    today      = now.strftime("%Y-%m-%d")
    current_hm = now.strftime("%H:%M")
    next_upcoming = None

    with rooms_db() as conn:
        bookings = [
            dict(r) for r in conn.execute(
                "SELECT * FROM bookings WHERE room_id = ? AND date = ? ORDER BY start_time",
                (room_id, today),
            ).fetchall()
        ]

    for b in bookings:
        if b["start_time"] <= current_hm < b["end_time"]:
            return "occupied", b
        if b["start_time"] > current_hm and next_upcoming is None:
            next_upcoming = b

    return ("booked", next_upcoming) if next_upcoming else ("available", None)


# ── DB initialisation ──────────────────────────────────────────────────────────

def init_crm_auth_db() -> None:
    """Bootstrap crm_auth.db: create tables, migrate, sync admin flags, seed employees."""
    _auth_init(DB_AUTH)
    _auth_migrate(DB_AUTH)
    _auth_sync_admin(DB_AUTH)

    try:
        from employees_data import EMPLOYEES
        for code, name, branch, dept, desig in EMPLOYEES:
            _auth_seed_employee(code, name, branch, dept, desig, DB_AUTH)
    except ImportError:
        pass  # employees_data.py is optional — skip if not present


def init_rooms_db() -> None:
    with rooms_db() as conn:
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
                created_at    TEXT    NOT NULL,
                expires_at    TEXT
            )
        """)
        # Migrate: add expires_at if it doesn't exist yet
        try:
            conn.execute("ALTER TABLE room_overrides ADD COLUMN expires_at TEXT")
        except Exception:
            pass  # column already exists


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    init_crm_auth_db()
    init_rooms_db()
    with auth_db() as conn:
        deleted = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),)
        ).rowcount
    logger.info("Startup complete. Pruned %d expired session(s).", deleted)


# ── Pydantic models ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    employee_code: str    # field name kept for mobile backward-compatibility
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class BookingRequest(BaseModel):
    room_id:    int
    date:       str
    start_time: str
    end_time:   str
    purpose:    Optional[str] = ""

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format.")
        return v


class CheckRequest(BaseModel):
    room_id:    int
    date:       str
    start_time: str
    end_time:   str

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date must be in YYYY-MM-DD format.")
        return v


class AdminOverrideRequest(BaseModel):
    reason:        str = "Maintenance"
    expires_hours: Optional[int] = 24  # auto-clear after N hours; None = never


# ── Auth routes ────────────────────────────────────────────────────────────────

@app.post("/api/v1/auth/login")
@limiter.limit("10/minute")
def login(req: LoginRequest, request: Request):
    employee_id = req.employee_code.strip().upper()

    with auth_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE employee_id = ? AND is_active = 1", (employee_id,)
        ).fetchone()

    if not row:
        logger.warning("Failed login attempt for employee_id=%s", employee_id)
        raise HTTPException(status_code=401, detail="Invalid employee code or password.")

    user = dict(row)
    stored_hash = user.get("password_hash") or ""
    if not stored_hash or not _auth_verify_password(req.password, stored_hash):
        logger.warning("Failed login attempt for employee_id=%s (wrong password)", employee_id)
        raise HTTPException(status_code=401, detail="Invalid employee code or password.")

    with auth_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now().isoformat(), user["id"]),
        )

    is_admin = bool(user.get("is_admin")) or employee_id in ADMIN_IDS
    logger.info("Login successful: employee_id=%s is_admin=%s", employee_id, is_admin)

    return {
        "token": create_token(user["id"], employee_id),
        "user": {
            "id":                   user["id"],
            "employee_code":        employee_id,   # mobile app expects this field name
            "name":                 user["name"],
            "branch":               user.get("branch") or "",
            "department":           user.get("department") or "",
            "designation":          user.get("designation") or "",
            "must_change_password": bool(user.get("must_change_password")),
            "is_admin":             is_admin,
        },
    }


@app.get("/api/v1/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id":                   current_user["id"],
        "employee_code":        current_user["employee_id"],
        "name":                 current_user["name"],
        "branch":               current_user.get("branch") or "",
        "department":           current_user.get("department") or "",
        "designation":          current_user.get("designation") or "",
        "must_change_password": bool(current_user.get("must_change_password")),
        "is_admin":             current_user.get("is_admin", False),
    }


@app.put("/api/v1/auth/change-password")
def change_password(req: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    stored_hash = current_user.get("password_hash", "")
    if not stored_hash or not _auth_verify_password(req.old_password, stored_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters.")

    result = _auth_update_user(current_user["id"], {"password": req.new_password}, DB_AUTH)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Clear the forced-change flag
    with auth_db() as conn:
        conn.execute(
            "UPDATE users SET must_change_password = 0 WHERE id = ?",
            (current_user["id"],),
        )

    return {"message": "Password updated successfully."}


# ── Room routes ────────────────────────────────────────────────────────────────

@app.get("/api/v1/rooms")
def list_rooms(current_user: dict = Depends(get_current_user)):
    result = []
    for room_id, room in sorted(ROOMS.items(), reverse=True):
        status, booking = get_room_status(room_id)

        with rooms_db() as conn:
            override_row = conn.execute(
                "SELECT * FROM room_overrides WHERE room_id = ?", (room_id,)
            ).fetchone()

        has_override    = override_row is not None
        override_reason = dict(override_row)["reason"] if override_row else None

        entry: dict = {
            "id":             room_id,
            "name":           room["name"],
            "floor":          room["floor"],
            "size":           room["size"],
            "amenities":      room["amenities"],
            "status":         status,
            "booking":        None,
            "has_override":   has_override,
            "override_reason": override_reason,
        }
        if booking and not booking.get("is_override"):
            entry["booking"] = {
                "id":         booking["id"],
                "start_time": to_12hr(booking["start_time"]),
                "end_time":   to_12hr(booking["end_time"]),
                "booked_by":  booking["booked_by"],
                "purpose":    booking["purpose"] or "",
            }
        result.append(entry)
    return result


@app.get("/api/v1/time-slots")
def time_slots(current_user: dict = Depends(get_current_user)):
    return {"slots": TIME_SLOTS}


# ── Availability check (dry-run — no booking created) ─────────────────────────

@app.post("/api/v1/bookings/check")
def check_availability(req: CheckRequest, current_user: dict = Depends(get_current_user)):
    if req.room_id not in ROOMS:
        raise HTTPException(status_code=400, detail="Invalid room ID.")

    try:
        s24 = to_24hr(req.start_time)
        e24 = to_24hr(req.end_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use e.g. '9:00 AM'.")

    with rooms_db() as conn:
        override = conn.execute(
            "SELECT * FROM room_overrides WHERE room_id = ?", (req.room_id,)
        ).fetchone()

    if override:
        return {
            "available": False,
            "conflicts": [{
                "start_time": "All day",
                "end_time":   "",
                "booked_by":  f"Admin override: {dict(override)['reason']}",
                "purpose":    dict(override)["reason"],
            }],
        }

    with rooms_db() as conn:
        existing = [
            dict(r) for r in conn.execute(
                "SELECT * FROM bookings WHERE room_id = ? AND date = ?",
                (req.room_id, req.date),
            ).fetchall()
        ]

    conflicts = [
        {
            "start_time": to_12hr(b["start_time"]),
            "end_time":   to_12hr(b["end_time"]),
            "booked_by":  b["booked_by"],
            "purpose":    b["purpose"] or "",
        }
        for b in existing
        if not (e24 <= b["start_time"] or s24 >= b["end_time"])
    ]

    return {"available": len(conflicts) == 0, "conflicts": conflicts}


# ── Schedule routes ────────────────────────────────────────────────────────────

@app.get("/api/v1/schedule/today")
def today_schedule(current_user: dict = Depends(get_current_user)):
    today  = datetime.now().strftime("%Y-%m-%d")
    now_hm = datetime.now().strftime("%H:%M")
    result = []

    for room_id, room in sorted(ROOMS.items(), reverse=True):
        with rooms_db() as conn:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE room_id = ? AND date = ? ORDER BY start_time",
                (room_id, today),
            ).fetchall()

        bookings = []
        for r in rows:
            b = dict(r)
            bookings.append({
                "id":         b["id"],
                "start_time": to_12hr(b["start_time"]),
                "end_time":   to_12hr(b["end_time"]),
                "booked_by":  b["booked_by"],
                "purpose":    b["purpose"] or "",
                "is_now":     b["start_time"] <= now_hm < b["end_time"],
                "can_cancel": current_user.get("is_admin") or
                              b["booked_by"].lower() == current_user["name"].lower(),
            })

        result.append({
            "room_id":   room_id,
            "room_name": room["name"],
            "floor":     room_id,
            "bookings":  bookings,
        })

    return result


# ── Booking routes ─────────────────────────────────────────────────────────────

@app.post("/api/v1/bookings")
def create_booking(req: BookingRequest, current_user: dict = Depends(get_current_user)):
    if req.room_id not in ROOMS:
        raise HTTPException(status_code=400, detail="Invalid room ID.")

    try:
        s24 = to_24hr(req.start_time)
        e24 = to_24hr(req.end_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use e.g. '9:00 AM'.")

    if s24 >= e24:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    with rooms_db() as conn:
        override = conn.execute(
            "SELECT * FROM room_overrides WHERE room_id = ?", (req.room_id,)
        ).fetchone()
    if override:
        raise HTTPException(
            status_code=409,
            detail=f"Room is currently marked as occupied by admin: {dict(override)['reason']}",
        )

    with rooms_db() as conn:
        existing = [
            dict(r) for r in conn.execute(
                "SELECT * FROM bookings WHERE room_id = ? AND date = ?",
                (req.room_id, req.date),
            ).fetchall()
        ]

    for b in existing:
        if not (e24 <= b["start_time"] or s24 >= b["end_time"]):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Room already booked from {to_12hr(b['start_time'])} to "
                    f"{to_12hr(b['end_time'])} by {b['booked_by']}."
                ),
            )

    try:
        with rooms_db() as conn:
            cursor = conn.execute(
                """INSERT INTO bookings
                   (room_id, date, start_time, end_time, booked_by, purpose, booked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (req.room_id, req.date, s24, e24,
                 current_user["name"], req.purpose or "",
                 datetime.now().isoformat()),
            )
            booking_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Booking conflict — slot just taken.")

    return {
        "id":         booking_id,
        "room_id":    req.room_id,
        "room_name":  ROOMS[req.room_id]["name"],
        "date":       req.date,
        "start_time": req.start_time,
        "end_time":   req.end_time,
        "booked_by":  current_user["name"],
        "purpose":    req.purpose or "",
    }


@app.delete("/api/v1/bookings/{booking_id}")
def cancel_booking(booking_id: int, current_user: dict = Depends(get_current_user)):
    with rooms_db() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Booking not found.")

    booking  = dict(row)
    is_owner = booking["booked_by"].lower() == current_user["name"].lower()
    if not current_user.get("is_admin") and not is_owner:
        raise HTTPException(status_code=403, detail="You can only cancel your own bookings.")

    with rooms_db() as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))

    return {"message": "Booking cancelled successfully."}


@app.get("/api/v1/bookings/search")
def search_bookings(
    name:      Optional[str] = None,
    room_id:   Optional[int] = None,
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    query  = "SELECT * FROM bookings WHERE 1=1"
    params: list = []

    if name:
        query += " AND booked_by LIKE ?"
        params.append(f"%{name}%")
    if room_id:
        query += " AND room_id = ?"
        params.append(room_id)
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)

    query += " ORDER BY date DESC, start_time LIMIT 100"

    with rooms_db() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "id":         r["id"],
            "room_id":    r["room_id"],
            "room_name":  ROOMS.get(r["room_id"], {}).get("name", f"Room {r['room_id']}"),
            "date":       r["date"],
            "start_time": to_12hr(r["start_time"]),
            "end_time":   to_12hr(r["end_time"]),
            "booked_by":  r["booked_by"],
            "purpose":    r["purpose"] or "",
            "can_cancel": current_user.get("is_admin") or
                          r["booked_by"].lower() == current_user["name"].lower(),
        }
        for r in rows
    ]


# ── Admin override routes ──────────────────────────────────────────────────────

@app.post("/api/v1/admin/rooms/{room_id}/override")
def set_room_override(
    room_id: int,
    req: AdminOverrideRequest,
    current_user: dict = Depends(require_admin),
):
    if room_id not in ROOMS:
        raise HTTPException(status_code=400, detail="Invalid room ID.")

    reason = req.reason.strip() or "Maintenance"
    now = datetime.now()
    expires_at = (
        (now + timedelta(hours=req.expires_hours)).isoformat()
        if req.expires_hours
        else None
    )
    with rooms_db() as conn:
        conn.execute(
            """INSERT INTO room_overrides (room_id, reason, overridden_by, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(room_id) DO UPDATE SET
                   reason        = excluded.reason,
                   overridden_by = excluded.overridden_by,
                   created_at    = excluded.created_at,
                   expires_at    = excluded.expires_at""",
            (room_id, reason, current_user["name"], now.isoformat(), expires_at),
        )

    logger.info(
        "Admin override set: room=%s reason=%s by=%s expires_at=%s",
        room_id, reason, current_user["name"], expires_at or "never",
    )
    return {
        "message":    f"{ROOMS[room_id]['name']} marked as occupied.",
        "room_id":    room_id,
        "reason":     reason,
        "set_by":     current_user["name"],
        "expires_at": expires_at,
    }


@app.delete("/api/v1/admin/rooms/{room_id}/override")
def clear_room_override(
    room_id: int,
    current_user: dict = Depends(require_admin),
):
    if room_id not in ROOMS:
        raise HTTPException(status_code=400, detail="Invalid room ID.")

    with rooms_db() as conn:
        cursor = conn.execute(
            "DELETE FROM room_overrides WHERE room_id = ?", (room_id,)
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="No active override for this room.")

    logger.info("Admin override cleared: room=%s by=%s", room_id, current_user["name"])
    return {"message": f"Override cleared for {ROOMS[room_id]['name']}."}


@app.get("/api/v1/admin/overrides")
def list_overrides(current_user: dict = Depends(require_admin)):
    with rooms_db() as conn:
        rows = conn.execute("SELECT * FROM room_overrides").fetchall()
    return [
        {
            "room_id":       r["room_id"],
            "room_name":     ROOMS.get(r["room_id"], {}).get("name", f"Room {r['room_id']}"),
            "reason":        r["reason"],
            "overridden_by": r["overridden_by"],
            "created_at":    r["created_at"],
        }
        for r in rows
    ]
