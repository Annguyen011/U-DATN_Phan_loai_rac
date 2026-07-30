"""
TrashSorter — Main Entry Point
================================
Kiến trúc: 3 threads + JSON store
  T1: Perception   — Camera → AI NCNN → Detection Queue
  T2: Control      — Serial → Arduino → Sort Dispatch
  T3: Web          — Flask + SocketIO Dashboard
  BG: JSON Store   — Auto-save to data/sorter.json

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

_PROJECT_ROOT = Path(__file__).parent         # src/
sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import load_config          # noqa: E402
from perception.fruit_detector import FruitDetector  # noqa: E402
from control.sort_controller import SortController  # noqa: E402
from drivers.serial_link import SerialLink           # noqa: E402
from database.store import TrashStore                # noqa: E402
from shared.detection_result import DetectionResult  # noqa: E402

parser = argparse.ArgumentParser(description="TrashSorter — AI Trash Classification")
parser.add_argument("--config", default=None)
parser.add_argument("--debug", action="store_true")
parser.add_argument("--host", default=None, help="Override web host")
parser.add_argument("--port", type=int, default=None, help="Override web port")
args = parser.parse_args()

cfg_path = args.config or str(_PROJECT_ROOT / "config" / "hardware_config.yaml")
cfg = load_config(cfg_path)
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

stop_event      = threading.Event()
detection_queue = deque(maxlen=cfg["system"]["queue_maxlen"])
queue_lock      = threading.Lock()
store           = TrashStore("data/sorter.json")


def create_app():
    from web.flask_app import create_flask_app
    return create_flask_app(cfg, store, stop_event)


def main() -> None:
    log.info("=" * 55)
    log.info("  ♻️  TrashSorter v1.0 — AI Trash Classification")
    log.info("  Model: %s | Labels: %s", cfg["model"]["path"], list(cfg["model"]["labels"].values()))
    log.info("=" * 55)

    flask_app, socketio = create_app()
    serial_link = SerialLink(cfg, stop_event)
    from web.flask_app import set_serial_for_manual
    set_serial_for_manual(serial_link)
    store.start()

    detector = FruitDetector(
        cfg=cfg, detection_queue=detection_queue,
        queue_lock=queue_lock, stop_event=stop_event,
        name="T1-Perception", daemon=True,
    )

    controller = SortController(
        cfg=cfg, serial_link=serial_link,
        detection_queue=detection_queue, queue_lock=queue_lock,
        store=store, stop_event=stop_event,
        name="T2-Control", daemon=True,
    )

    def shutdown(signum=None, frame=None):
        log.info("🛑 Shutting down...")
        stop_event.set()
        store.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for t in (serial_link, detector, controller):
        t.start()
        log.info("  ▶  %s started", t.name)

    host = args.host or cfg["web"]["host"]
    port = args.port or cfg["web"]["port"]

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║  ♻️  TrashSorter Dashboard                           ║")
    print(f"  ║  🌐  http://{host}:{port}                          ║")
    print("  ║  📷  Camera + AI + Arduino                           ║")
    print("  ║  💾  JSON Store: data/sorter.json                    ║")
    print("  ║  🛑  Press Ctrl+C to stop                            ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()

    socketio.run(flask_app, host=host, port=port, debug=args.debug,
                 use_reloader=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()