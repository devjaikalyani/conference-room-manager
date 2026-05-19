-- conference_rooms.db schema + sample data
-- Run via setup.py or: sqlite3 conference_rooms.db < rooms_schema.sql

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    INTEGER NOT NULL,
    date       TEXT    NOT NULL,            -- YYYY-MM-DD
    start_time TEXT    NOT NULL,            -- HH:MM (24h)
    end_time   TEXT    NOT NULL,            -- HH:MM (24h)
    booked_by  TEXT    NOT NULL,
    purpose    TEXT,
    booked_at  TEXT    NOT NULL,            -- ISO timestamp
    UNIQUE(room_id, date, start_time, end_time)
);

CREATE INDEX IF NOT EXISTS idx_room_date ON bookings(room_id, date);
CREATE INDEX IF NOT EXISTS idx_date      ON bookings(date);
CREATE INDEX IF NOT EXISTS idx_booked_by ON bookings(booked_by);

-- Admin can mark a room as occupied (maintenance, cleaning, etc.)
CREATE TABLE IF NOT EXISTS room_overrides (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id       INTEGER NOT NULL UNIQUE,
    reason        TEXT    NOT NULL DEFAULT 'Maintenance',
    overridden_by TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

-- Sample bookings (adjust dates as needed)
INSERT OR IGNORE INTO bookings (room_id, date, start_time, end_time, booked_by, purpose, booked_at) VALUES
    (5, date('now'), '09:00', '10:00', 'Priya Sharma',   'Sprint planning',   datetime('now')),
    (5, date('now'), '14:00', '15:00', 'Rahul Verma',    'Client call',       datetime('now')),
    (4, date('now'), '10:00', '11:00', 'Anita Desai',    'Design review',     datetime('now')),
    (3, date('now'), '11:00', '12:00', 'Suresh Nair',    'Team standup',      datetime('now')),
    (2, date('now'), '15:00', '16:00', 'Meena Pillai',   'HR interview',      datetime('now'));
