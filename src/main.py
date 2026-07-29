"""
TrashSorter — Main Entry Point
================================
Kiến trúc: 4 threads chạy song song
  T1: Perception   — Camera → AI NCNN → Detection Queue
  T2: Control      — Serial → Arduino → Sort Dispatch
  T3: Web          — Flask + SocketIO Dashboard
  BG: DB Writer    — Batch SQLite persister

Usage:
  python main.py
  python main.py --debug
  python main.py --config config/hardware_config.yaml
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from collections import deque
from pathlib import Path

# ── Add project root to path ────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config.loader import load_config
from perception.fruit_detector import FruitDetector
from control.sort_controller import SortController
from drivers.serial_link import SerialLink
from database.db_writer import DatabaseWriter
from shared.detection_result import DetectionResult

# ── CLI ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="TrashSorter — AI Trash Classification")
parser.add_argument("--config", default="config/hardware_config.yaml")
parser.add_argument("--debug", action="store_true")
parser.add_argument("--host", default=None, help="Override web host")
parser.add_argument("--port", type=int, default=None, help="Override web port")
args = parser.parse_args()

# ── Config & Logging ────────────────────────────────────────────────────────
cfg = load_config(args.config)

log_dir = Path(cfg["system"]["log_file"]).parent
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG if args.debug else logging.INFO,
    format="%(asctime)s [%(threadName)-16s] %(levelname)-5s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(cfg["system"]["log_file"], encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# ── Shared State ────────────────────────────────────────────────────────────
stop_event      = threading.Event()
detection_queue = deque(maxlen=cfg["system"]["queue_maxlen"])
queue_lock      = threading.Lock()
db_write_queue  = deque(maxlen=200)


def create_app():
    """Lazy import Flask app — tránh circular imports."""
    from web.flask_app import create_flask_app
    return create_flask_app(cfg, db_write_queue, stop_event)


def main() -> None:
    log.info("=" * 55)
    log.info("  ♻️  TrashSorter v1.0 — AI Trash Classification")
    log.info("  Model: %s | Labels: %s", cfg["model"]["path"], list(cfg["model"]["labels"].values()))
    log.info("=" * 55)

    # ── Flask app ──────────────────────────────────────────────────────
    flask_app, socketio = create_app()

    # ── Serial link ────────────────────────────────────────────────────
    serial_link = SerialLink(cfg, stop_event)

    # ── Thread 1: Perception ───────────────────────────────────────────
    detector = FruitDetector(
        cfg=cfg,
        detection_queue=detection_queue,
        queue_lock=queue_lock,
        stop_event=stop_event,
        name="T1-Perception",
        daemon=True,
    )

    # ── Thread 2: Control ──────────────────────────────────────────────
    controller = SortController(
        cfg=cfg,
        serial_link=serial_link,
        detection_queue=detection_queue,
        queue_lock=queue_lock,
        db_write_queue=db_write_queue,
        stop_event=stop_event,
        name="T2-Control",
        daemon=True,
    )

    # ── Background: DB Writer ──────────────────────────────────────────
    db_writer = DatabaseWriter(
        cfg=cfg,
        write_queue=db_write_queue,
        stop_event=stop_event,
        name="DB-Writer",
        daemon=True,
    )

    # ── Graceful shutdown ──────────────────────────────────────────────
    def shutdown(signum=None, frame=None):
        log.info("🛑 Shutting down all threads...")
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── Start all threads ──────────────────────────────────────────────
    for t in (serial_link, detector, controller, db_writer):
        t.start()
        log.info("  ▶  %s started", t.name)

    # ── Flask (blocking main thread) ───────────────────────────────────
    host = args.host or cfg["web"]["host"]
    port = args.port or cfg["web"]["port"]

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║  ♻️  TrashSorter Dashboard                           ║")
    print(f"  ║  🌐  http://{host}:{port}                          ║")
    print("  ║  📷  Camera + AI + Arduino                           ║")
    print("  ║  🛑  Press Ctrl+C to stop                            ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    socketio.run(
        flask_app,
        host=host,
        port=port,
        debug=args.debug,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()