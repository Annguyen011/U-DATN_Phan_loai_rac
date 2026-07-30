"""
database/store.py — Ultra-light JSON-based storage
====================================================
Thay thế SQLite bằng JSON file. Nhẹ hơn, 0 dependencies,
dễ đọc, dễ backup. Thread-safe với lock đơn giản.

Cấu trúc file:
  data/sorter.json → { "events": [...], "daily": {...}, "summary": {...} }
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

class TrashStore:
    """Singleton JSON store for all trash sorting events & stats."""

    def __init__(self, path: str = "data/sorter.json", flush_ivl: float = 5.0):
        self._path     = Path(path)
        self._flush_ivl = flush_ivl
        self._lock     = threading.Lock()
        self._stop     = threading.Event()
        self._events: list[dict]   = []
        self._daily: dict[str, dict] = {}       # date → {kim_loai,nhua,...}
        self._summary: dict[str, int] = defaultdict(int)  # live counters

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()
        self._thread = threading.Thread(target=self._loop, name="Store", daemon=True)

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()
        log.info("TrashStore started — %s", self._path)

    def stop(self):
        self._stop.set()
        self._flush()
        log.info("TrashStore stopped — %d events saved", len(self._events))

    def add(self, trash_type: str, confidence: float, action: str,
             station: int = 1, is_reject: bool = False):
        """Gọi từ SortController — push 1 event vào buffer."""
        event = {
            "ts":       time.time() * 1000,
            "type":     trash_type,
            "conf":     round(confidence, 3),
            "action":   action,
            "station":  station,
            "reject":   is_reject,
        }
        with self._lock:
            self._events.append(event)
            if not is_reject:
                self._summary[trash_type] += 1
            else:
                self._summary["rejects"] += 1

    def live_counts(self) -> dict:
        """Trả về live counters cho dashboard."""
        with self._lock:
            return dict(self._summary)

    def today_stats(self) -> dict:
        """Thống kê hôm nay."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            return self._daily.get(today, {})

    def history(self, days: int = 7) -> list[dict]:
        """Lịch sử N ngày gần nhất."""
        from datetime import timedelta
        dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(days)]
        with self._lock:
            return [{"date": d, **self._daily.get(d, {})} for d in reversed(dates)
                    if d in self._daily]

    def recent_events(self, limit: int = 50) -> list[dict]:
        """N events gần nhất."""
        with self._lock:
            return list(reversed(self._events[-limit:]))

    def hourly_breakdown(self) -> list[dict]:
        """Phân tích theo giờ hôm nay."""
        today = datetime.now().strftime("%Y-%m-%d")
        result: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        with self._lock:
            for e in self._events:
                ts = e["ts"]
                try:
                    dt = datetime.fromtimestamp(ts / 1000)
                except Exception:
                    continue
                if dt.strftime("%Y-%m-%d") == today and not e["reject"]:
                    result[dt.hour][e["type"]] += 1
        return [{"hour": h, **counts} for h, counts in sorted(result.items())]

    # ── Internal ────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.is_set():
            if self._events:
                self._flush()
            time.sleep(self._flush_ivl)

    def _flush(self):
        """Ghi events + cập nhật daily stats → JSON file."""
        with self._lock:
            if not self._events:
                return
            # Gộp events mới vào daily stats
            today = datetime.now().strftime("%Y-%m-%d")
            day = self._daily.setdefault(today, defaultdict(int))
            for e in self._events:
                if not e["reject"]:
                    day[e["type"]] += 1
                else:
                    day["rejects"] += 1
                day["total"] += 1
            # Ghi toàn bộ ra JSON
            data = {
                "events":  self._events[-10000:],   # giữ tối đa 10k events
                "daily":   {k: dict(v) for k, v in self._daily.items()},
                "summary": dict(self._summary),
            }
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    def _load(self):
        """Đọc dữ liệu từ file JSON nếu có."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text("utf-8"))
            self._events  = data.get("events", [])[-5000:]
            self._daily   = {k: defaultdict(int, v) for k, v in data.get("daily", {}).items()}
            self._summary = defaultdict(int, data.get("summary", {}))
            log.info("Loaded %d events from %s", len(self._events), self._path)
        except Exception as e:
            log.warning("Failed to load store: %s — starting fresh", e)