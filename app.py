"""
Conference Room Manager
Track availability and bookings for conference rooms.
Session-based auth: email+password, email OTP, phone OTP, Google OAuth2, Zoho OAuth2.
"""
import os
import sqlite3
import streamlit as st
from datetime import datetime

from utils.auth import (
    init_auth_db,
    migrate_auth_db,
    sync_admin_flags,
    get_user_by_session,
    logout_session,
    update_user as _auth_update_user,
    register_user as _auth_register,
    complete_oauth_registration as _auth_complete_oauth,
    login_password as _auth_login_password,
    send_email_otp as _auth_send_email_otp,
    login_email_otp as _auth_login_email_otp,
    send_phone_otp as _auth_send_phone_otp,
    login_phone_otp as _auth_login_phone_otp,
    google_auth_url as _auth_google_url,
    google_callback as _auth_google_callback,
    zoho_auth_url as _auth_zoho_url,
    zoho_callback as _auth_zoho_callback,
)

# ── Configuration ──────────────────────────────────────────────────────────────

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conference_rooms.db")

ROOMS = {
    5: {"name": "5th Floor - Large Conference Room", "floor": 5, "size": "Large", "capacity": 20, "amenities": ["TV", "Whiteboard"]},
    4: {"name": "4th Floor - Large Conference Room", "floor": 4, "size": "Large", "capacity": 20, "amenities": ["TV", "Whiteboard"]},
    3: {"name": "3rd Floor - Small Conference Room",  "floor": 3, "size": "Small", "capacity": 5,  "amenities": ["Whiteboard"]},
    2: {"name": "2nd Floor - Small Conference Room",  "floor": 2, "size": "Small", "capacity": 5,  "amenities": ["Whiteboard"]},
}

TIME_SLOTS = [
    "8:00 AM", "9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
    "1:00 PM", "2:00 PM",  "3:00 PM",  "4:00 PM",  "5:00 PM",
    "6:00 PM", "7:00 PM",  "8:00 PM",
]


# ── Database ───────────────────────────────────────────────────────────────────

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute('''
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
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_room_date ON bookings(room_id, date)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_date      ON bookings(date)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_booked_by ON bookings(booked_by)')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS room_overrides (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id       INTEGER NOT NULL UNIQUE,
                reason        TEXT    NOT NULL DEFAULT 'Maintenance',
                overridden_by TEXT    NOT NULL,
                created_at    TEXT    NOT NULL
            )
        ''')


# ── Time helpers ───────────────────────────────────────────────────────────────

def to_24hr(time_str: str) -> str:
    return datetime.strptime(time_str, "%I:%M %p").strftime("%H:%M")


def to_12hr(time_str: str) -> str:
    dt = datetime.strptime(time_str, "%H:%M")
    formatted = dt.strftime("%I:%M %p")
    return formatted.lstrip("0") or formatted


# ── Cached query helpers ───────────────────────────────────────────────────────
# TTL=15s: multiple status checks in one render share the same DB result.
# After any write, call st.cache_data.clear() before st.rerun().

@st.cache_data(ttl=15)
def get_bookings_for_date(room_id: int, date: str) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            '''SELECT id, start_time, end_time, booked_by, purpose, booked_at
               FROM bookings WHERE room_id = ? AND date = ?
               ORDER BY start_time''',
            (room_id, date),
        ).fetchall()
    return [
        {"id": r[0], "start_time": r[1], "end_time": r[2],
         "booked_by": r[3], "purpose": r[4] or "", "booked_at": r[5]}
        for r in rows
    ]


@st.cache_data(ttl=15)
def get_active_override(room_id: int) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM room_overrides WHERE room_id = ?", (room_id,)
        ).fetchone()
    if not row:
        return None
    return {"room_id": row[1], "reason": row[2], "overridden_by": row[3], "created_at": row[4]}


def get_current_status(room_id: int) -> tuple[str, dict | None]:
    """Return ('occupied'|'booked'|'available', booking_or_None).
    Admin overrides take priority over normal booking checks.
    """
    override = get_active_override(room_id)
    if override:
        return "occupied", {
            "id": None, "start_time": "00:00", "end_time": "23:59",
            "booked_by": f"[Override] {override['reason']}",
            "purpose": override["reason"], "is_override": True,
        }

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_hm = now.strftime("%H:%M")
    next_upcoming = None

    for booking in get_bookings_for_date(room_id, today):
        if booking["start_time"] <= current_hm < booking["end_time"]:
            return "occupied", booking
        if booking["start_time"] > current_hm and next_upcoming is None:
            next_upcoming = booking

    if next_upcoming:
        return "booked", next_upcoming
    return "available", None


def get_conflicts(room_id: int, date: str, start_time: str, end_time: str) -> list[dict]:
    s24 = to_24hr(start_time)
    e24 = to_24hr(end_time)
    return [
        b for b in get_bookings_for_date(room_id, date)
        if not (e24 <= b["start_time"] or s24 >= b["end_time"])
    ]


# ── Write helpers (all clear cache before returning) ──────────────────────────

def book_room(room_id: int, date: str, start_time: str, end_time: str,
              booked_by: str, purpose: str) -> bool:
    try:
        with get_db_connection() as conn:
            conn.execute(
                '''INSERT INTO bookings
                       (room_id, date, start_time, end_time, booked_by, purpose, booked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (room_id, date, to_24hr(start_time), to_24hr(end_time),
                 booked_by, purpose, datetime.now().isoformat()),
            )
        st.cache_data.clear()
        return True
    except sqlite3.IntegrityError:
        return False


def cancel_booking(booking_id: int) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    st.cache_data.clear()
    return cursor.rowcount > 0


def set_room_override(room_id: int, reason: str, overridden_by: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO room_overrides (room_id, reason, overridden_by, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(room_id) DO UPDATE SET
                   reason        = excluded.reason,
                   overridden_by = excluded.overridden_by,
                   created_at    = excluded.created_at""",
            (room_id, reason.strip() or "Maintenance", overridden_by, datetime.now().isoformat()),
        )
    st.cache_data.clear()


def clear_room_override(room_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("DELETE FROM room_overrides WHERE room_id = ?", (room_id,))
    st.cache_data.clear()


def search_bookings(booked_by=None, room_id=None,
                    date_from=None, date_to=None) -> list[dict]:
    query = '''SELECT id, room_id, date, start_time, end_time,
                      booked_by, purpose, booked_at
               FROM bookings WHERE 1=1'''
    params: list = []
    if booked_by:
        query += " AND booked_by LIKE ?"
        params.append(f"%{booked_by}%")
    if room_id:
        query += " AND room_id = ?"
        params.append(room_id)
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    query += " ORDER BY date DESC, start_time"

    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"id": r[0], "room_id": r[1], "date": r[2], "start_time": r[3],
         "end_time": r[4], "booked_by": r[5], "purpose": r[6] or "", "booked_at": r[7]}
        for r in rows
    ]


# ── UI helpers ─────────────────────────────────────────────────────────────────

def _room_label(room_id: int) -> str:
    r = ROOMS[room_id]
    return f"Floor {r['floor']} – {r['size']}"


def _render_cancel_button(booking: dict, context_key: str, is_admin: bool = False) -> None:
    confirm_key = f"confirm_{context_key}_{booking['id']}"
    name_key    = f"name_{context_key}_{booking['id']}"
    cancel_key  = f"cancel_{context_key}_{booking['id']}"

    if st.button("Cancel", key=cancel_key, help="Cancel this booking"):
        st.session_state[confirm_key] = True

    if st.session_state.get(confirm_key):
        if is_admin:
            st.caption(f"Cancel booking by **{booking['booked_by']}**?")
            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("Yes, Cancel", key=f"do_cancel_{context_key}_{booking['id']}", type="primary"):
                    if cancel_booking(booking["id"]):
                        st.success("Booking cancelled.")
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    else:
                        st.error("Could not cancel — it may have already been removed.")
            with col_b:
                if st.button("Never mind", key=f"abort_{context_key}_{booking['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
        else:
            entered = st.text_input(
                f"Type your name to confirm cancellation of the {to_12hr(booking['start_time'])} slot",
                key=name_key,
            )
            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("Confirm", key=f"do_cancel_{context_key}_{booking['id']}", type="primary"):
                    if entered.strip().lower() == booking["booked_by"].strip().lower():
                        if cancel_booking(booking["id"]):
                            st.success("Booking cancelled.")
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                        else:
                            st.error("Could not cancel — it may have already been removed.")
                    else:
                        st.error("Name doesn't match. Cancellation not confirmed.")
            with col_b:
                if st.button("Never mind", key=f"abort_{context_key}_{booking['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()


# ── Styles ─────────────────────────────────────────────────────────────────────

_STRUCTURAL_CSS = """
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ── Pulse-dot keyframes ─────────────────────────────────────── */
    @keyframes pdot-avail  { 0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,.55)} 60%{box-shadow:0 0 0 7px rgba(52,211,153,0)} }
    @keyframes pdot-occup  { 0%,100%{box-shadow:0 0 0 0 rgba(248,113,113,.55)} 60%{box-shadow:0 0 0 7px rgba(248,113,113,0)} }
    @keyframes pdot-booked { 0%,100%{box-shadow:0 0 0 0 rgba(251,191,36,.55)}  60%{box-shadow:0 0 0 7px rgba(251,191,36,0)} }
    @keyframes pdot-overrd { 0%,100%{box-shadow:0 0 0 0 rgba(192,132,252,.55)} 60%{box-shadow:0 0 0 7px rgba(192,132,252,0)} }

    .pdot {
        display: inline-block; width: 7px; height: 7px;
        border-radius: 50%; vertical-align: middle;
        margin-right: 3px; position: relative; top: -1px; flex-shrink: 0;
    }
    .pill-available .pdot { background:#34d399; animation: pdot-avail  2.4s ease-in-out infinite; }
    .pill-occupied  .pdot { background:#f87171; animation: pdot-occup  1.6s ease-in-out infinite; }
    .pill-booked    .pdot { background:#fbbf24; animation: pdot-booked 3.0s ease-in-out infinite; }
    .pill-override  .pdot { background:#c084fc; animation: pdot-overrd 3.5s ease-in-out infinite; }

    /* ── Fade-in for main content ────────────────────────────────── */
    @keyframes crm-fadein { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
    .room-card, .sched-row, .hist-row {
        animation: crm-fadein 0.35s ease both;
    }

    /* ── Navbar brand ────────────────────────────────────────────── */
    .crm-navbar-brand { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
    .crm-navbar-logo  { height: 64px; width: auto; object-fit: contain; }

    /* ── Top-nav user chip ───────────────────────────────────────── */
    .topnav-user-chip {
        display: flex; align-items: center; gap: 7px;
        height: 38px; padding: 0 4px;
        font-size: 0.88rem; font-weight: 600; white-space: nowrap;
    }
    .topnav-admin-badge {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em;
        text-transform: uppercase; padding: 2px 7px; border-radius: 999px;
        background: rgba(0,175,239,0.15); color: #00AFEF;
        border: 1px solid rgba(0,175,239,0.35); flex-shrink: 0;
    }

    /* ── Top-nav buttons uniform height ─────────────────────────── */
    #topnav_profile button, #topnav_back button, #topnav_signout button,
    div[data-testid="stPopover"] > div > button {
        height: 38px !important; min-height: 38px !important; max-height: 38px !important;
        padding-top: 0 !important; padding-bottom: 0 !important;
        font-size: 0.875rem !important; font-weight: 600 !important;
        border-radius: 10px !important; width: 100% !important; box-sizing: border-box !important;
    }
    #topnav_signout [data-testid="stBaseButton-primary"] {
        background: #00AFEF !important; background-color: #00AFEF !important;
        color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;
        border: none !important; box-shadow: 0 2px 10px rgba(0,175,239,0.35) !important;
    }
    #topnav_signout [data-testid="stBaseButton-primary"]:hover {
        background: #0099d4 !important; background-color: #0099d4 !important;
    }

    /* ── Hero ────────────────────────────────────────────────────── */
    .hero { border-radius: 24px; padding: 28px 32px; margin-bottom: 28px; }
    .hero-title {
        font-family: 'Plus Jakarta Sans', 'Space Grotesk', sans-serif;
        font-size: 2.5rem; font-weight: 700;
        letter-spacing: -0.03em; margin: 0 0 6px 0;
        background: linear-gradient(135deg, #60a5fa, #34d399);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .hero-sub { font-size: 1rem; margin: 0 0 14px; }
    .hero-stats-row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 2px; }
    .hero-stat-chip {
        display: inline-flex; align-items: center; gap: 5px;
        font-size: 0.78rem; font-weight: 700; letter-spacing: 0.04em;
        padding: 4px 12px; border-radius: 999px;
        border-width: 1px; border-style: solid;
    }
    .stat-available { background: rgba(16,185,129,0.14); border-color: rgba(16,185,129,0.32); color: #34d399; }
    .stat-occupied  { background: rgba(239,68,68,0.14);  border-color: rgba(239,68,68,0.32);  color: #f87171; }
    .stat-booked    { background: rgba(234,179,8,0.14);  border-color: rgba(234,179,8,0.32);  color: #fbbf24; }
    .stat-override  { background: rgba(168,85,247,0.14); border-color: rgba(168,85,247,0.32); color: #c084fc; }

    /* ── Section label ───────────────────────────────────────────── */
    .section-label {
        font-size: 0.75rem; font-weight: 700;
        letter-spacing: 0.13em; text-transform: uppercase; margin-bottom: 14px;
    }

    /* ── Section header row (label + timestamp) ─────────────────── */
    .crm-section-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 14px;
    }
    .crm-section-ts { font-size: 0.72rem; }

    /* ── Room cards ──────────────────────────────────────────────── */
    .room-card { border-radius: 20px; padding: 20px 18px; min-height: 170px; border-width: 1px; border-style: solid; }
    .room-card-hdr {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 8px;
    }
    .room-floor { font-family: 'Plus Jakarta Sans', 'Space Grotesk', sans-serif; font-size: 1.2rem; font-weight: 700; }
    .status-pill {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.10em;
        text-transform: uppercase; margin-bottom: 10px; border-width: 1px; border-style: solid;
    }
    .pill-available { background: rgba(16,185,129,0.20);  color: #34d399; border-color: rgba(16,185,129,0.35); }
    .pill-occupied  { background: rgba(239,68,68,0.20);   color: #f87171; border-color: rgba(239,68,68,0.35); }
    .pill-booked    { background: rgba(234,179,8,0.20);   color: #fbbf24; border-color: rgba(234,179,8,0.35); }
    .pill-override  { background: rgba(168,85,247,0.20);  color: #c084fc; border-color: rgba(168,85,247,0.35); }
    .room-meta  { font-size: 0.82rem; margin: 3px 0; }
    .room-until { font-size: 0.84rem; color: #f87171; font-weight: 600; margin-top: 8px; }
    .room-from  { font-size: 0.84rem; color: #fbbf24; font-weight: 600; margin-top: 8px; }
    .room-override-tag { font-size: 0.80rem; color: #c084fc; font-weight: 600; margin-top: 8px; }
    .room-capacity {
        display: inline-flex; align-items: center; gap: 4px;
        font-size: 0.73rem; font-weight: 600;
        padding: 2px 9px; border-radius: 6px;
        margin-top: 10px; border-width: 1px; border-style: solid;
    }

    /* ── Admin panel ─────────────────────────────────────────────── */
    .admin-panel { border-radius: 20px; padding: 20px 24px; margin-bottom: 28px; border-width: 1px; border-style: solid; }
    .admin-label { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 4px; }
    .admin-room-name { font-size: 0.95rem; font-weight: 600; margin-bottom: 6px; }

    /* ── Schedule section ────────────────────────────────────────── */
    .sched-room-header {
        display: flex; align-items: baseline; gap: 10px;
        padding: 14px 0 8px; flex-wrap: wrap;
    }
    .sched-room-name { font-size: 0.97rem; font-weight: 700; }
    .sched-room-meta { font-size: 0.78rem; }
    .sched-empty { font-size: 0.85rem; padding: 8px 0 4px; }
    .sched-divider { border: none; border-top-width: 1px; border-top-style: solid; margin: 12px 0 4px; }
    .sched-row { border-radius: 14px; padding: 12px 16px; margin-bottom: 8px; border-width: 1px; border-style: solid; }
    .sched-row.now { background: rgba(239,68,68,0.07) !important; border-color: rgba(239,68,68,0.24) !important; }
    .sched-time { font-size: 0.90rem; font-weight: 600; margin-bottom: 3px; }
    .sched-who  { font-size: 0.85rem; }
    .sched-desc { font-size: 0.81rem; margin-top: 2px; }
    .now-badge {
        display: inline-block; background: rgba(239,68,68,0.25); color: #f87171;
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.10em;
        padding: 2px 7px; border-radius: 999px; border: 1px solid rgba(239,68,68,0.4);
        margin-left: 8px; vertical-align: middle;
    }

    /* ── History rows ────────────────────────────────────────────── */
    .hist-row { border-radius: 14px; padding: 14px 18px; margin-bottom: 10px; border-width: 1px; border-style: solid; }
    .hist-date { font-size: 0.80rem; font-weight: 600; margin-bottom: 4px; }
    .hist-room { font-size: 0.88rem; font-weight: 600; }
    .hist-time { font-size: 0.83rem; margin-top: 2px; }
    .hist-who  { font-size: 0.83rem; margin-top: 2px; }

    /* ── Tabs ────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] { border-radius: 16px; padding: 4px; gap: 2px; border-width: 1px; border-style: solid; }
    .stTabs [data-baseweb="tab"] { border-radius: 12px; font-weight: 600; padding: 8px 20px; }

    /* ── Buttons ─────────────────────────────────────────────────── */
    .stButton button { border-radius: 14px !important; font-weight: 600 !important; }
    .stButton button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        background: #00AFEF !important; background-color: #00AFEF !important;
        border: none !important; box-shadow: 0 6px 20px rgba(0,175,239,0.35) !important;
        color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: #0099d4 !important; background-color: #0099d4 !important;
        box-shadow: 0 8px 24px rgba(0,175,239,0.45) !important;
    }

    /* ── Mobile: bottom tab navigation (merged into main mobile block below) ── */

    /* ── Inputs ──────────────────────────────────────────────────── */
    .stTextInput input { border-radius: 12px !important; }
    .stSelectbox > div > div { border-radius: 12px !important; }

    /* ── Misc ────────────────────────────────────────────────────── */
    div[data-testid="stAlert"] { border-radius: 14px !important; }

    label, [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
    .stTextInput label, .stSelectbox label, .stDateInput label,
    .stRadio label, .stNumberInput label { opacity: 1 !important; font-weight: 500 !important; }

    div[data-testid="stPopover"] > div > button {
        border-radius: 20px !important; padding: 5px 14px !important;
        font-size: 0.72rem !important; font-weight: 700 !important;
        letter-spacing: 0.09em !important; text-transform: uppercase !important;
        white-space: nowrap !important; min-height: unset !important;
        height: auto !important; line-height: 1.5 !important; width: auto !important;
    }
    [data-testid="stPopoverBody"] { border-radius: 16px !important; padding: 12px 16px !important; }
    [data-testid="stPopoverBody"] .stRadio > div { background: transparent !important; gap: 4px !important; }
    [data-testid="stPopoverBody"] .stRadio label { font-size: 0.9rem !important; font-weight: 500 !important; padding: 6px 4px !important; }

    /* ── Show/hide by screen size (default = desktop) ─────── */
    .mobile-only  { display: none  !important; }
    .desktop-only { display: block !important; }

    /* ── Mobile greeting header ──────────────────────────── */
    .mob-greeting {
        display: flex; align-items: center; justify-content: space-between;
        padding: 14px 4px 20px;
    }
    .mob-greeting-left { display: flex; flex-direction: column; gap: 4px; }
    .mob-greeting-hi   { font-size: 0.88rem; font-weight: 400; }
    .mob-greeting-name-row { display: flex; align-items: center; gap: 8px; }
    .mob-greeting-name { font-size: 1.30rem; font-weight: 700; }
    .mob-greeting-admin {
        font-size: 0.62rem; font-weight: 700; letter-spacing: 0.10em;
        text-transform: uppercase; padding: 2px 8px; border-radius: 999px;
        background: rgba(0,175,239,0.15); color: #00AFEF;
        border: 1px solid rgba(0,175,239,0.35);
    }

    /* ── Profile tab ────────────────────────────────────────── */
    .profile-wrap { width: 100%; }
    .profile-avatar-wrap { display: flex; flex-direction: column; align-items: center; padding: 20px 0 16px; }
    .profile-avatar {
        width: 72px; height: 72px; border-radius: 36px;
        background: #00AFEF; display: flex; align-items: center; justify-content: center;
        font-size: 26px; font-weight: 800; color: #fff; margin-bottom: 10px; flex-shrink: 0;
    }
    .profile-av-name { font-size: 1.2rem; font-weight: 700; margin-bottom: 4px; }
    .profile-av-id   { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase; padding: 3px 10px; border-radius: 999px; border: 1px solid; }
    .profile-av-id-row { display: flex; align-items: center; gap: 8px; }
    .profile-info-card { border-radius: 18px; padding: 4px 16px; border: 1px solid; margin-bottom: 16px; }
    .profile-info-row  {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.07);
    }
    .profile-info-row:last-child { border-bottom: none; }
    .profile-info-label { font-size: 0.82rem; }
    .profile-info-value { font-size: 0.88rem; font-weight: 600; }

    /* ── Desktop profile — horizontal card layout ────────────── */
    @media (min-width: 769px) {
        .profile-wrap {
            max-width: 620px;
            margin: 28px auto 0;
        }
        .profile-hero-card {
            display: flex; align-items: center; gap: 28px;
            border-radius: 22px; border: 1px solid; padding: 28px 32px;
            margin-bottom: 16px;
        }
        .profile-avatar-wrap {
            flex-direction: column; align-items: center;
            padding: 0; flex-shrink: 0;
        }
        .profile-avatar { width: 88px; height: 88px; border-radius: 44px; font-size: 32px; margin-bottom: 12px; }
        .profile-av-name { font-size: 1.35rem; }
        .profile-hero-right { flex: 1; }
        .profile-info-card { margin-bottom: 16px; }
        .profile-btn-row { display: flex; gap: 12px; }
        .profile-btn-row > div { flex: 1; }
    }

    /* ── Sign-out button in Profile tab (red variant) ──────── */
    #profile_signout_tab [data-testid="stBaseButton-primary"] {
        background: rgba(239,68,68,0.12) !important;
        background-color: rgba(239,68,68,0.12) !important;
        color: #f87171 !important; -webkit-text-fill-color: #f87171 !important;
        border: 1px solid rgba(239,68,68,0.30) !important;
        box-shadow: none !important;
    }
    #profile_signout_tab [data-testid="stBaseButton-primary"]:hover {
        background: rgba(239,68,68,0.20) !important;
        border-color: rgba(239,68,68,0.50) !important;
    }

    /* ── Room status grid — 4-col desktop / 2-col mobile ────────────── */
    .mob-room-grid-2col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin-top: 12px;
    }
    .mob-room-grid-2col .room-card {
        min-height: 130px;
        padding: 14px 12px !important;
        border-radius: 18px !important;
    }
    @media (min-width: 769px) {
        .mob-room-grid-2col {
            grid-template-columns: repeat(4, 1fr);
            gap: 18px;
            margin-top: 16px;
        }
        .mob-room-grid-2col .room-card {
            min-height: 170px;
            padding: 20px 18px !important;
            border-radius: 20px !important;
        }
    }

    /* ── Mobile status-tab meta row ──────────────────────────────────── */
    .mob-status-meta {
        display: flex; align-items: center; justify-content: space-between;
        margin-top: 18px; margin-bottom: 2px;
    }
    .mob-status-time { font-size: 0.70rem; }


    /* ── Profile warning banner ──────────────────────────────────────── */
    .profile-warn-banner {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 12px 14px; border-radius: 12px;
        font-size: 0.83rem; margin: 0 0 14px;
    }
    .profile-av-id-row { display: flex; align-items: center; gap: 8px; margin-top: 4px; }

    /* ── Above-tabs section-label hidden on mobile ───────────────────── */
    /* (applied via extra class crm-above-tabs-label) */

    /* ════════════════════════════════════════════════════════════
       DESKTOP  ≥ 769px  — real website feel
       ════════════════════════════════════════════════════════════ */
    @media (min-width: 769px) {
        .hero { padding: 36px 40px !important; }
        .hero-title { font-size: 2.8rem !important; }
        .room-card {
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }
        .room-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 14px 36px rgba(0,0,0,0.30) !important;
        }
        .hist-row, .sched-row {
            transition: transform 0.14s ease, box-shadow 0.14s ease;
        }
        .hist-row:hover, .sched-row:hover {
            transform: translateX(3px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.20) !important;
        }
        /* Hide Profile tab (5th) on desktop — use My Profile button in top nav instead */
        .stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(5) {
            display: none !important;
        }
    }

    /* ════════════════════════════════════════════════════════════
       MOBILE  ≤ 768px  — app-like, matches React Native
       ════════════════════════════════════════════════════════════ */
    @media (max-width: 768px) {
        /* ── Hide desktop-only top nav (CSS-based — no JS timing issues) ── */
        #crm-topnav { display: none !important; }

        .main .block-container {
            padding-left: 12px !important; padding-right: 12px !important;
            padding-top: 8px !important; padding-bottom: 80px !important;
        }
        /* Hide the above-tabs section-label (room cards are in Status tab) */
        .crm-above-tabs-label { display: none !important; }
        /* Hero hidden on mobile (desktop-only) */
        .hero { display: none !important; }
        .stButton button { min-height: 48px !important; }
        .stTextInput input, .stSelectbox > div > div,
        .stDateInput input { min-height: 48px !important; font-size: 16px !important; }

        /* ── Bottom tab bar — matches RN app exactly ─────────── */
        .stTabs [data-baseweb="tab-list"] {
            position: fixed !important;
            bottom: 0 !important; left: 0 !important; right: 0 !important;
            z-index: 9999 !important; border-radius: 0 !important;
            padding: 0 4px !important; height: 60px !important;
            display: flex !important; align-items: stretch !important;
        }
        .stTabs [data-baseweb="tab"] {
            flex: 1 !important;
            padding: 6px 2px 4px !important;
            border-radius: 0 !important;
            min-width: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        /* Show native tab text, style it for bottom nav */
        .stTabs [data-baseweb="tab"] p,
        .stTabs [data-baseweb="tab"] div {
            font-size: 12px !important;
            font-weight: 600 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            overflow: visible !important;
            color: inherit !important;
        }
        /* Tab panel padding adjustment */
        .stTabs [data-baseweb="tab-panel"] {
            padding-top: 0 !important;
        }

        /* ── Mobile-only / desktop-only visibility ───────────── */
        .mobile-only  { display: block !important; }
        .desktop-only { display: none  !important; }
        /* ── Hide footer on mobile ─────────────────────────────── */
        .crm-footer { display: none !important; }
        /* ── Room cards section label ───────────────────────── */
        .section-label { font-size: 0.68rem !important; margin-bottom: 8px !important; }
    }

    /* ════════════════════════════════════════════════════════════
       FOOTER
       ════════════════════════════════════════════════════════════ */
    .crm-footer {
        margin-top: 52px; padding: 40px 20px 16px;
        border-top-width: 1px; border-top-style: solid; text-align: center;
    }
    .crm-footer-title {
        font-size: 0.62rem; font-weight: 700; letter-spacing: 0.22em;
        text-transform: uppercase; margin-bottom: 22px; opacity: 0.40;
    }
    .crm-footer-groups {
        display: flex; flex-wrap: wrap; justify-content: center;
        gap: 24px 32px; margin-bottom: 28px; align-items: flex-start;
    }
    .crm-footer-group { display: flex; flex-direction: column; align-items: center; gap: 9px; }
    .crm-footer-group-label {
        font-size: 0.58rem; font-weight: 700; letter-spacing: 0.20em;
        text-transform: uppercase; opacity: 0.32; margin-bottom: 1px;
    }
    .crm-footer-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 7px; }
    .footer-badge {
        display: inline-flex; align-items: center; gap: 6px;
        font-size: 0.76rem; font-weight: 600; letter-spacing: 0.01em;
        padding: 6px 13px 6px 10px; border-radius: 10px;
        border-width: 1px; border-style: solid;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        cursor: default;
    }
    .footer-badge:hover { transform: translateY(-2px); }
    .fbadge-icon { font-size: 0.85rem; line-height: 1; flex-shrink: 0; }
    .footer-badge-py   { background: rgba(55,118,171,0.14); color: #4d9de0; border-color: rgba(55,118,171,0.30); }
    .footer-badge-st   { background: rgba(255,75,75,0.12);  color: #ff6b6b; border-color: rgba(255,75,75,0.28); }
    .footer-badge-api  { background: rgba(0,175,239,0.13);  color: #00AFEF; border-color: rgba(0,175,239,0.30); }
    .footer-badge-db   { background: rgba(77,171,145,0.13); color: #4dab91; border-color: rgba(77,171,145,0.28); }
    .footer-badge-rn   { background: rgba(97,218,251,0.12); color: #61dafb; border-color: rgba(97,218,251,0.28); }
    .footer-badge-expo { background: rgba(165,180,252,0.12); color: #a5b4fc; border-color: rgba(165,180,252,0.28); }
    .footer-badge-pwa  { background: rgba(168,85,247,0.12); color: #c084fc; border-color: rgba(168,85,247,0.28); }
    .crm-footer-divider {
        width: 40px; height: 2px; border-radius: 999px;
        margin: 0 auto 18px; opacity: 0.20;
    }
    .crm-footer-copy   { font-size: 0.76rem; }
    @media (max-width: 768px) {
        .crm-footer { margin-bottom: 70px; }
        .crm-footer-groups { gap: 20px 24px; }
    }
    /* Collapse the invisible JS-only iframe injected for tab persistence */
    [data-testid="stIFrame"] {
        height: 0 !important; min-height: 0 !important;
        margin: 0 !important; padding: 0 !important;
        overflow: hidden !important; display: block !important;
    }
    /* Remove Streamlit's default bottom padding so footer sits flush */
    .main .block-container {
        padding-bottom: 0 !important;
    }
"""

_DARK_CSS = """
    /* ══════════════════════════════════════════════════════════
       DARK GLASSMORPHISM THEME
       ══════════════════════════════════════════════════════════ */

    /* ── Animated mesh background ────────────────────────────── */
    .stApp {
        background:
            radial-gradient(ellipse 80% 55% at 8%  12%,  rgba(0,175,239,0.13) 0%, transparent 55%),
            radial-gradient(ellipse 65% 50% at 92% 88%,  rgba(0,48,120,0.35)  0%, transparent 55%),
            radial-gradient(ellipse 55% 40% at 58%  3%,  rgba(100,40,200,0.09) 0%, transparent 45%),
            radial-gradient(ellipse 40% 35% at 80% 40%,  rgba(0,175,239,0.06) 0%, transparent 40%),
            #040e1f !important;
        color: #f7f4ed !important;
    }

    /* ── Hero — glass panel ──────────────────────────────────── */
    .hero {
        background: rgba(4,14,40,0.55);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid rgba(255,255,255,0.09);
        box-shadow: 0 8px 40px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.07);
    }
    .hero-sub { color: #8fa8c8; }
    .section-label { color: #00AFEF; }
    .crm-section-ts { color: #3d5570; }

    /* ── Room cards — frosted glass ──────────────────────────── */
    .room-card {
        background: rgba(4,14,38,0.52) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255,255,255,0.08) !important;
        box-shadow: 0 6px 28px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.06) !important;
    }
    .room-available {
        background: rgba(8,40,28,0.55) !important;
        border-color: rgba(52,211,153,0.25) !important;
        box-shadow: 0 6px 28px rgba(0,0,0,0.25), 0 0 0 1px rgba(52,211,153,0.07), inset 0 1px 0 rgba(52,211,153,0.09) !important;
    }
    .room-occupied {
        background: rgba(40,8,8,0.55) !important;
        border-color: rgba(248,113,113,0.25) !important;
        box-shadow: 0 6px 28px rgba(0,0,0,0.25), 0 0 0 1px rgba(248,113,113,0.07), inset 0 1px 0 rgba(248,113,113,0.09) !important;
    }
    .room-booked {
        background: rgba(40,30,0,0.55) !important;
        border-color: rgba(251,191,36,0.25) !important;
        box-shadow: 0 6px 28px rgba(0,0,0,0.25), 0 0 0 1px rgba(251,191,36,0.07), inset 0 1px 0 rgba(251,191,36,0.09) !important;
    }
    .room-overridden {
        background: rgba(28,8,40,0.55) !important;
        border-color: rgba(192,132,252,0.25) !important;
        box-shadow: 0 6px 28px rgba(0,0,0,0.25), 0 0 0 1px rgba(192,132,252,0.07), inset 0 1px 0 rgba(192,132,252,0.09) !important;
    }
    .room-floor { color: #f0f6fc; font-weight: 700; }
    .room-meta  { color: #7a9ab8; }
    .room-by    { color: #c0d4e8; }

    /* ── Room capacity badge ─────────────────────────────────── */
    .room-capacity {
        background: rgba(255,255,255,0.06);
        color: #6a8aaa;
        border-color: rgba(255,255,255,0.10);
        backdrop-filter: blur(8px);
    }

    /* ── Admin container — glass ─────────────────────────────── */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(4,14,38,0.50) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 18px !important;
        box-shadow: 0 4px 24px rgba(0,0,0,0.22) !important;
    }
    .admin-label { color: #00AFEF; letter-spacing: 0.12em; }
    .admin-room-name { color: #f0f6fc; }

    /* ── Schedule section ────────────────────────────────────── */
    .sched-room-name { color: #f0f6fc; }
    .sched-room-meta { color: #3d5570; }
    .sched-empty { color: #3d5570; }
    .sched-divider { border-top-color: rgba(255,255,255,0.05); }
    .sched-row {
        background: rgba(4,14,38,0.52);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.07);
        box-shadow: 0 2px 12px rgba(0,0,0,0.18);
    }
    .sched-time { color: #29c0f0; font-weight: 700; }
    .sched-who  { color: #e8f0f8; }
    .sched-desc { color: #7a9ab8; }

    /* ── History rows — glass ────────────────────────────────── */
    .hist-row {
        background: rgba(4,14,38,0.52);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.07);
        box-shadow: 0 2px 12px rgba(0,0,0,0.18);
    }
    .hist-date  { color: #29c0f0; font-weight: 700; }
    .hist-room  { color: #f0f6fc; }
    .hist-time  { color: #7a9ab8; }
    .hist-who   { color: #c0d4e8; }

    /* ── Desktop tab bar — glass ─────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(4,14,38,0.60);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-color: rgba(255,255,255,0.09);
        box-shadow: 0 4px 20px rgba(0,0,0,0.20);
    }
    .stTabs [data-baseweb="tab"] { color: #3d5570; }
    .stTabs [aria-selected="true"] {
        background: rgba(0,175,239,0.14) !important;
        color: #00AFEF !important;
        box-shadow: inset 0 0 0 1px rgba(0,175,239,0.25) !important;
    }

    /* ── Mobile bottom tab bar — dark mode ──────────────────── */
    @media (max-width: 768px) {
        .stTabs [data-baseweb="tab-list"] {
            background: rgba(6,16,36,0.96) !important;
            backdrop-filter: blur(28px) !important;
            -webkit-backdrop-filter: blur(28px) !important;
            border-top: 1.5px solid rgba(255,255,255,0.10) !important;
            box-shadow: 0 -6px 30px rgba(0,0,0,0.60) !important;
        }
        .stTabs [data-baseweb="tab"] { color: #4a6380 !important; }
        .stTabs [aria-selected="true"] { background: rgba(0,175,239,0.12) !important; color: #00AFEF !important; }
        .stTabs [aria-selected="true"] p,
        .stTabs [aria-selected="true"] div { color: #00AFEF !important; font-weight: 700 !important; }
        .mob-status-time { color: #6a8aaa; }
    }

    /* ── Profile warning banner ──────────────────────────────── */
    .profile-warn-banner {
        background: rgba(251,191,36,0.08);
        border: 1px solid rgba(251,191,36,0.28);
        color: #fbbf24;
        backdrop-filter: blur(10px);
    }

    /* ── Global text ─────────────────────────────────────────── */
    .stApp, .stApp div, .stApp span, .stApp p { color: #f7f4ed; }
    label, [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] span { color: #7a9ab8 !important; }
    p, .stMarkdown p, .stMarkdown span { color: #7a9ab8 !important; }

    /* ── Buttons — glass + glow ──────────────────────────────── */
    .stButton button {
        background: rgba(255,255,255,0.05) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(255,255,255,0.11) !important;
        color: #e8f0f8 !important;
        transition: all 0.18s ease !important;
    }
    .stButton button:hover {
        background: rgba(255,255,255,0.09) !important;
        border-color: rgba(255,255,255,0.20) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25) !important;
    }
    .stButton button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg,#00AFEF,#0090cc) !important;
        background-color: #00AFEF !important;
        border: none !important;
        box-shadow: 0 4px 18px rgba(0,175,239,0.40), 0 1px 0 rgba(255,255,255,0.15) inset !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg,#14bef5,#00AFEF) !important;
        box-shadow: 0 6px 24px rgba(0,175,239,0.55), 0 1px 0 rgba(255,255,255,0.15) inset !important;
        transform: translateY(-1px) !important;
    }

    /* ── Mobile greeting ─────────────────────────────────────── */
    .mob-greeting-hi   { color: #7a9ab8; }
    .mob-greeting-name { color: #f0f6fc; }

    /* ── Profile tab ─────────────────────────────────────────── */
    .profile-av-name { color: #f0f6fc; }
    .profile-av-id   { color: #00AFEF; border-color: rgba(0,175,239,0.35); background: rgba(0,175,239,0.10); }
    .profile-hero-card {
        background: rgba(4,14,38,0.52);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.08);
        box-shadow: 0 4px 20px rgba(0,0,0,0.20);
    }
    .profile-info-card {
        background: rgba(4,14,38,0.52);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.08);
        box-shadow: 0 4px 20px rgba(0,0,0,0.20);
    }
    .profile-info-label { color: #7a9ab8; }
    .profile-info-value { color: #f0f6fc; }

    /* ── Top-nav secondary buttons ───────────────────────────── */
    .topnav-user-name { color: #f0f6fc; }
    #topnav_profile [data-testid="stBaseButton-secondary"],
    #topnav_back    [data-testid="stBaseButton-secondary"] {
        background: rgba(0,175,239,0.10) !important;
        backdrop-filter: blur(10px) !important;
        color: #29c0f0 !important;
        -webkit-text-fill-color: #29c0f0 !important;
        border: 1px solid rgba(0,175,239,0.28) !important;
    }
    #topnav_profile [data-testid="stBaseButton-secondary"]:hover,
    #topnav_back    [data-testid="stBaseButton-secondary"]:hover {
        background: rgba(0,175,239,0.18) !important;
        border-color: rgba(0,175,239,0.50) !important;
    }

    /* ── Inputs — glass ──────────────────────────────────────── */
    .stTextInput input, .stTextInput textarea,
    [data-testid="stTextInput"] input, [data-testid="stTextInput"] textarea,
    [data-testid="stTextInputRootElement"] input,
    .stApp input[type="text"], .stApp input[type="search"],
    .stApp input[type="password"], .stApp textarea {
        background: rgba(255,255,255,0.05) !important;
        background-color: rgba(255,255,255,0.05) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(255,255,255,0.11) !important;
        color: #f0f6fc !important;
        -webkit-text-fill-color: #f0f6fc !important;
        transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
    }
    .stTextInput input:focus, .stTextInput textarea:focus,
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextInputRootElement"] input:focus,
    .stApp input:focus, .stApp textarea:focus {
        border-color: rgba(0,175,239,0.50) !important;
        box-shadow: 0 0 0 3px rgba(0,175,239,0.12) !important;
    }
    .stApp input::placeholder, .stApp textarea::placeholder {
        color: rgba(240,246,252,0.35) !important;
        -webkit-text-fill-color: rgba(240,246,252,0.35) !important;
    }
    .stSelectbox > div > div, .stSelectbox [data-baseweb="select"] {
        background: rgba(255,255,255,0.05) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(255,255,255,0.11) !important;
        color: #f0f6fc !important;
    }
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox [data-baseweb="select"] div { color: #f0f6fc !important; }
    .stDateInput > div > div, .stDateInput input {
        background: rgba(255,255,255,0.05) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(255,255,255,0.11) !important;
        color: #f0f6fc !important;
    }

    /* ── Popovers — glass ────────────────────────────────────── */
    div[data-testid="stPopover"] > div > button {
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        color: #f0f6fc !important;
    }
    div[data-testid="stPopover"] button:hover { background: rgba(255,255,255,0.12) !important; }
    [data-testid="stPopoverBody"],
    [data-baseweb="popover"] [data-baseweb="block"] {
        background: rgba(4,14,38,0.82) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        box-shadow: 0 12px 48px rgba(0,0,0,0.65), 0 1px 0 rgba(255,255,255,0.07) inset !important;
    }
    [data-testid="stPopoverBody"] * { color: #f0f6fc !important; background: transparent; }
    [data-testid="stPopoverBody"] label { color: #7a9ab8 !important; }
    [data-testid="stPopoverBody"] p { color: #f0f6fc !important; font-weight: 600 !important; }

    /* ── Base overrides (config.toml is light; flip everything dark) ── */
    .stApp { background: #040e1f !important; color: #f7f4ed !important; }
    .stApp * { color: #f7f4ed; }
    html, body { background: #040e1f !important; }

    /* ── Select / time dropdown popup ───────────────────────── */
    [data-baseweb="menu"], [data-baseweb="list"],
    ul[role="listbox"], [data-baseweb="popover"] [data-baseweb="list"] {
        background: rgba(4,14,38,0.97) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 14px !important;
        box-shadow: 0 12px 40px rgba(0,0,0,0.55) !important;
        overflow: hidden !important;
    }
    [data-baseweb="menu"] li, [data-baseweb="list"] li,
    [role="option"] {
        background: transparent !important;
        color: #e8f0f8 !important;
    }
    [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [data-baseweb="menu"] li[aria-selected="true"],
    [role="option"][aria-selected="true"] {
        background: rgba(0,175,239,0.18) !important;
        color: #00AFEF !important;
    }
    [role="option"] * { color: inherit !important; background: transparent !important; }

    /* ── Alerts / info boxes ─────────────────────────────────── */
    [data-testid="stAlert"] {
        background: rgba(4,14,38,0.60) !important;
        border-color: rgba(255,255,255,0.10) !important;
        color: #e8f0f8 !important;
    }
    [data-testid="stAlert"] * { color: #e8f0f8 !important; }

    /* ── Expander ────────────────────────────────────────────── */
    [data-testid="stExpander"] {
        background: rgba(4,14,38,0.52) !important;
        border-color: rgba(255,255,255,0.08) !important;
    }
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] button { color: #e8f0f8 !important; background: transparent !important; }

    /* ── Sidebar (if used) ───────────────────────────────────── */
    [data-testid="stSidebar"] { background: rgba(4,14,30,0.92) !important; }

    /* ── Date picker calendar popup ─────────────────────────── */
    [data-baseweb="calendar"] {
        background: rgba(4,14,38,0.90) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 18px !important;
        box-shadow: 0 16px 48px rgba(0,0,0,0.55) !important;
    }
    [data-baseweb="calendar"] * { color: #e8f0f8 !important; background: transparent !important; }
    [data-baseweb="calendar"] [role="columnheader"] * { color: #3d5570 !important; }
    [data-baseweb="calendar"] button { border-radius: 50% !important; transition: background 0.15s !important; }
    [data-baseweb="calendar"] button:hover > div { background: rgba(0,175,239,0.18) !important; border-radius: 50% !important; }
    [data-baseweb="calendar"] [aria-selected="true"] > div {
        background: #00AFEF !important; border-radius: 50% !important;
    }
    [data-baseweb="calendar"] [aria-selected="true"] * { color: #ffffff !important; }
    [data-baseweb="calendar"] [data-baseweb="select"] > div,
    [data-baseweb="calendar"] [data-baseweb="select"] { background: rgba(255,255,255,0.07) !important; border-color: rgba(255,255,255,0.12) !important; }

    /* ── Footer ──────────────────────────────────────────────── */
    .crm-footer { border-top-color: rgba(255,255,255,0.06); }
    .crm-footer-title { color: #7a9ab8; }
    .crm-footer-group-label { color: #7a9ab8; }
    .crm-footer-divider { background: rgba(255,255,255,0.25); }
    .crm-footer-copy { color: #3d5570; }

    /* ── Streamlit header bar — match dark background ────────── */
    [data-testid="stHeader"] {
        background: #040e1f !important;
        border-bottom: 1px solid rgba(255,255,255,0.06) !important;
    }
    [data-testid="stHeader"] * { color: #f7f4ed !important; }
    [data-testid="stDecoration"] { display: none !important; }
"""

_LIGHT_CSS = """
    /* ══════════════════════════════════════════════════════════
       LIGHT GLASSMORPHISM THEME
       ══════════════════════════════════════════════════════════ */

    /* ── Animated mesh background ────────────────────────────── */
    .stApp {
        background:
            radial-gradient(ellipse 80% 55% at 8%  12%,  rgba(0,175,239,0.10) 0%, transparent 55%),
            radial-gradient(ellipse 65% 50% at 92% 88%,  rgba(59,130,246,0.12) 0%, transparent 55%),
            radial-gradient(ellipse 55% 40% at 58%  3%,  rgba(16,185,129,0.07) 0%, transparent 45%),
            radial-gradient(ellipse 40% 35% at 80% 40%,  rgba(0,175,239,0.05) 0%, transparent 40%),
            #eef4fb !important;
        color: #1e293b !important;
    }

    /* ── Hero — frosted glass ────────────────────────────────── */
    .hero {
        background: rgba(255,255,255,0.62);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid rgba(255,255,255,0.90);
        box-shadow: 0 8px 40px rgba(0,80,180,0.08), inset 0 1px 0 rgba(255,255,255,0.95);
    }
    .hero-sub { color: #475569; }
    .section-label { color: #0080bb; }
    .crm-section-ts { color: #94a3b8; }

    /* ── Room cards — frosted glass ──────────────────────────── */
    .room-card {
        background: rgba(255,255,255,0.60) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(255,255,255,0.88) !important;
        box-shadow: 0 6px 28px rgba(0,80,180,0.07), inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    .room-available {
        background: rgba(236,253,245,0.75) !important;
        border-color: rgba(52,211,153,0.35) !important;
        box-shadow: 0 6px 28px rgba(16,185,129,0.08), 0 0 0 1px rgba(52,211,153,0.10), inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    .room-occupied {
        background: rgba(254,242,242,0.75) !important;
        border-color: rgba(248,113,113,0.35) !important;
        box-shadow: 0 6px 28px rgba(239,68,68,0.08), 0 0 0 1px rgba(248,113,113,0.10), inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    .room-booked {
        background: rgba(255,251,235,0.75) !important;
        border-color: rgba(251,191,36,0.35) !important;
        box-shadow: 0 6px 28px rgba(234,179,8,0.08), 0 0 0 1px rgba(251,191,36,0.10), inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    .room-overridden {
        background: rgba(250,245,255,0.75) !important;
        border-color: rgba(192,132,252,0.35) !important;
        box-shadow: 0 6px 28px rgba(168,85,247,0.08), 0 0 0 1px rgba(192,132,252,0.10), inset 0 1px 0 rgba(255,255,255,0.95) !important;
    }
    .room-floor { color: #0f172a; font-weight: 700; }
    .room-meta  { color: #475569; }
    .room-by    { color: #64748b; }

    /* ── Room capacity badge ─────────────────────────────────── */
    .room-capacity {
        background: rgba(0,0,0,0.05);
        color: #64748b;
        border-color: rgba(0,0,0,0.09);
    }

    /* ── Admin container — glass ─────────────────────────────── */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(255,255,255,0.58) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(255,255,255,0.88) !important;
        border-radius: 18px !important;
        box-shadow: 0 4px 24px rgba(0,80,180,0.07) !important;
    }
    .admin-label { color: #0080bb; letter-spacing: 0.12em; }
    .admin-room-name { color: #0f172a; }

    /* ── Schedule section ────────────────────────────────────── */
    .sched-room-name { color: #0f172a; }
    .sched-room-meta { color: #94a3b8; }
    .sched-empty { color: #94a3b8; }
    .sched-divider { border-top-color: rgba(0,0,0,0.07); }
    .sched-row {
        background: rgba(255,255,255,0.70);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-color: rgba(255,255,255,0.88);
        box-shadow: 0 2px 12px rgba(0,80,180,0.06);
    }
    .sched-time { color: #0080bb; font-weight: 700; }
    .sched-who  { color: #1e293b; }
    .sched-desc { color: #64748b; }

    /* ── History rows — glass ────────────────────────────────── */
    .hist-row {
        background: rgba(255,255,255,0.70);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-color: rgba(255,255,255,0.88);
        box-shadow: 0 2px 12px rgba(0,80,180,0.06);
    }
    .hist-date  { color: #0080bb; font-weight: 700; }
    .hist-room  { color: #0f172a; }
    .hist-time  { color: #475569; }
    .hist-who   { color: #334155; }

    /* ── Desktop tab bar — glass ─────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(255,255,255,0.55);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-color: rgba(255,255,255,0.88);
        box-shadow: 0 4px 20px rgba(0,80,180,0.07);
    }
    .stTabs [data-baseweb="tab"] { color: #64748b; }
    .stTabs [aria-selected="true"] {
        background: rgba(0,175,239,0.12) !important;
        color: #0080bb !important;
        box-shadow: inset 0 0 0 1px rgba(0,175,239,0.25) !important;
    }

    /* ── Mobile bottom tab bar — solid white, visible in all conditions ── */
    @media (max-width: 768px) {
        .stTabs [data-baseweb="tab-list"] {
            background: #ffffff !important;
            backdrop-filter: none !important;
            -webkit-backdrop-filter: none !important;
            border-top: 1.5px solid rgba(0,0,0,0.10) !important;
            box-shadow: 0 -4px 24px rgba(0,80,180,0.10) !important;
        }
        .stTabs [data-baseweb="tab"] { color: #94a3b8 !important; }
        .stTabs [aria-selected="true"] { background: rgba(0,175,239,0.08) !important; color: #0080bb !important; }
        .stTabs [aria-selected="true"] p,
        .stTabs [aria-selected="true"] div { color: #0080bb !important; font-weight: 700 !important; }
        .mob-status-time { color: #64748b; }
    }

    /* ── Profile warning banner ──────────────────────────────── */
    .profile-warn-banner {
        background: rgba(251,191,36,0.10);
        border: 1px solid rgba(234,179,8,0.28);
        color: #92400e;
    }

    /* ── Global text ─────────────────────────────────────────── */
    .stApp, .stApp div, .stApp span, .stApp p { color: #1e293b; }
    label, [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
    [data-testid="stWidgetLabel"] span { color: #475569 !important; }
    p, .stMarkdown p, .stMarkdown span { color: #334155 !important; }

    /* ── Buttons — glass ─────────────────────────────────────── */
    .stButton button {
        background: rgba(255,255,255,0.65) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(0,0,0,0.11) !important;
        color: #1e293b !important;
        transition: all 0.18s ease !important;
    }
    .stButton button:hover {
        background: rgba(255,255,255,0.88) !important;
        border-color: rgba(0,0,0,0.20) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 16px rgba(0,80,180,0.10) !important;
    }
    .stButton button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg,#00AFEF,#0090cc) !important;
        background-color: #00AFEF !important;
        border: none !important;
        box-shadow: 0 4px 18px rgba(0,175,239,0.35), 0 1px 0 rgba(255,255,255,0.25) inset !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg,#14bef5,#00AFEF) !important;
        box-shadow: 0 6px 24px rgba(0,175,239,0.48), 0 1px 0 rgba(255,255,255,0.25) inset !important;
        transform: translateY(-1px) !important;
    }

    /* ── Mobile greeting ─────────────────────────────────────── */
    .mob-greeting-hi   { color: #475569; }
    .mob-greeting-name { color: #0f172a; }

    /* ── Profile tab ─────────────────────────────────────────── */
    .profile-av-name { color: #0f172a; }
    .profile-av-id   { color: #0080bb; border-color: rgba(0,175,239,0.28); background: rgba(0,175,239,0.08); }
    .profile-hero-card {
        background: rgba(255,255,255,0.70);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.88);
        box-shadow: 0 4px 20px rgba(0,80,180,0.06);
    }
    .profile-info-card {
        background: rgba(255,255,255,0.70);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-color: rgba(255,255,255,0.88);
        box-shadow: 0 4px 20px rgba(0,80,180,0.06);
    }
    .profile-info-label { color: #475569; }
    .profile-info-value { color: #0f172a; }

    /* ── Top-nav secondary buttons ───────────────────────────── */
    .topnav-user-name { color: #1e293b; }
    #topnav_profile [data-testid="stBaseButton-secondary"],
    #topnav_back    [data-testid="stBaseButton-secondary"] {
        background: rgba(0,175,239,0.08) !important;
        backdrop-filter: blur(10px) !important;
        color: #0080bb !important;
        -webkit-text-fill-color: #0080bb !important;
        border: 1px solid rgba(0,175,239,0.25) !important;
    }
    #topnav_profile [data-testid="stBaseButton-secondary"]:hover,
    #topnav_back    [data-testid="stBaseButton-secondary"]:hover {
        background: rgba(0,175,239,0.15) !important;
        border-color: rgba(0,175,239,0.42) !important;
    }

    /* ── Inputs — glass ──────────────────────────────────────── */
    .stTextInput input, .stTextInput textarea,
    [data-testid="stTextInput"] input, [data-testid="stTextInput"] textarea,
    [data-testid="stTextInputRootElement"] input,
    .stApp input[type="text"], .stApp input[type="search"],
    .stApp input[type="password"], .stApp textarea {
        background: rgba(255,255,255,0.75) !important;
        background-color: rgba(255,255,255,0.75) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
    }
    .stTextInput input:focus, .stTextInput textarea:focus,
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextInputRootElement"] input:focus,
    .stApp input:focus, .stApp textarea:focus {
        border-color: rgba(0,175,239,0.45) !important;
        box-shadow: 0 0 0 3px rgba(0,175,239,0.10) !important;
    }
    .stApp input::placeholder, .stApp textarea::placeholder {
        color: rgba(15,23,42,0.40) !important;
        -webkit-text-fill-color: rgba(15,23,42,0.40) !important;
    }
    .stSelectbox > div > div, .stSelectbox [data-baseweb="select"] {
        background: rgba(255,255,255,0.75) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
        color: #0f172a !important;
    }
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox [data-baseweb="select"] div { color: #0f172a !important; }
    .stDateInput > div > div, .stDateInput input {
        background: rgba(255,255,255,0.75) !important;
        backdrop-filter: blur(10px) !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
        color: #0f172a !important;
    }

    /* ── Popovers — glass ────────────────────────────────────── */
    div[data-testid="stPopover"] > div > button {
        background: rgba(255,255,255,0.65) !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
        color: #0f172a !important;
    }
    div[data-testid="stPopover"] button:hover { background: rgba(255,255,255,0.90) !important; }
    [data-testid="stPopoverBody"],
    [data-baseweb="popover"] [data-baseweb="block"] {
        background: rgba(255,255,255,0.90) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(255,255,255,0.90) !important;
        box-shadow: 0 12px 48px rgba(0,80,180,0.14), 0 1px 0 rgba(255,255,255,0.95) inset !important;
    }
    [data-testid="stPopoverBody"] * { color: #1e293b !important; background: transparent; }
    [data-testid="stPopoverBody"] label { color: #475569 !important; }
    [data-testid="stPopoverBody"] p { color: #0f172a !important; font-weight: 600 !important; }

    /* ── Select / time dropdown popup ───────────────────────── */
    [data-baseweb="menu"], [data-baseweb="list"],
    ul[role="listbox"], [data-baseweb="popover"] [data-baseweb="list"] {
        background: rgba(255,255,255,0.95) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(0,0,0,0.08) !important;
        border-radius: 14px !important;
        box-shadow: 0 12px 40px rgba(0,80,180,0.14) !important;
    }
    [data-baseweb="menu"] li, [data-baseweb="list"] li,
    [role="option"] {
        background: transparent !important;
        color: #1e293b !important;
    }
    [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [data-baseweb="menu"] li[aria-selected="true"],
    [role="option"][aria-selected="true"] {
        background: rgba(0,175,239,0.12) !important;
        color: #0080bb !important;
    }

    /* ── Date picker calendar popup ─────────────────────────── */
    [data-baseweb="calendar"] {
        background: rgba(255,255,255,0.95) !important;
        backdrop-filter: blur(28px) !important;
        -webkit-backdrop-filter: blur(28px) !important;
        border: 1px solid rgba(0,0,0,0.08) !important;
        border-radius: 18px !important;
        box-shadow: 0 16px 48px rgba(0,80,180,0.14) !important;
    }
    [data-baseweb="calendar"] * { color: #1e293b !important; background: transparent !important; }
    [data-baseweb="calendar"] [role="columnheader"] * { color: #94a3b8 !important; }
    [data-baseweb="calendar"] button { border-radius: 50% !important; transition: background 0.15s !important; }
    [data-baseweb="calendar"] button:hover > div { background: rgba(0,175,239,0.12) !important; border-radius: 50% !important; }
    [data-baseweb="calendar"] [aria-selected="true"] > div {
        background: #00AFEF !important; border-radius: 50% !important;
    }
    [data-baseweb="calendar"] [aria-selected="true"] * { color: #ffffff !important; }
    [data-baseweb="calendar"] [data-baseweb="select"] > div,
    [data-baseweb="calendar"] [data-baseweb="select"] { background: rgba(0,0,0,0.04) !important; border-color: rgba(0,0,0,0.10) !important; }

    /* ── Footer ──────────────────────────────────────────────── */
    .crm-footer { border-top-color: rgba(0,0,0,0.08); }
    .crm-footer-title { color: #64748b; }
    .crm-footer-group-label { color: #64748b; }
    .crm-footer-divider { background: rgba(0,0,0,0.18); }
    .crm-footer-copy { color: #94a3b8; }

    /* ── Streamlit header bar — match light background ───────── */
    [data-testid="stHeader"] {
        background: #eef4fb !important;
        border-bottom: 1px solid rgba(0,0,0,0.07) !important;
    }
    [data-testid="stHeader"] * { color: #1e293b !important; }
    [data-testid="stDecoration"] { display: none !important; }
"""


def inject_styles(theme: str = "dark") -> None:
    if theme == "dark":
        color_block = _DARK_CSS
    elif theme == "light":
        color_block = _LIGHT_CSS
    else:
        color_block = _DARK_CSS + f"\n@media (prefers-color-scheme: light) {{\n{_LIGHT_CSS}\n}}"

    st.markdown(
        f"<style>\n{_STRUCTURAL_CSS}\n{color_block}\n</style>",
        unsafe_allow_html=True,
    )


# ── Auth constants ─────────────────────────────────────────────────────────────

_LOGO_URL = "https://ritewater.in/wp-content/uploads/2023/10/Group-45541@2x.png"


# ── Auth session helpers ───────────────────────────────────────────────────────

def init_session_state() -> None:
    defaults = {
        "theme":          "Dark",
        "crm_page":       "main",   # "main" | "profile"
        "auth_token":     None,
        "auth_user":      None,
        "auth_mode":      "login",  # "login" | "register" | "complete_oauth" | "email_otp" | "phone_otp"
        "auth_error":     "",
        "pending_oauth":  None,
        "email_otp_sent": False,
        "email_otp_to":   "",
        "phone_otp_sent": False,
        "phone_otp_to":   "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _persist_theme() -> None:
    """Called by on_change on every theme radio — writes selection to query params."""
    try:
        st.query_params["theme"] = st.session_state.get("theme", "Dark")
    except Exception:
        pass


def _restore_session() -> None:
    """Restore auth token and theme from URL params after a page refresh."""
    try:
        qp_theme = st.query_params.get("theme")
        if qp_theme in ("Dark", "Light", "System") and "theme" not in st.session_state:
            st.session_state["theme"] = qp_theme

        sid = st.query_params.get("sid")
        if sid and not st.session_state.get("auth_token"):
            user = get_user_by_session(sid)
            if user:
                st.session_state["auth_token"] = sid
                st.session_state["auth_user"]  = user
    except Exception:
        pass


def _set_auth_success(token: str, user: dict, extra: dict | None = None) -> None:
    """Set session state on successful login/registration and rerun."""
    st.session_state["auth_token"] = token
    st.session_state["auth_user"]  = user
    st.session_state["auth_error"] = ""
    st.session_state["crm_page"]   = "main"
    if extra:
        st.session_state.update(extra)
    try:
        st.query_params["sid"]   = token
        st.query_params["theme"] = st.session_state.get("theme", "Dark")
    except Exception:
        pass
    st.rerun()


def _get_redirect_uri() -> str:
    return os.getenv("STREAMLIT_BASE_URL", "http://localhost:8501").rstrip("/")


def _handle_oauth_callback() -> None:
    """Detect an OAuth redirect in URL params, process it, then clear params."""
    params = st.query_params
    code  = params.get("code", "")
    state = params.get("state", "")
    if not code:
        return

    if st.session_state.get("_oauth_last_code") == code:
        st.query_params.clear()
        return
    st.session_state["_oauth_last_code"] = code

    redirect_uri = _get_redirect_uri()
    result: dict = {}

    _state_parts = state.split("_", 2)
    _embedded_theme = _state_parts[1] if len(_state_parts) >= 2 and _state_parts[1] in ("Dark", "Light", "System") else None
    if _embedded_theme:
        st.session_state["theme"] = _embedded_theme

    if state.startswith("google_"):
        with st.spinner("Completing Google sign-in…"):
            result = _auth_google_callback(code, redirect_uri)
    elif state.startswith("zoho_"):
        with st.spinner("Completing Zoho sign-in…"):
            result = _auth_zoho_callback(code, redirect_uri)
    else:
        return

    st.query_params.clear()
    if _embedded_theme:
        try:
            st.query_params["theme"] = _embedded_theme
        except Exception:
            pass

    if result.get("error"):
        st.session_state["auth_error"] = result["error"]
        st.rerun()

    if result.get("new_user"):
        st.session_state["auth_mode"]    = "complete_oauth"
        st.session_state["pending_oauth"] = {
            "google_id": result.get("google_id", ""),
            "zoho_id":   result.get("zoho_id",   ""),
            "email":     result.get("email",      ""),
            "name":      result.get("name",       ""),
        }
        st.rerun()

    if result.get("success") and result.get("user"):
        _set_auth_success(result["token"], result["user"])


# ── Auth page CSS ──────────────────────────────────────────────────────────────

def _inject_auth_css() -> None:
    theme    = st.session_state.get("theme", "Dark")
    is_light = theme == "Light"

    card_bg      = "rgba(255,255,255,0.72)"  if is_light else "rgba(4,18,44,0.72)"
    card_border  = "rgba(255,255,255,0.90)"  if is_light else "rgba(255,255,255,0.09)"
    text_main    = "#0f172a"                  if is_light else "#f7f4ed"
    text_sub     = "#6b7280"                  if is_light else "#8fa8c8"
    btn_bg       = "rgba(255,255,255,0.65)"   if is_light else "rgba(255,255,255,0.06)"
    btn_border   = "rgba(0,0,0,0.12)"         if is_light else "rgba(255,255,255,0.14)"
    inp_bg       = "rgba(255,255,255,0.80)"   if is_light else "rgba(255,255,255,0.06)"
    inp_border   = "rgba(0,0,0,0.14)"         if is_light else "rgba(255,255,255,0.14)"
    demo_bg      = "#fefce8"                  if is_light else "rgba(253,224,71,0.10)"
    demo_border  = "#fbbf24"
    demo_col     = "#92400e"                  if is_light else "#fcd34d"
    hero_bg      = "rgba(255,255,255,0.55)"   if is_light else "rgba(0,20,55,0.55)"
    hero_text    = "#0f172a"                  if is_light else "#f0f6fc"
    hero_sub     = "#3d6080"                  if is_light else "#8fa8c8"
    hero_feat    = "#1e4f78"                  if is_light else "#a8c8e0"
    divider_col  = "rgba(0,0,0,0.10)"         if is_light else "rgba(255,255,255,0.10)"
    otp_link_col = "#0080bb"                  if is_light else "#29c0f0"
    back_col     = "#6b7280"                  if is_light else "#8fa8c8"
    card_shadow  = "0 16px 48px rgba(0,80,180,0.12), inset 0 1px 0 rgba(255,255,255,0.95)" if is_light else "0 16px 48px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.07)"

    st.markdown(f"""
    <style>
    /* ── Auth page — full-height, vertically centred ────────────── */
    .stApp {{
        background:
            radial-gradient(ellipse 80% 55% at 8%  12%,  rgba(0,175,239,0.13) 0%, transparent 55%),
            radial-gradient(ellipse 65% 50% at 92% 88%,  {"rgba(59,130,246,0.12)" if is_light else "rgba(0,48,120,0.38)"} 0%, transparent 55%),
            radial-gradient(ellipse 55% 40% at 58%  3%,  {"rgba(16,185,129,0.07)" if is_light else "rgba(100,40,200,0.09)"} 0%, transparent 45%),
            {"#eef4fb" if is_light else "#040e1f"} !important;
        min-height: 100vh !important;
    }}
    .main .block-container {{
        min-height: 100vh !important;
        padding-top: 4vh !important;
        padding-bottom: 4vh !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
        max-width: 1100px !important;
    }}

    /* ── Hero panel ─────────────────────────────────────────────── */
    .auth-hero {{
        background: {hero_bg};
        backdrop-filter: blur(28px);
        -webkit-backdrop-filter: blur(28px);
        border: 1px solid {card_border};
        border-radius: 28px;
        padding: 56px 48px;
        min-height: 580px;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        box-shadow: {card_shadow};
    }}
    .auth-hero-title {{
        font-family: 'Plus Jakarta Sans', 'Space Grotesk', sans-serif;
        font-size: 2.8rem;
        font-weight: 800;
        color: {hero_text};
        line-height: 1.1;
        margin: 8px 0 14px;
    }}
    .auth-hero-sub {{
        color: {hero_sub};
        font-size: 0.97rem;
        line-height: 1.65;
        margin: 0 0 36px;
    }}
    .auth-hero-features {{ display:flex; flex-direction:column; gap:18px; }}
    .auth-hero-feature {{
        display: flex; align-items: flex-start; gap: 12px;
        color: {hero_feat}; font-size: 0.92rem; line-height: 1.45;
    }}
    .auth-hero-icon {{ color:#00AFEF; font-size:0.7rem; margin-top:4px; flex-shrink:0; }}
    .auth-brand-kicker {{
        font-size:0.78rem; font-weight:700; letter-spacing:0.14em;
        text-transform:uppercase; color:#00AFEF; margin-bottom:6px;
    }}

    /* ── Form card ──────────────────────────────────────────────── */
    .auth-card {{
        background: {card_bg};
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid {card_border};
        border-radius: 28px;
        padding: 36px 32px 28px;
        box-shadow: {card_shadow};
        margin-bottom: 0;
    }}
    .auth-card-title {{
        font-family: 'Plus Jakarta Sans', 'Space Grotesk', sans-serif;
        font-size: 1.9rem;
        font-weight: 700;
        color: {text_main};
        margin: 14px 0 4px;
        line-height: 1.2;
        text-align: left;
    }}
    .auth-card-sub {{
        color: {text_sub};
        font-size: 0.97rem;
        margin: 0 0 22px;
        padding-left: 18px;
        text-align: left;
    }}

    /* ── Divider "or" ────────────────────────────────────────────── */
    .auth-divider {{
        display: flex; align-items: center; gap: 10px;
        color: {text_sub}; font-size: 0.78rem;
        margin: 16px 0;
    }}
    .auth-divider::before, .auth-divider::after {{
        content: ''; flex: 1; height: 1px;
        background: {divider_col};
    }}

    /* ── OAuth provider buttons ──────────────────────────────────── */
    a.auth-provider-btn {{
        display: flex; align-items: center; justify-content: center;
        gap: 11px; width: 100%; padding: 12px 18px;
        border-radius: 12px;
        font-family: 'Plus Jakarta Sans', 'DM Sans', sans-serif;
        font-size: 0.92rem; font-weight: 600;
        text-decoration: none !important;
        margin-bottom: 10px; cursor: pointer;
        transition: opacity 0.15s, transform 0.12s, box-shadow 0.15s;
        box-sizing: border-box; letter-spacing: 0.01em;
    }}
    a.auth-provider-btn:hover {{ opacity: 0.88; transform: translateY(-1px); }}
    a.auth-provider-btn-google {{
        background: {btn_bg};
        color: {text_main} !important;
        -webkit-text-fill-color: {text_main} !important;
        border: 1.5px solid {btn_border};
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    a.auth-provider-btn-zoho {{
        background: #e8270a;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        border: none;
        box-shadow: 0 2px 10px rgba(232,39,10,0.30);
    }}
    a.auth-provider-btn-zoho:hover {{
        box-shadow: 0 4px 16px rgba(232,39,10,0.45) !important;
    }}
    a.auth-provider-btn-unconfigured {{
        background: {btn_bg};
        color: {text_sub} !important;
        -webkit-text-fill-color: {text_sub} !important;
        border: 1px dashed {btn_border};
        cursor: not-allowed; opacity: 0.55; pointer-events: none;
    }}

    /* ── Input fields (global — Streamlit renders outside .auth-card) ── */
    [data-baseweb="base-input"],
    [data-baseweb="input"],
    [data-baseweb="input"] > div {{
        background-color: {inp_bg} !important;
        background:       {inp_bg} !important;
        border-color:     {inp_border} !important;
    }}
    .stTextInput input, input {{
        background-color: transparent !important;
        color: {text_main} !important;
        -webkit-text-fill-color: {text_main} !important;
    }}
    .stTextInput input::placeholder {{
        color: {text_sub} !important;
        -webkit-text-fill-color: {text_sub} !important;
    }}
    label, [data-testid="stWidgetLabel"] p {{
        color: {text_sub} !important;
    }}

    /* ── OTP / back text links ───────────────────────────────────── */
    .auth-alt-row {{
        display: flex; align-items: center; justify-content: center;
        gap: 8px; flex-wrap: wrap; margin: 12px 0 4px;
        font-size: 0.84rem; color: {text_sub};
    }}
    .auth-alt-row .sep {{ opacity: 0.4; }}
    .auth-alt-link {{
        color: {otp_link_col}; font-weight: 600; cursor: pointer;
        text-decoration: underline; text-underline-offset: 2px;
        background: none; border: none; font-size: inherit;
        font-family: inherit; padding: 0; line-height: inherit;
    }}
    .auth-alt-link:hover {{ opacity: 0.75; }}

    /* ── Back link ───────────────────────────────────────────────── */
    .auth-back-row {{ margin-bottom: 16px; }}
    .auth-back-link {{
        color: {back_col}; font-size: 0.84rem; cursor: pointer;
        background: none; border: none; font-family: inherit;
        padding: 0; display: inline-flex; align-items: center; gap: 5px;
    }}
    .auth-back-link:hover {{ color: {text_main}; }}

    /* ── Expander inside auth card ───────────────────────────────── */
    .auth-card [data-testid="stExpander"] {{
        border: 1px solid {divider_col} !important;
        border-radius: 12px !important;
        margin-top: 14px !important;
        overflow: hidden !important;
    }}
    [data-testid="stExpander"] button,
    [data-testid="stExpander"] button:hover,
    [data-testid="stExpander"] button:active,
    [data-testid="stExpander"] button:focus,
    [data-testid="stExpander"] button:focus-visible,
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary:hover,
    [data-testid="stExpander"] [data-baseweb="accordion"],
    [data-testid="stExpander"] [data-baseweb="accordion"] > div,
    [data-testid="stExpander"] [data-baseweb="accordion"] button,
    [data-testid="stExpander"] [data-baseweb="accordion"] button:hover,
    [data-testid="stExpander"] [data-baseweb="accordion"] button:focus {{
        background:       {card_bg} !important;
        background-color: {card_bg} !important;
        outline: none !important; box-shadow: none !important;
    }}
    [data-testid="stExpander"] button:hover {{
        background: {btn_bg} !important;
        background-color: {btn_bg} !important;
    }}
    [data-testid="stExpander"] button span,
    [data-testid="stExpander"] button p {{
        color: {text_sub} !important;
        font-size: 0.88rem !important; font-weight: 600 !important;
    }}
    [data-testid="stExpanderDetails"],
    [data-testid="stExpander"] [data-testid="stExpanderDetails"] > div {{
        background:       {card_bg} !important;
        background-color: {card_bg} !important;
        padding-top: 12px !important;
    }}

    /* ── Setup-account footer ────────────────────────────────────── */
    .auth-setup-row {{
        text-align: center; font-size: 0.86rem;
        color: {text_sub}; margin-top: 18px; padding-top: 16px;
        border-top: 1px solid {divider_col};
    }}

    /* ── Demo OTP box ────────────────────────────────────────────── */
    .demo-otp-box {{
        background: {demo_bg}; border: 1.5px solid {demo_border};
        border-radius: 14px; padding: 14px 18px; margin: 12px 0;
    }}
    .demo-otp-label {{
        font-size:0.75rem; font-weight:700; letter-spacing:0.1em;
        text-transform:uppercase; color:{demo_col}; margin-bottom:6px;
    }}
    .demo-otp-code {{
        font-size:2rem; font-weight:700; letter-spacing:0.3em;
        color:{demo_col}; font-family:'JetBrains Mono',monospace;
    }}
    .demo-otp-note {{ font-size:0.78rem; color:{demo_col}; opacity:0.8; margin-top:4px; }}

    /* ── Global text + button overrides for auth page ───────────── */
    .stApp, .stApp p, .stApp div, .stApp span {{ color: {text_main}; }}
    .stButton button {{
        background: {btn_bg} !important;
        border: 1px solid {btn_border} !important;
        color: {text_main} !important;
        -webkit-text-fill-color: {text_main} !important;
    }}
    .stButton button[kind="primary"],
    [data-testid="stBaseButton-primary"] {{
        background: linear-gradient(135deg,#00AFEF,#0090cc) !important;
        border: none !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        box-shadow: 0 4px 18px rgba(0,175,239,0.35) !important;
    }}

    /* ── Theme popover button ────────────────────────────────────── */
    div[data-testid="stPopover"] > div > button,
    [data-testid="stPopover"] button {{
        background: {btn_bg} !important;
        background-color: {btn_bg} !important;
        border: 1px solid {btn_border} !important;
        color: {text_main} !important;
        -webkit-text-fill-color: {text_main} !important;
        border-radius: 12px !important;
    }}
    div[data-testid="stPopover"] > div > button:hover {{
        background: {"rgba(0,0,0,0.08)" if is_light else "rgba(255,255,255,0.12)"} !important;
    }}
    [data-testid="stPopoverBody"],
    [data-baseweb="popover"] [data-baseweb="block"] {{
        background: {card_bg} !important;
        backdrop-filter: blur(20px) !important;
        -webkit-backdrop-filter: blur(20px) !important;
        border: 1px solid {card_border} !important;
        box-shadow: 0 8px 32px {"rgba(0,80,180,0.12)" if is_light else "rgba(0,0,0,0.50)"} !important;
    }}
    [data-testid="stPopoverBody"] * {{ color: {text_main} !important; background: transparent; }}
    [data-testid="stPopoverBody"] label {{ color: {text_sub} !important; }}

    /* ── Tighten column gap on auth page ─────────────────────── */
    section[data-testid="column"] {{ padding: 0 10px !important; }}
    </style>
    """, unsafe_allow_html=True)


# ── Auth page sub-components ───────────────────────────────────────────────────

def _render_demo_otp(label: str, otp: str) -> None:
    st.markdown(
        f'<div class="demo-otp-box">'
        f'<div class="demo-otp-label">{label}</div>'
        f'<div class="demo-otp-code">{otp}</div>'
        f'<div class="demo-otp-note">Copy the code above and paste it below</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_back_link(target_mode: str) -> None:
    if st.button("← Back", key=f"back_to_{target_mode}", type="tertiary"):
        st.session_state["auth_mode"]    = target_mode
        st.session_state["email_otp_sent"] = False
        st.session_state["email_otp_to"]   = ""
        st.session_state["phone_otp_sent"] = False
        st.session_state["phone_otp_to"]   = ""
        st.rerun()


def _provider_btn(label: str, url: str, variant: str, icon_html: str) -> None:
    cls = f"auth-provider-btn auth-provider-btn-{variant}"
    if url:
        st.markdown(
            f'<a href="{url}" target="_self" class="{cls}">'
            f'{icon_html}<span>{label}</span></a>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="auth-provider-btn auth-provider-btn-unconfigured">'
            f'{icon_html}<span>{label} (not configured)</span></div>',
            unsafe_allow_html=True,
        )


_GOOGLE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 48 48" style="flex-shrink:0">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
    '</svg>'
)

_ZOHO_ICON = (
    '<svg width="18" height="18" viewBox="0 0 64 64" style="flex-shrink:0">'
    '<rect width="64" height="64" rx="8" fill="#fff" opacity=".15"/>'
    '<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" '
    'font-family="Arial Black,sans-serif" font-size="36" font-weight="900" fill="#fff">Z</text>'
    '</svg>'
)


def _render_main_login() -> None:
    theme      = st.session_state.get("theme", "Dark")
    redirect   = _get_redirect_uri()
    google_url = _auth_google_url(redirect, theme=theme)
    zoho_url   = _auth_zoho_url(redirect,   theme=theme)

    st.markdown(
        '<div class="auth-card-title">Welcome back</div>'
        '<div class="auth-card-sub">Sign in to book and manage rooms.</div>',
        unsafe_allow_html=True,
    )

    _provider_btn("Continue with Google",    google_url, "google", _GOOGLE_ICON)
    _provider_btn("Continue with Zoho Mail", zoho_url,  "zoho",   _ZOHO_ICON)
    st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
    otp_col1, otp_col2 = st.columns(2)
    with otp_col1:
        if st.button("Email OTP", key="go_email_otp", use_container_width=True):
            st.session_state["auth_mode"] = "email_otp"
            st.rerun()
    with otp_col2:
        if st.button("Phone OTP", key="go_phone_otp", use_container_width=True):
            st.session_state["auth_mode"] = "phone_otp"
            st.rerun()

    with st.expander("Sign in with Email & Password"):
        with st.form("auth_pw_form", clear_on_submit=False):
            identifier = st.text_input(
                "Email or Employee ID",
                placeholder="you@ritewater.in  or  RWSIPL007",
            )
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted:
            if not identifier or not password:
                st.error("Please fill in both fields.")
            else:
                res = _auth_login_password(identifier, password)
                if res.get("error"):
                    st.error(res["error"])
                else:
                    _set_auth_success(res["token"], res["user"])

    st.markdown('<div class="auth-setup-row">First time here?</div>', unsafe_allow_html=True)
    if st.button("Set up my account", key="go_register_btn", use_container_width=True):
        st.session_state["auth_mode"] = "register"
        st.rerun()


def _login_form_email_otp() -> None:
    sent    = st.session_state.get("email_otp_sent", False)
    sent_to = st.session_state.get("email_otp_to", "")

    if not sent:
        with st.form("auth_email_otp_req", clear_on_submit=False):
            email = st.text_input("Email address", placeholder="you@ritewater.in")
            send  = st.form_submit_button("Send OTP", type="primary", use_container_width=True)
        if send:
            if not email.strip():
                st.error("Please enter your email address.")
                return
            res = _auth_send_email_otp(email.strip().lower())
            if res.get("error"):
                st.error(res["error"])
            else:
                st.session_state["email_otp_sent"] = True
                st.session_state["email_otp_to"]   = email.strip().lower()
                if res.get("demo"):
                    st.session_state["_demo_email_otp"] = res.get("otp", "")
                st.rerun()
    else:
        st.caption(f"OTP sent to **{sent_to}**")
        demo_otp = st.session_state.pop("_demo_email_otp", None)
        if demo_otp:
            _render_demo_otp("Demo mode — no SMTP configured", demo_otp)
        with st.form("auth_email_otp_verify", clear_on_submit=False):
            code = st.text_input("Enter 6-digit OTP", placeholder="123456", max_chars=6)
            c1, c2 = st.columns(2)
            with c1:
                verify = st.form_submit_button("Verify OTP", type="primary", use_container_width=True)
            with c2:
                resend = st.form_submit_button("Resend", use_container_width=True)
        if verify:
            if not code.strip():
                st.error("Please enter the OTP.")
                return
            res = _auth_login_email_otp(sent_to, code.strip())
            if res.get("error"):
                st.error(res["error"])
            else:
                _set_auth_success(res["token"], res["user"],
                                  {"email_otp_sent": False, "email_otp_to": ""})
        if resend:
            st.session_state["email_otp_sent"] = False
            st.session_state["email_otp_to"]   = ""
            st.rerun()


def _login_form_phone_otp() -> None:
    sent    = st.session_state.get("phone_otp_sent", False)
    sent_to = st.session_state.get("phone_otp_to", "")

    if not sent:
        with st.form("auth_phone_otp_req", clear_on_submit=False):
            phone = st.text_input("Phone number", placeholder="+91 9876543210",
                                  help="Enter with country code, e.g. +91XXXXXXXXXX")
            send = st.form_submit_button("Send OTP", type="primary", use_container_width=True)
        if send:
            if not phone.strip():
                st.error("Please enter your phone number.")
                return
            res = _auth_send_phone_otp(phone.strip())
            if res.get("error"):
                st.error(res["error"])
            else:
                st.session_state["phone_otp_sent"] = True
                st.session_state["phone_otp_to"]   = phone.strip()
                if res.get("demo"):
                    st.session_state["_demo_phone_otp"] = res.get("otp", "")
                st.rerun()
    else:
        st.caption(f"OTP sent to **{sent_to}**")
        demo_otp = st.session_state.pop("_demo_phone_otp", None)
        if demo_otp:
            _render_demo_otp("Demo mode — Twilio not configured", demo_otp)
        with st.form("auth_phone_otp_verify", clear_on_submit=False):
            code = st.text_input("Enter 6-digit OTP", placeholder="123456", max_chars=6)
            c1, c2 = st.columns(2)
            with c1:
                verify = st.form_submit_button("Verify OTP", type="primary", use_container_width=True)
            with c2:
                resend = st.form_submit_button("Resend", use_container_width=True)
        if verify:
            if not code.strip():
                st.error("Please enter the OTP.")
                return
            res = _auth_login_phone_otp(sent_to, code.strip())
            if res.get("error"):
                st.error(res["error"])
            else:
                _set_auth_success(res["token"], res["user"],
                                  {"phone_otp_sent": False, "phone_otp_to": ""})
        if resend:
            st.session_state["phone_otp_sent"] = False
            st.session_state["phone_otp_to"]   = ""
            st.rerun()


def _render_register_form(
    prefill_name: str = "",
    prefill_email: str = "",
    google_id: str = "",
    zoho_id: str = "",
) -> None:
    oauth_mode = bool(google_id or zoho_id)
    heading    = "Complete Registration" if oauth_mode else "Set Up Your Account"
    st.markdown(f"<div style='font-weight:700;font-size:1.05rem;margin-bottom:4px'>{heading}</div>",
                unsafe_allow_html=True)
    if not oauth_mode:
        st.caption("Enter your Employee ID and add your email or phone number.")

    with st.form("auth_register_form", clear_on_submit=False):
        name   = st.text_input("Full Name", value=prefill_name, placeholder="e.g. Priya Sharma")
        emp_id = st.text_input("Employee ID", placeholder="e.g. RWSIPL007")
        if not oauth_mode:
            email    = st.text_input("Email address", value=prefill_email,
                                     placeholder="you@ritewater.in")
            phone    = st.text_input("Phone number (optional)", placeholder="+91 9876543210")
            password = st.text_input(
                "Set a password (optional — can also use OTP to sign in)",
                type="password",
                placeholder="Leave blank to use OTP only",
            )
        else:
            email    = prefill_email
            phone    = ""
            password = ""
            st.info(f"Signing in via {'Google' if google_id else 'Zoho'}  ·  {prefill_email}")

        submitted = st.form_submit_button(
            "Set Up Account", type="primary", use_container_width=True
        )

    if submitted:
        if oauth_mode:
            res = _auth_complete_oauth(
                name=name, employee_id=emp_id, email=email,
                google_id=google_id, zoho_id=zoho_id,
            )
        else:
            res = _auth_register(
                name=name, employee_id=emp_id,
                email=email, phone=phone, password=password,
            )
        if res.get("error"):
            st.error(res["error"])
        else:
            msg = "Account activated! Signing you in…" if res.get("activated") else "Account created! Signing you in…"
            st.success(msg)
            _set_auth_success(res["token"], res["user"],
                              {"auth_mode": "login", "pending_oauth": None})

    if st.button("Back to Sign in", key="reg_back_btn", use_container_width=False):
        st.session_state["auth_mode"] = "login"
        st.rerun()


def render_auth_page() -> None:
    _inject_auth_css()

    error = st.session_state.get("auth_error", "")
    mode  = st.session_state.get("auth_mode", "login")

    # Theme popover — top right
    _, theme_col = st.columns([0.82, 0.18])
    with theme_col:
        with st.popover("Theme", use_container_width=True):
            st.radio("Theme", ["System", "Dark", "Light"],
                     label_visibility="collapsed", key="theme",
                     on_change=_persist_theme)

    hero_col, form_col = st.columns([1.1, 0.9])

    with hero_col:
        st.markdown(
            f'<div class="auth-hero">'
            f'<div style="margin-bottom:28px">'
            f'<img src="{_LOGO_URL}" style="height:90px;width:auto;object-fit:contain" alt="Rite Water Solutions">'
            f'</div>'
            f'<div class="auth-brand-kicker">Employee Portal</div>'
            f'<div class="auth-hero-title">Conference Room<br>Manager</div>'
            f'<p class="auth-hero-sub">Book and manage conference rooms at Rite Water Solutions — real-time availability, instant confirmation.</p>'
            f'<div class="auth-hero-features">'
            f'<div class="auth-hero-feature"><span class="auth-hero-icon">&#9679;</span><span>Live room availability across all floors</span></div>'
            f'<div class="auth-hero-feature"><span class="auth-hero-icon">&#9679;</span><span>Book rooms in seconds, cancel anytime</span></div>'
            f'<div class="auth-hero-feature"><span class="auth-hero-icon">&#9679;</span><span>Admin controls for overrides and scheduling</span></div>'
            f'<div class="auth-hero-feature"><span class="auth-hero-icon">&#9679;</span><span>Full booking history with search</span></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with form_col:
        if error:
            st.error(error)
            st.session_state["auth_error"] = ""

        st.markdown('<div class="auth-card">', unsafe_allow_html=True)

        if mode == "complete_oauth":
            po = st.session_state.get("pending_oauth") or {}
            _render_register_form(
                prefill_name=po.get("name", ""),
                prefill_email=po.get("email", ""),
                google_id=po.get("google_id", ""),
                zoho_id=po.get("zoho_id", ""),
            )
        elif mode == "register":
            _render_back_link("login")
            _render_register_form()
        elif mode == "email_otp":
            _render_back_link("login")
            st.markdown(
                '<div class="auth-card-title">Sign in with Email OTP</div>'
                '<div class="auth-card-sub">We\'ll send a one-time code to your email.</div>',
                unsafe_allow_html=True,
            )
            _login_form_email_otp()
        elif mode == "phone_otp":
            _render_back_link("login")
            st.markdown(
                '<div class="auth-card-title">Sign in with Phone OTP</div>'
                '<div class="auth-card-sub">We\'ll send a one-time code to your phone.</div>',
                unsafe_allow_html=True,
            )
            _login_form_phone_otp()
        else:
            _render_main_login()

        st.markdown('</div>', unsafe_allow_html=True)  # .auth-card


# ── Profile page ───────────────────────────────────────────────────────────────

def render_profile_page() -> None:
    auth_user = st.session_state.get("auth_user") or {}

    st.markdown("## My Profile")
    st.caption("Update your personal details below. Employee ID cannot be changed.")
    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Employee ID**")
        st.code(auth_user.get("employee_id", "—"), language=None)
    with c2:
        st.markdown("**Account created**")
        created = auth_user.get("created_at", "")
        st.caption(created[:10] if created else "—")

    oauth_linked = []
    if auth_user.get("google_id"):
        oauth_linked.append("Google")
    if auth_user.get("zoho_id"):
        oauth_linked.append("Zoho Mail")
    if oauth_linked:
        st.info(f"Linked via OAuth: {', '.join(oauth_linked)}")

    st.divider()

    with st.form("profile_form", clear_on_submit=False):
        st.markdown("#### Personal Details")
        new_name  = st.text_input("Full name",  value=auth_user.get("name", ""))
        new_email = st.text_input("Email",       value=auth_user.get("email", "") or "")
        new_phone = st.text_input("Phone",       value=auth_user.get("phone", "") or "",
                                  placeholder="+91 XXXXXXXXXX")
        submitted = st.form_submit_button("Save Changes", type="primary",
                                          use_container_width=True)

    if submitted:
        fields: dict = {}
        if new_name.strip()  != auth_user.get("name", ""):
            fields["name"]  = new_name.strip()
        if new_email.strip() != (auth_user.get("email") or ""):
            fields["email"] = new_email.strip()
        if new_phone.strip() != (auth_user.get("phone") or ""):
            fields["phone"] = new_phone.strip()
        if not fields:
            st.info("No changes detected.")
        else:
            result = _auth_update_user(auth_user["id"], fields)
            if result.get("error"):
                st.error(result["error"])
            else:
                st.session_state["auth_user"] = result["user"]
                st.success("Profile updated.")
                st.rerun()

    if st.button("Change password", type="secondary", use_container_width=True):
        _change_password_dialog(auth_user["id"])


@st.dialog("Change Password")
def _change_password_dialog(user_id: str) -> None:
    st.caption("Choose a new password for your account.")
    new_pw  = st.text_input("New password",     type="password", key="dlg_new_pw")
    conf_pw = st.text_input("Confirm password", type="password", key="dlg_conf_pw")
    st.markdown("<div style='margin-top:4px'></div>", unsafe_allow_html=True)
    save_col, cancel_col = st.columns(2)
    with save_col:
        if st.button("Save password", type="primary", use_container_width=True, key="dlg_save"):
            if not new_pw:
                st.error("Please enter a new password.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            elif new_pw != conf_pw:
                st.error("Passwords do not match.")
            else:
                result = _auth_update_user(user_id, {"password": new_pw})
                if result.get("error"):
                    st.error(result["error"])
                else:
                    st.session_state["auth_user"] = result["user"]
                    st.success("Password updated.")
                    st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True, key="dlg_cancel"):
            st.rerun()


# ── Admin override panel ───────────────────────────────────────────────────────

def _render_admin_panel(auth_user: dict, key_prefix: str = "") -> None:
    with st.container(border=True):
        st.markdown('<div class="admin-label">Admin Controls — Room Override</div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, (room_id, room) in enumerate(sorted(ROOMS.items(), reverse=True)):
            override = get_active_override(room_id)
            with cols[i % 2]:
                st.markdown(
                    f'<div class="admin-room-name">Floor {room_id} — {room["size"]}</div>',
                    unsafe_allow_html=True,
                )
                if override:
                    st.markdown(
                        f'<div style="color:#c084fc;font-size:0.8rem;margin-bottom:6px;">'
                        f'Override: {override["reason"]}</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("Clear Override", key=f"{key_prefix}admin_clear_{room_id}",
                                 help="Remove override and return to normal status"):
                        clear_room_override(room_id)
                        st.success(f"Override cleared for Floor {room_id}.")
                        st.rerun()
                else:
                    reason_key = f"{key_prefix}admin_reason_{room_id}"
                    if reason_key not in st.session_state:
                        st.session_state[reason_key] = ""
                    reason = st.text_input(
                        "Reason", key=reason_key,
                        placeholder="Maintenance, Cleaning…",
                        label_visibility="collapsed",
                    )
                    if st.button("Mark as Occupied", key=f"{key_prefix}admin_override_{room_id}"):
                        set_room_override(
                            room_id,
                            reason.strip() or "Maintenance",
                            auth_user["name"],
                        )
                        st.success(f"Floor {room_id} marked as occupied.")
                        st.rerun()


# ── Footer ─────────────────────────────────────────────────────────────────────

def _render_footer() -> None:
    st.markdown("""
    <div class="crm-footer">
        <div class="crm-footer-title">Tech Stack</div>
        <div class="crm-footer-groups">
            <div class="crm-footer-group">
                <div class="crm-footer-group-label">Backend</div>
                <div class="crm-footer-row">
                    <span class="footer-badge footer-badge-py">Python 3.12</span>
                    <span class="footer-badge footer-badge-st">Streamlit</span>
                    <span class="footer-badge footer-badge-api">FastAPI</span>
                    <span class="footer-badge footer-badge-db">SQLite</span>
                </div>
            </div>
            <div class="crm-footer-group">
                <div class="crm-footer-group-label">Mobile &amp; PWA</div>
                <div class="crm-footer-row">
                    <span class="footer-badge footer-badge-rn">React Native</span>
                    <span class="footer-badge footer-badge-expo">Expo</span>
                    <span class="footer-badge footer-badge-pwa">PWA</span>
                </div>
            </div>
        </div>
        <div class="crm-footer-divider"></div>
        <div class="crm-footer-copy">© 2026 Rite Water Solutions &nbsp;·&nbsp; Conference Room Manager</div>
    </div>
    """, unsafe_allow_html=True)


# ── Main app ───────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Conference Room Manager",
        page_icon="https://ritewater.in/wp-content/uploads/2023/10/Group-45541@2x.png",
        layout="wide",
    )

    # PWA manifest + mobile meta tags (injected once per session)
    if "pwa_injected" not in st.session_state:
        st.markdown("""
        <link rel="manifest" href="/app/static/manifest.json">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="CRM">
        <meta name="theme-color" content="#00AFEF">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
        <script>
        (function(){
            var VALID = ['Dark','Light','System'];
            var urlTheme = new URLSearchParams(window.location.search).get('theme');
            if(urlTheme && VALID.includes(urlTheme)){
                localStorage.setItem('crm_theme', urlTheme);
            } else {
                var saved = localStorage.getItem('crm_theme');
                if(saved && VALID.includes(saved)){
                    var url = new URL(window.location.href);
                    url.searchParams.set('theme', saved);
                    window.location.replace(url.toString());
                }
            }
        })();
        </script>
        """, unsafe_allow_html=True)
        st.session_state["pwa_injected"] = True

    if "db_initialized" not in st.session_state:
        init_db()
        st.session_state["db_initialized"] = True

    if "auth_db_initialized" not in st.session_state:
        init_auth_db()
        migrate_auth_db()
        sync_admin_flags()
        st.session_state["auth_db_initialized"] = True

    _restore_session()
    init_session_state()
    _handle_oauth_callback()

    # ── Auth gate ─────────────────────────────────────────────────────────────
    token     = st.session_state.get("auth_token")
    auth_user = get_user_by_session(token) if token else None

    if not auth_user:
        if token:
            st.session_state["auth_token"] = None
            st.session_state["auth_user"]  = None
        try:
            st.query_params.pop("sid", None)
        except Exception:
            pass
        render_auth_page()
        st.stop()

    # Real-time admin check: DB column OR ADMIN_EMPLOYEE_IDS env var.
    # The env-var fallback covers the case where the user registered after
    # the last sync_admin_flags() run, or where the DB column hasn't been
    # updated yet.
    _admin_ids = {
        e.strip().upper()
        for e in os.getenv("ADMIN_EMPLOYEE_IDS", "RWSIPL493,TRWSIPL834").split(",")
        if e.strip()
    }
    is_admin = bool(auth_user.get("is_admin")) or \
               auth_user.get("employee_id", "").upper() in _admin_ids

    # Keep the DB column in sync so future reads are accurate
    if is_admin and not auth_user.get("is_admin"):
        auth_user = dict(auth_user)
        auth_user["is_admin"] = True

    st.session_state["auth_user"] = auth_user

    # ── Profile page ──────────────────────────────────────────────────────────
    if st.session_state.get("crm_page") == "profile":
        _THEME_OPTIONS = ["System", "Dark", "Light"]
        hdr_brand_p, _, hdr_theme_p, hdr_back, hdr_so_p = st.columns([2.6, 2.6, 0.9, 1, 1])
        with hdr_brand_p:
            st.markdown(
                f'<div class="crm-navbar-brand">'
                f'<img src="{_LOGO_URL}" class="crm-navbar-logo" alt="Rite Water">'
                f'</div>',
                unsafe_allow_html=True,
            )
        with hdr_theme_p:
            with st.popover("Theme", use_container_width=False):
                st.radio("Theme", _THEME_OPTIONS, label_visibility="collapsed", key="theme", on_change=_persist_theme)
        with hdr_back:
            if st.button("← Rooms", key="topnav_back", type="secondary", use_container_width=True):
                st.session_state["crm_page"] = "main"
                st.rerun()
        with hdr_so_p:
            if st.button("Sign Out", key="topnav_signout", type="primary", use_container_width=True):
                logout_session(st.session_state.get("auth_token"))
                for k in ["auth_token", "auth_user", "auth_mode", "auth_error",
                          "pending_oauth", "email_otp_sent", "email_otp_to",
                          "phone_otp_sent", "phone_otp_to"]:
                    st.session_state.pop(k, None)
                st.cache_data.clear()
                try:
                    st.query_params.pop("sid", None)
                except Exception:
                    pass
                st.rerun()
        theme_key = {"Dark": "dark", "Light": "light", "System": "system"}[st.session_state["theme"]]
        inject_styles(theme_key)
        render_profile_page()
        return

    # ── Header row: brand + user chip + theme + profile + signout ───────────
    _THEME_OPTIONS = ["System", "Dark", "Light"]
    with st.container(key="crm-topnav"):
        hdr_brand, _, hdr_user, hdr_theme, hdr_profile, hdr_right = st.columns([2.0, 1.4, 1.6, 0.8, 1.0, 0.9])

        with hdr_brand:
            st.markdown(
                f'<div class="crm-navbar-brand">'
                f'<img src="{_LOGO_URL}" class="crm-navbar-logo" alt="Rite Water">'
                f'</div>',
                unsafe_allow_html=True,
            )

        with hdr_user:
            _admin_badge = '<span class="topnav-admin-badge">Admin</span>' if is_admin else ""
            st.markdown(
                f'<div class="topnav-user-chip">'
                f'<span class="topnav-user-name">{auth_user["name"]}</span>'
                f'{_admin_badge}'
                f'</div>',
                unsafe_allow_html=True,
            )

        with hdr_theme:
            with st.popover("Theme", use_container_width=False):
                st.radio("Theme", _THEME_OPTIONS, label_visibility="collapsed", key="theme", on_change=_persist_theme)

        with hdr_profile:
            if st.button("My Profile", key="topnav_profile", type="secondary", use_container_width=True):
                st.session_state["crm_page"] = "profile"
                st.rerun()

        with hdr_right:
            if st.button("Sign Out", key="topnav_signout", type="primary", use_container_width=True):
                logout_session(st.session_state.get("auth_token"))
                for k in ["auth_token", "auth_user", "auth_mode", "auth_error",
                          "pending_oauth", "email_otp_sent", "email_otp_to",
                          "phone_otp_sent", "phone_otp_to"]:
                    st.session_state.pop(k, None)
                st.cache_data.clear()
                try:
                    st.query_params.pop("sid", None)
                except Exception:
                    pass
                st.rerun()

    theme_key = {"Dark": "dark", "Light": "light", "System": "system"}[st.session_state["theme"]]
    inject_styles(theme_key)

    # ── JavaScript: mobile layout (bottom nav icons + hide header) ──────────
    st.markdown("""
    <script>
    (function(){
        var TAB_LABELS = ['Status','Book','Schedule','History','Profile'];

        function crm_layout(){
            var isMobile = window.innerWidth <= 768;
            var tabs = document.querySelectorAll(
                '.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]'
            );

            if(isMobile){
                /* ── MOBILE ─────────────────────────────────────── */

                /* 1. Hide the top header row — text-based detection (Streamlit doesn't set DOM ids from widget keys) */
                var _nb = document.querySelectorAll('[data-testid*="stBaseButton"]');
                for(var _bi=0;_bi<_nb.length;_bi++){
                    var _bt=_nb[_bi].textContent.trim();
                    if(_bt==='My Profile'||_bt==='← Rooms'){
                        var _hr=_nb[_bi].closest('[data-testid="stHorizontalBlock"]');
                        if(_hr){_hr.style.setProperty('display','none','important');break;}
                    }
                }
                /* 2. Hide Streamlit wrapper containers of .desktop-only elements (removes ghost spacing) */
                document.querySelectorAll('.desktop-only').forEach(function(e){
                    var w=e.closest('[data-testid="stMarkdownContainer"]');
                    if(w) w.style.setProperty('display','none','important');
                });

                /* 2. Set plain text label on each tab */
                tabs.forEach(function(tab,i){
                    if(i>=TAB_LABELS.length) return;
                    tab.setAttribute('data-crm-label', TAB_LABELS[i]);
                    tab.style.setProperty('background','transparent','important');
                });

                /* 4. Style Sign-Out button red in Profile tab panel */
                var panels = document.querySelectorAll('[data-baseweb="tab-panel"]');
                if(panels[4]){
                    panels[4].querySelectorAll('[data-testid="stBaseButton-primary"]').forEach(function(b){
                        if(b.textContent.trim()==='Sign Out'){
                            b.style.cssText +=
                                'background:rgba(239,68,68,0.12)!important;' +
                                'color:#f87171!important;-webkit-text-fill-color:#f87171!important;' +
                                'border:1px solid rgba(239,68,68,0.30)!important;box-shadow:none!important;';
                        }
                    });
                }

            } else {
                /* ── DESKTOP ────────────────────────────────────── */

                /* Compact nav header columns — getElementById works now (st.container key="crm-topnav" sets DOM id) */
                var _tn=document.getElementById('crm-topnav');
                if(_tn){
                    var nb=_tn.querySelector('[data-testid="stHorizontalBlock"]');
                    if(nb){
                        nb.style.setProperty('flex-wrap','nowrap','important');
                        nb.style.setProperty('align-items','center','important');
                        var cs=nb.querySelectorAll('[data-testid="column"]');
                        if(cs.length>=6){
                            cs[0].style.setProperty('flex','1 1 auto','important');
                            cs[0].style.setProperty('min-width','0','important');
                            cs[1].style.setProperty('display','none','important');
                            cs[2].style.setProperty('flex','0 0 auto','important');
                            cs[3].style.setProperty('flex','0 0 auto','important');
                            cs[4].style.setProperty('flex','0 0 auto','important');
                            cs[4].style.setProperty('min-width','100px','important');
                            cs[4].style.setProperty('max-width','100px','important');
                            cs[5].style.setProperty('flex','0 0 auto','important');
                            cs[5].style.setProperty('min-width','84px','important');
                            cs[5].style.setProperty('max-width','84px','important');
                        }
                    }
                }
            }
        }

        /* ── Dark-mode dropdown override (config.toml base=light; dark needs override) ── */
        function crm_dark_dropdowns(){
            var theme = new URLSearchParams(window.location.search).get('theme') || 'Dark';
            var isDark = theme === 'Dark' ||
                (theme === 'System' && window.matchMedia('(prefers-color-scheme: dark)').matches);

            var existing = document.getElementById('crm-dd-css');
            /* If already last in head and correct theme, nothing to do */
            if(existing && existing === document.head.lastElementChild) return;
            if(existing) existing.remove();
            if(!isDark) return; /* Light mode: native BaseWeb light theme is fine */

            var s = document.createElement('style');
            s.id = 'crm-dd-css';
            s.textContent =
                '[data-baseweb="menu"],[data-baseweb="list"],ul[role="listbox"]{' +
                'background:rgba(4,14,38,0.97)!important;' +
                'border:1px solid rgba(255,255,255,0.10)!important;' +
                'border-radius:14px!important;' +
                'box-shadow:0 12px 40px rgba(0,0,0,0.55)!important;' +
                'overflow:hidden!important;}' +
                '[role="option"]{background:transparent!important;color:#e8f0f8!important;}' +
                '[role="option"]:hover{background:rgba(0,175,239,0.16)!important;color:#00AFEF!important;}' +
                '[role="option"][aria-selected="true"]{background:rgba(0,175,239,0.22)!important;color:#00AFEF!important;}' +
                '[role="option"] *{color:inherit!important;background:transparent!important;}' +
                '[data-baseweb="calendar"]{background:rgba(4,14,38,0.97)!important;border:1px solid rgba(255,255,255,0.10)!important;border-radius:18px!important;}' +
                '[data-baseweb="calendar"] *{color:#e8f0f8!important;background:transparent!important;}' +
                '[data-baseweb="calendar"] [aria-selected="true"]>div{background:#00AFEF!important;border-radius:50%!important;}' +
                '[data-baseweb="calendar"] [aria-selected="true"] *{color:#fff!important;}';
            document.head.appendChild(s);
        }

        /* Fire when emotion inserts new styles into <head>, guarded against own insertion */
        new MutationObserver(function(muts){
            for(var i=0;i<muts.length;i++){
                var nodes=muts[i].addedNodes;
                for(var j=0;j<nodes.length;j++){
                    if(nodes[j].id==='crm-dd-css') return;
                }
            }
            crm_dark_dropdowns();
        }).observe(document.head,{childList:true});

        var _t;
        new MutationObserver(function(){clearTimeout(_t);_t=setTimeout(crm_layout,60);})
            .observe(document.body,{childList:true,subtree:true});
        crm_dark_dropdowns();
        setTimeout(crm_layout,300);
        window.addEventListener('resize',crm_layout);
    })();
    </script>
    """, unsafe_allow_html=True)

    # ── Compute live stats ────────────────────────────────────────────────────
    _stat_counts: dict[str, int] = {}
    for _rid in ROOMS:
        _s, _ = get_current_status(_rid)
        _stat_counts[_s] = _stat_counts.get(_s, 0) + 1
    _n_override = sum(1 for _rid in ROOMS if get_active_override(_rid))

    _chips = []
    if _stat_counts.get("available", 0):
        _chips.append(f'<span class="hero-stat-chip stat-available">&#9679; {_stat_counts["available"]} Available</span>')
    if _stat_counts.get("occupied", 0):
        _chips.append(f'<span class="hero-stat-chip stat-occupied">&#9679; {_stat_counts["occupied"]} Occupied</span>')
    if _stat_counts.get("booked", 0):
        _chips.append(f'<span class="hero-stat-chip stat-booked">&#9679; {_stat_counts["booked"]} Booked Soon</span>')
    if _n_override:
        _chips.append(f'<span class="hero-stat-chip stat-override">&#9679; {_n_override} Override</span>')
    _stats_html = f'<div class="hero-stats-row">{"".join(_chips)}</div>' if _chips else ""

    # ── Desktop hero (hidden on mobile) ──────────────────────────────────────
    st.markdown(f"""
    <div class="hero desktop-only">
        <div class="hero-title">Conference Room Manager</div>
        <p class="hero-sub">Check live availability, book a room, or view today's schedule.</p>
        {_stats_html}
    </div>
    """, unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_status, tab_book, tab_schedule, tab_history, tab_profile = st.tabs(
        ["Status", "Book", "Schedule", "History", "Profile"]
    )

    # Persist active tab across reruns triggered by widget interactions.
    # Streamlit resets st.tabs to tab 0 on every rerun; this JS saves the
    # selected tab in sessionStorage and re-clicks it after each rerun.
    st.iframe("""
    <style>html,body{margin:0;padding:0;height:0;overflow:hidden}</style>
    <script>
    (function () {
        var doc = window.parent.document;
        var STORE_KEY = 'crm_active_tab';

        function getTabs() {
            return doc.querySelectorAll('[data-baseweb="tab"]');
        }

        function restoreTab() {
            var saved = parseInt(sessionStorage.getItem(STORE_KEY) || '0', 10);
            var tabs = getTabs();
            if (tabs.length > saved && tabs[saved].getAttribute('aria-selected') !== 'true') {
                tabs[saved].click();
            }
        }

        doc.addEventListener('click', function (e) {
            var tab = e.target.closest('[data-baseweb="tab"]');
            if (tab) {
                var tabs = getTabs();
                var idx = Array.from(tabs).indexOf(tab);
                if (idx >= 0) sessionStorage.setItem(STORE_KEY, idx);
            }
        }, true);

        setTimeout(restoreTab, 120);
    })();
    </script>
    """, height="content")

    # ── Tab 0: Status — 4-col on desktop, 2-col on mobile ───────────────────
    with tab_status:
        _hour = datetime.now().hour
        _greet = "Good morning" if _hour < 12 else "Good afternoon" if _hour < 17 else "Good evening"
        _mob_admin_badge = '<span class="mob-greeting-admin">Admin</span>' if is_admin else ""
        _now_str = datetime.now().strftime("%I:%M %p").lstrip("0")

        _status_cards = []
        for _rid, _room in sorted(ROOMS.items(), reverse=True):
            _st, _bk = get_current_status(_rid)
            _ov = get_active_override(_rid)
            _am = " · ".join(_room["amenities"])
            if _ov:
                _cc, _pc, _bl = "room-overridden", "pill-override", '<span class="pdot"></span> OVERRIDE'
                _ex = f'<div class="room-override-tag">{_ov["reason"]}</div>'
            elif _st == "occupied":
                _cc, _pc, _bl = "room-occupied", "pill-occupied", '<span class="pdot"></span> OCCUPIED'
                _ex = (
                    f'<div class="room-until">Until {to_12hr(_bk["end_time"])}</div>'
                    f'<div class="room-by">{_bk["booked_by"]}</div>'
                )
            elif _st == "booked":
                _cc, _pc, _bl = "room-booked", "pill-booked", '<span class="pdot"></span> BOOKED'
                _ex = f'<div class="room-from">From {to_12hr(_bk["start_time"])}</div>'
            else:
                _cc, _pc, _bl = "room-available", "pill-available", '<span class="pdot"></span> AVAILABLE'
                _ex = ""
            _status_cards.append(
                f'<div class="room-card {_cc}">'
                f'<div class="room-card-hdr">'
                f'<div class="room-floor">Floor {_rid}</div>'
                f'<span class="room-capacity">{_room["capacity"]} seats</span>'
                f'</div>'
                f'<span class="status-pill {_pc}">{_bl}</span>'
                f'<div class="room-meta">{_room["size"]} &nbsp;·&nbsp; {_am}</div>'
                f'{_ex}</div>'
            )

        _cards_joined = "".join(_status_cards)
        st.markdown(
            f'<div class="mob-greeting">'
            f'<div class="mob-greeting-left">'
            f'<span class="mob-greeting-hi">{_greet},</span>'
            f'<div class="mob-greeting-name-row">'
            f'<span class="mob-greeting-name">{auth_user["name"]}</span>'
            f'{_mob_admin_badge}</div></div></div>'
            f'<div class="mob-status-meta">'
            f'<span class="section-label" style="margin-bottom:0">LIVE ROOM STATUS</span>'
            f'<span class="mob-status-time">Updated {_now_str}</span></div>'
            f'<div class="mob-room-grid-2col">{_cards_joined}</div>',
            unsafe_allow_html=True,
        )

        if is_admin:
            st.markdown('<div style="margin-top:16px"></div>', unsafe_allow_html=True)
            _render_admin_panel(auth_user, key_prefix="status_")

    # ── Tab 1: Book a Room ────────────────────────────────────────────────────
    with tab_book:
        st.markdown('<div class="section-label">Book a Conference Room</div>', unsafe_allow_html=True)

        if st.session_state.get("_booking_success"):
            st.success(st.session_state.pop("_booking_success"))
        col1, col2 = st.columns(2)

        with col1:
            room_options = {_room_label(rid): rid for rid in sorted(ROOMS, reverse=True)}
            selected_room_name = st.selectbox("Select Room", list(room_options.keys()))
            selected_room_id   = room_options[selected_room_name]

            booking_date = st.date_input("Date", min_value=datetime.now().date())

            time_col1, time_col2 = st.columns(2)
            with time_col1:
                start_hour = st.selectbox("Start Time", TIME_SLOTS[:-1], index=2)
            start_idx   = TIME_SLOTS.index(start_hour)
            end_options = TIME_SLOTS[start_idx + 1:]
            with time_col2:
                end_hour = st.selectbox("End Time", end_options, index=0)

        with col2:
            booked_by = st.text_input("Your Name", value=auth_user["name"])
            purpose   = st.text_input("Meeting Purpose",
                                      placeholder="e.g., Team standup, Client call...")

            date_str = booking_date.strftime("%Y-%m-%d")

            active_override = get_active_override(selected_room_id)
            if active_override:
                st.warning(f"This room is currently marked as occupied by admin: **{active_override['reason']}**")

            _btn_check, _btn_book = st.columns(2)
            with _btn_check:
                _do_check = st.button("Check Availability", use_container_width=True)
            with _btn_book:
                _do_book = st.button("Book Room", type="primary", use_container_width=True)

            if _do_check:
                if active_override:
                    st.error(f"Room unavailable — admin override active: {active_override['reason']}")
                else:
                    conflicts = get_conflicts(selected_room_id, date_str, start_hour, end_hour)
                    if not conflicts:
                        st.success(f"Room is available for {start_hour} – {end_hour}.")
                    else:
                        st.error("Room is already booked during this time.")
                        for c in conflicts:
                            st.caption(
                                f"  Booked {to_12hr(c['start_time'])} – {to_12hr(c['end_time'])} "
                                f"by {c['booked_by']}"
                                + (f": {c['purpose']}" if c['purpose'] else "")
                            )

            if _do_book:
                name = booked_by.strip()
                desc = purpose.strip()

                if len(name) < 2:
                    st.error("Please enter your full name (at least 2 characters).")
                elif active_override:
                    st.error(f"Cannot book — admin override is active: {active_override['reason']}")
                else:
                    conflicts = get_conflicts(selected_room_id, date_str, start_hour, end_hour)
                    if conflicts:
                        st.error("Room is not available — slot was just taken.")
                        for c in conflicts:
                            st.caption(
                                f"  Conflict: {to_12hr(c['start_time'])} – "
                                f"{to_12hr(c['end_time'])} by {c['booked_by']}"
                            )
                    elif book_room(selected_room_id, date_str, start_hour, end_hour, name, desc):
                        room = ROOMS[selected_room_id]
                        st.session_state["_booking_success"] = (
                            f"**{room['name']}** booked for "
                            f"**{start_hour} – {end_hour}** on **{booking_date.strftime('%d %b %Y')}**"
                            + (f" · _{desc}_" if desc else "")
                        )
                        st.rerun()
                    else:
                        st.error("Booking failed — the slot may have just been taken. Please try again.")

    # ── Tab 3: Today's Schedule ──────────────────────────────────────────────
    with tab_schedule:
        _today_label = datetime.now().strftime("%A, %d %B %Y")
        st.markdown(
            f'<div class="crm-section-header">'
            f'<span class="section-label" style="margin-bottom:0">Today\'s Schedule</span>'
            f'<span class="crm-section-ts">{_today_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        today  = datetime.now().strftime("%Y-%m-%d")
        now_hm = datetime.now().strftime("%H:%M")

        for room_id, room in sorted(ROOMS.items(), reverse=True):
            _amenities_s = " · ".join(room["amenities"])
            st.markdown(
                f'<div class="sched-room-header">'
                f'<span class="sched-room-name">Floor {room_id} &nbsp;—&nbsp; {room["size"]}</span>'
                f'<span class="sched-room-meta">{_amenities_s} &nbsp;·&nbsp; {room["capacity"]} seats</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            bookings = get_bookings_for_date(room_id, today)

            if not bookings:
                st.markdown(
                    '<div class="sched-empty">No bookings today</div>',
                    unsafe_allow_html=True,
                )
            else:
                for booking in bookings:
                    is_current = booking["start_time"] <= now_hm < booking["end_time"]
                    row_cls  = "sched-row now" if is_current else "sched-row"
                    now_html = '<span class="now-badge">NOW</span>' if is_current else ""
                    _purpose = booking["purpose"] if booking["purpose"] not in ("__check_only__", "") else ""
                    desc_html = f'<div class="sched-desc">{_purpose}</div>' if _purpose else ""

                    can_cancel = is_admin or booking["booked_by"].lower() == auth_user["name"].lower()

                    info_col, btn_col = st.columns([5, 1])
                    with info_col:
                        st.markdown(f"""
                        <div class="{row_cls}">
                            <div class="sched-time">{to_12hr(booking['start_time'])} – {to_12hr(booking['end_time'])}{now_html}</div>
                            <div class="sched-who">{booking['booked_by']}</div>
                            {desc_html}
                        </div>
                        """, unsafe_allow_html=True)
                    with btn_col:
                        if can_cancel:
                            _render_cancel_button(booking, f"today_{room_id}", is_admin=is_admin)

            st.markdown('<div class="sched-divider"></div>', unsafe_allow_html=True)

    # ── Tab 4: Booking History ────────────────────────────────────────────────
    with tab_history:
        st.markdown('<div class="section-label" style="margin-bottom:14px">Booking History</div>', unsafe_allow_html=True)

        with st.form("hist_search_form"):
            search_col1, search_col2 = st.columns(2)
            with search_col1:
                search_name = st.text_input("Search by Name", placeholder="Enter name...")
            with search_col2:
                room_choices = ["All Rooms"] + [
                    f"Floor {rid} – {ROOMS[rid]['size']}"
                    for rid in sorted(ROOMS, reverse=True)
                ]
                search_room = st.selectbox("Filter by Room", room_choices)

            date_col1, date_col2 = st.columns(2)
            with date_col1:
                date_from = st.date_input("From Date", value=None, key="search_from")
            with date_col2:
                date_to = st.date_input("To Date", value=None, key="search_to")

            do_search = st.form_submit_button("Search", type="primary", use_container_width=True)

        room_filter = None
        if search_room != "All Rooms":
            room_filter = int(search_room.split()[1])

        from_str = date_from.strftime("%Y-%m-%d") if date_from else None
        to_str   = date_to.strftime("%Y-%m-%d")   if date_to   else None

        if date_from and date_to and date_from > date_to:
            st.warning("'From Date' is after 'To Date' — no results will match.")

        if not do_search and "hist_results" not in st.session_state:
            st.session_state["hist_results"] = search_bookings()

        if do_search:
            st.session_state["hist_results"] = search_bookings(
                booked_by=search_name.strip() if search_name else None,
                room_id=room_filter,
                date_from=from_str,
                date_to=to_str,
            )
            st.session_state["hist_page"] = 0

        results = st.session_state.get("hist_results", [])

        if results:
            _PAGE_SIZE = 10
            _total     = len(results)
            _max_page  = (_total - 1) // _PAGE_SIZE

            st.session_state.setdefault("hist_page", 0)

            _page  = min(st.session_state["hist_page"], _max_page)
            _start = _page * _PAGE_SIZE
            _end   = min(_start + _PAGE_SIZE, _total)
            _page_results = results[_start:_end]

            _info_col, _nav_col = st.columns([3, 2])
            with _info_col:
                st.success(f"Found **{_total}** booking(s)  ·  showing {_start + 1}–{_end}")
            with _nav_col:
                _prev_col, _page_col, _next_col = st.columns([1, 1.2, 1])
                with _prev_col:
                    if st.button("← Prev", key="hist_prev", use_container_width=True,
                                 disabled=_page == 0):
                        st.session_state["hist_page"] = _page - 1
                        st.rerun()
                with _page_col:
                    st.markdown(
                        f'<div style="text-align:center;padding:6px 0;font-size:0.85rem;font-weight:600">'
                        f'Page {_page + 1} / {_max_page + 1}</div>',
                        unsafe_allow_html=True,
                    )
                with _next_col:
                    if st.button("Next →", key="hist_next", use_container_width=True,
                                 disabled=_page >= _max_page):
                        st.session_state["hist_page"] = _page + 1
                        st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            for booking in _page_results:
                room = ROOMS.get(booking["room_id"], {})
                _hist_purpose = booking["purpose"] if booking["purpose"] not in ("__check_only__", "") else ""
                desc_html = f' · {_hist_purpose}' if _hist_purpose else ""
                can_cancel = is_admin or booking["booked_by"].lower() == auth_user["name"].lower()
                try:
                    _date_display = datetime.strptime(booking["date"], "%Y-%m-%d").strftime("%b %d, %Y")
                except Exception:
                    _date_display = booking["date"]

                info_col, btn_col = st.columns([5, 1])
                with info_col:
                    st.markdown(f"""
                    <div class="hist-row">
                        <div class="hist-date">{_date_display}</div>
                        <div class="hist-room">Floor {booking['room_id']} &nbsp;·&nbsp; {room.get('size','')}</div>
                        <div class="hist-time">{to_12hr(booking['start_time'])} – {to_12hr(booking['end_time'])}</div>
                        <div class="hist-who">{booking['booked_by']}{desc_html}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with btn_col:
                    if can_cancel:
                        _render_cancel_button(booking, f"hist_{booking['id']}", is_admin=is_admin)
        else:
            st.session_state["hist_page"] = 0
            st.info("No bookings found matching your filters.")

    # ── Tab 5: Profile (mobile only — desktop uses the separate profile page) ─
    with tab_profile:
        _pu        = auth_user
        _pname     = _pu.get("name", "—")
        _pinitials = "".join(w[0] for w in _pname.split()[:2]).upper() if _pname.strip() else "?"
        _pempid    = _pu.get("employee_id", "—")
        _pbranch   = _pu.get("branch", "—") or "—"
        _pdept     = _pu.get("department", "—") or "—"
        _pdesig    = _pu.get("designation", "—") or "—"
        _padmin_b  = '<span class="mob-greeting-admin">Admin</span>' if is_admin else ""
        _pwarn     = ""
        if _pu.get("must_change_password"):
            _pwarn = '<div class="profile-warn-banner"><span>You are using your default password. Please change it below.</span></div>'

        st.markdown(
            f'<div class="profile-wrap">'
            f'<div class="profile-hero-card">'
            f'<div class="profile-avatar-wrap">'
            f'<div class="profile-avatar">{_pinitials}</div>'
            f'<div class="profile-av-name">{_pname}</div>'
            f'<div class="profile-av-id-row">'
            f'<span class="profile-av-id">{_pempid}</span>'
            f'{_padmin_b}</div></div></div>'
            f'{_pwarn}'
            f'<div class="profile-info-card">'
            f'<div class="profile-info-row">'
            f'<span class="profile-info-label">Branch</span>'
            f'<span class="profile-info-value">{_pbranch}</span></div>'
            f'<div class="profile-info-row">'
            f'<span class="profile-info-label">Department</span>'
            f'<span class="profile-info-value">{_pdept}</span></div>'
            f'<div class="profile-info-row">'
            f'<span class="profile-info-label">Designation</span>'
            f'<span class="profile-info-value">{_pdesig}</span></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        _pbtn_l, _pbtn_r = st.columns(2)
        with _pbtn_l:
            if st.button("Change Password", key="profile_tab_chgpw",
                         use_container_width=True, type="secondary"):
                _change_password_dialog(_pu["id"])
        with _pbtn_r:
            if st.button("Sign Out", key="profile_tab_signout",
                         type="primary", use_container_width=True):
                logout_session(st.session_state.get("auth_token"))
                for k in ["auth_token", "auth_user", "auth_mode", "auth_error",
                          "pending_oauth", "email_otp_sent", "email_otp_to",
                          "phone_otp_sent", "phone_otp_to"]:
                    st.session_state.pop(k, None)
                st.cache_data.clear()
                try:
                    st.query_params.pop("sid", None)
                except Exception:
                    pass
                st.rerun()

    _render_footer()


if __name__ == "__main__":
    main()
