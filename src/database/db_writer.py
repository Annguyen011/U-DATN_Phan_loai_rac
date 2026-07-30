"""
database/db_writer.py — Background batch writer (SQLite WAL)
=============================================================
Lưu mọi SortEvent vào sort_events + cập nhật daily_stats.
Nhẹ, không dependency ngoài — chỉ dùng sqlite3 built-in.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_SQL_EVENTS = """
CREATE TABLE IF NOT EXISTS sort_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trash_type  TEXT    NOT NULL,
    confidence  REAL    NOT NULL,
    action      TEXT    NOT NULL,
    station     INTEGER NOT NULL DEFAULT 1,
    is_reject   INTEGER NOT NULL DEFAULT 0,
    sorted_at   REAL    NOT NULL
);"""

_SQL_STATS = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date            TEXT PRIMARY KEY,
    kim_loai        INTEGER DEFAULT 0,
    nhua            INTEGER DEFAULT 0,
    giay            INTEGER DEFAULT 0,
    khong_phai_rac  INTEGER DEFAULT 0,
    rejects         INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0
);"""

_SQL_INSERT = """
INSERT INTO sort_events (trash_type, confidence, action, station, is_reject, sorted_at)
VALUES (?,?,?,?,?,?)"""

_SQL_UPSERT = """
INSERT INTO daily_stats (date, kim_loai, nhua, giay, khong_phai_rac, rejects, total)
VALUES (?,?,?,?,?,?,?)
ON CONFLICT(date) DO UPDATE SET
    kim_loai        = kim_loai        + excluded.kim_loai,
    nhua            = nhua            + excluded.nhua,
    giay            = giay            + excluded.giay,
    khong_phai_rac  = khong_phai_rac  + excluded.khong_phai_rac,
    rejects         = rejects         + excluded.rejects,
    total           = total           + excluded.total"""

class DatabaseWriter(threading.Thread):
    def __init__(self, cfg: dict, write_queue: deque, stop_event: threading.Event, **kw):
        super().__init__(**kw)
        db              = cfg["database"]
        self._path      = db["path"]
        self._wal       = db.get("wal_mode", True)
        self._cache     = db.get("cache_kb", 4096)
        self._ivl       = db["write_queue"]["flush_interval_s"]
        self._batch     = db["write_queue"]["flush_batch_size"]
        self._queue     = write_queue
        self._stop      = stop_event
        self._conn: sqlite3.Connection | None = None

    def run(self):
        self._conn = self._connect()
        log.info("DatabaseWriter started")
        last = time.monotonic()
        while not self._stop.is_set():
            if (time.monotonic() - last) >= self._ivl or len(self._queue) >= self._batch:
                self._flush()
                last = time.monotonic()
            time.sleep(0.5)
        self._flush()
        self._conn.close()
        log.info("DatabaseWriter stopped")

    def _flush(self):
        if not self._queue:
            return
        batch = [self._queue.popleft() for _ in range(len(self._queue))]
        try:
            with self._conn:
                rows = [(e.trash_type, e.confidence, e.action,
                         e.station, int(e.is_reject), e.sorted_at_ms) for e in batch]
                self._conn.executemany(_SQL_INSERT, rows)

                today   = datetime.now().strftime("%Y-%m-%d")
                counts  = Counter(e.trash_type for e in batch if not e.is_reject)
                rejects = sum(1 for e in batch if e.is_reject)
                self._conn.execute(_SQL_UPSERT, (
                    today,
                    counts.get("KIM_LOAI",       0),
                    counts.get("NHUA",           0),
                    counts.get("GIAY",           0),
                    counts.get("KHONG_PHAI_RAC", 0),
                    rejects, len(batch),
                ))
            log.debug("DB flush: %d events", len(batch))
        except sqlite3.Error as e:
            log.error("DB error: %s — re-queuing", e)
            for item in reversed(batch):
                self._queue.appendleft(item)

    def _connect(self):
        p = Path(self._path); p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p), check_same_thread=False)
        if self._wal: conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA cache_size=-{self._cache}")
        conn.execute(_SQL_EVENTS)
        conn.execute(_SQL_STATS)
        conn.commit()
        log.info("Database ready: %s", p)
        return conn