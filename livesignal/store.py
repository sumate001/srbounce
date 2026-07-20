"""SQLite persistence: trades, singleton state row, zone snapshots.

Restart safety: open trade lives in `trades` (exit_time IS NULL); state
(equity, paused, day_key, day_realised_pnl) lives in the singleton `state`
row. Nothing is held only in memory.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    entry REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    size REAL NOT NULL,
    zone_center REAL NOT NULL,
    pattern TEXT NOT NULL,
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    r_multiple REAL,
    paper INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    equity REAL NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    day_key TEXT NOT NULL,
    day_realised_pnl REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS zones_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    center REAL NOT NULL,
    lo REAL NOT NULL,
    hi REAL NOT NULL,
    kind TEXT NOT NULL,
    touches INTEGER NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def init_state(conn: sqlite3.Connection, initial_equity: float, day_key: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO state (id, equity, paused, day_key, day_realised_pnl) "
        "VALUES (1, ?, 0, ?, 0)",
        (initial_equity, day_key),
    )
    conn.commit()


def get_state(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM state WHERE id = 1").fetchone()
    return dict(row) if row else {}


def update_state(conn: sqlite3.Connection, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE state SET {cols} WHERE id = 1", tuple(fields.values()))
    conn.commit()


def get_open_trade(conn: sqlite3.Connection, market: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM trades WHERE market = ? AND exit_time IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (market,),
    ).fetchone()
    return dict(row) if row else None


def insert_trade(conn: sqlite3.Connection, market: str, direction: str, entry_time: str,
                  entry: float, sl: float, tp: float, size: float, zone_center: float,
                  pattern: str, paper: bool) -> int:
    cur = conn.execute(
        "INSERT INTO trades (market, direction, entry_time, entry, sl, tp, size, "
        "zone_center, pattern, paper) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (market, direction, entry_time, entry, sl, tp, size, zone_center, pattern, int(paper)),
    )
    conn.commit()
    return cur.lastrowid


def close_trade(conn: sqlite3.Connection, trade_id: int, exit_time: str, exit_price: float,
                 exit_reason: str, pnl: float, r_multiple: float) -> None:
    conn.execute(
        "UPDATE trades SET exit_time = ?, exit_price = ?, exit_reason = ?, "
        "pnl = ?, r_multiple = ? WHERE id = ?",
        (exit_time, exit_price, exit_reason, pnl, r_multiple, trade_id),
    )
    conn.commit()


def recent_closed_trades(conn: sqlite3.Connection, market: str | None = None, since: str | None = None) -> list[dict]:
    q = "SELECT * FROM trades WHERE exit_time IS NOT NULL"
    args: list = []
    if market:
        q += " AND market = ?"
        args.append(market)
    if since:
        q += " AND exit_time >= ?"
        args.append(since)
    q += " ORDER BY id"
    with closing(conn.execute(q, args)) as cur:
        return [dict(r) for r in cur.fetchall()]


def save_zones_snapshot(conn: sqlite3.Connection, market: str, taken_at: str, zones: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO zones_snapshot (market, taken_at, center, lo, hi, kind, touches) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(market, taken_at, z["center"], z["lo"], z["hi"], z["kind"], z["touches"]) for z in zones],
    )
    conn.commit()


def latest_zones_snapshot(conn: sqlite3.Connection, market: str) -> list[dict]:
    row = conn.execute(
        "SELECT taken_at FROM zones_snapshot WHERE market = ? ORDER BY id DESC LIMIT 1",
        (market,),
    ).fetchone()
    if not row:
        return []
    with closing(conn.execute(
        "SELECT * FROM zones_snapshot WHERE market = ? AND taken_at = ?",
        (market, row["taken_at"]),
    )) as cur:
        return [dict(r) for r in cur.fetchall()]
