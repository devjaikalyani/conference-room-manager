-- Run this once in the Supabase SQL Editor (Database → SQL Editor → New query)
-- Project: Conference Room Manager

CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,
    employee_id          TEXT UNIQUE NOT NULL,
    name                 TEXT NOT NULL,
    email                TEXT UNIQUE,
    phone                TEXT UNIQUE,
    password_hash        TEXT,
    google_id            TEXT UNIQUE,
    zoho_id              TEXT UNIQUE,
    is_active            INTEGER DEFAULT 1,
    is_admin             INTEGER DEFAULT 0,
    branch               TEXT DEFAULT '',
    department           TEXT DEFAULT '',
    designation          TEXT DEFAULT '',
    must_change_password INTEGER DEFAULT 0,
    created_at           TEXT DEFAULT '',
    last_login           TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id          BIGSERIAL PRIMARY KEY,
    identifier  TEXT NOT NULL,
    code        TEXT NOT NULL,
    purpose     TEXT NOT NULL DEFAULT 'login',
    expires_at  TEXT NOT NULL,
    used        INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_otp ON otp_codes(identifier, purpose, used);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    expires_at  TEXT NOT NULL,
    created_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS bookings (
    id         BIGSERIAL PRIMARY KEY,
    room_id    INTEGER NOT NULL,
    date       TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL,
    booked_by  TEXT NOT NULL,
    purpose    TEXT,
    booked_at  TEXT NOT NULL,
    UNIQUE(room_id, date, start_time, end_time)
);
CREATE INDEX IF NOT EXISTS idx_room_date ON bookings(room_id, date);
CREATE INDEX IF NOT EXISTS idx_date      ON bookings(date);
CREATE INDEX IF NOT EXISTS idx_booked_by ON bookings(booked_by);

CREATE TABLE IF NOT EXISTS room_overrides (
    id            BIGSERIAL PRIMARY KEY,
    room_id       INTEGER NOT NULL UNIQUE,
    reason        TEXT NOT NULL DEFAULT 'Maintenance',
    overridden_by TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
