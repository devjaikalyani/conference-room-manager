"""
One-time migration: reads data from the local SQLite files and pushes it to Supabase.

Run AFTER you have:
  1. Run supabase_schema.sql in the Supabase SQL editor
  2. Set SUPABASE_URL and SUPABASE_KEY in your environment or .env

Usage:
    python migrate_to_supabase.py
"""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env.shared")
load_dotenv(ROOT / ".env", override=True)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

AUTH_DB   = ROOT / "crm_auth.db"
ROOMS_DB  = ROOT / "conference_rooms.db"

if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env or environment.")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


def migrate_users() -> None:
    print("Migrating users...")
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()

    ok = skip = fail = 0
    for row in rows:
        data = {k: row[k] for k in row.keys()}
        data.setdefault("created_at", "")
        try:
            sb.table("users").upsert(data, on_conflict="employee_id").execute()
            ok += 1
        except Exception as e:
            print(f"  FAIL user {data.get('employee_id')}: {e}")
            fail += 1
    print(f"  Users: {ok} upserted, {fail} failed")


def migrate_bookings() -> None:
    print("Migrating bookings...")
    conn = sqlite3.connect(ROOMS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM bookings").fetchall()
    conn.close()

    ok = fail = 0
    for row in rows:
        data = {k: row[k] for k in row.keys() if k != "id"}
        try:
            sb.table("bookings").upsert(
                data, on_conflict="room_id,date,start_time,end_time"
            ).execute()
            ok += 1
        except Exception as e:
            print(f"  FAIL booking: {e}")
            fail += 1
    print(f"  Bookings: {ok} upserted, {fail} failed")


def migrate_overrides() -> None:
    print("Migrating room overrides...")
    conn = sqlite3.connect(ROOMS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM room_overrides").fetchall()
    conn.close()

    ok = fail = 0
    for row in rows:
        data = {k: row[k] for k in row.keys() if k != "id"}
        try:
            sb.table("room_overrides").upsert(data, on_conflict="room_id").execute()
            ok += 1
        except Exception as e:
            print(f"  FAIL override room {data.get('room_id')}: {e}")
            fail += 1
    print(f"  Overrides: {ok} upserted, {fail} failed")


if __name__ == "__main__":
    migrate_users()
    migrate_bookings()
    migrate_overrides()
    print("Done.")
