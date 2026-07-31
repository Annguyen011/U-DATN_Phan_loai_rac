"""
web/flask_app.py — Flask + SocketIO Dashboard
===============================================
Routes:
  GET  /                    → index.html
  GET  /video_feed          → MJPEG camera stream
  GET  /api/stats/live      → real-time counters (from store)
  GET  /api/stats/today     → today stats (from store)
  GET  /api/stats/history   → ?days=7 history
  GET  /api/events/recent   → ?limit=50 recent events
  GET  /api/stats/hourly    → hourly breakdown
  GET  /api/health          → health check
  SocketIO: stats_update, detection, sort_event
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

_latest_frame_lock = threading.Lock()
_latest_frame      = None
_socketio_ref: SocketIO | None = None
_store             = None
_serial_ref        = None  # để gửi lệnh manual
_servo_cfg         = {}

def push_frame(jpeg_bytes: bytes):
    global _latest_frame
    with _latest_frame_lock:
        _latest_frame = jpeg_bytes

def push_detection_event(label: str, confidence: float):
    if _socketio_ref:
        _socketio_ref.emit("detection", {"label": label, "confidence": confidence, "ts": time.time()})

def set_serial_for_manual(serial_link):
    global _serial_ref, _servo_cfg
    _serial_ref = serial_link

def create_flask_app(cfg: dict, store, stop_event: threading.Event) -> tuple[Flask, SocketIO]:
    global _socketio_ref, _store, _servo_cfg
    _servo_cfg = cfg.get("hardware", {}).get("servos", {})
    _store = store

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = cfg["web"]["secret_key"]

    socketio = SocketIO(app, async_mode=cfg["web"]["socketio_async_mode"],
                        cors_allowed_origins=cfg["web"]["cors_allowed_origins"],
                        logger=False, engineio_logger=False)
    _socketio_ref = socketio
    push_ivl = cfg["dashboard"]["push_interval_s"]

    @app.route("/")
    def dashboard():
        return render_template("index.html")

    # ── MJPEG Video stream ───────────────────────────────────────────────
    @app.route("/video_feed")
    def video_feed():
        import cv2, numpy as np

        def _placeholder(text="Waiting for camera..."):
            ph = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(ph, text, (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80,80,80), 1)
            _, buf = cv2.imencode(".jpg", ph, [cv2.IMWRITE_JPEG_QUALITY, 70])
            return buf.tobytes()

        placeholder_waiting = _placeholder("Waiting for camera...")
        placeholder_offline = _placeholder("Camera offline")
        last_real_frame_ts = 0.0
        OFFLINE_TIMEOUT = 5.0

        def generate():
            nonlocal last_real_frame_ts
            while True:
                try:
                    with _latest_frame_lock:
                        frame_bytes = _latest_frame
                    now = time.monotonic()
                    if frame_bytes is not None:
                        last_real_frame_ts = now
                        out_bytes = frame_bytes
                    elif last_real_frame_ts == 0.0:
                        out_bytes = placeholder_waiting
                    elif (now - last_real_frame_ts) > OFFLINE_TIMEOUT:
                        out_bytes = placeholder_offline
                    else:
                        out_bytes = frame_bytes or placeholder_waiting
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + out_bytes + b"\r\n")
                    time.sleep(0.033)
                except GeneratorExit:
                    break

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                                 "Pragma": "no-cache", "Expires": "0"})

    # ── REST APIs (dùng store thay vì SQLite) ────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "ts": time.time()})

    @app.route("/api/stats/live")
    def stats_live():
        return jsonify({**_store.live_counts(), "ts": time.time()})

    @app.route("/api/stats/today")
    def stats_today():
        return jsonify(_store.today_stats())

    @app.route("/api/stats/history")
    def stats_history():
        days = request.args.get("days", 7, type=int)
        return jsonify(_store.history(days))

    @app.route("/api/events/recent")
    def events_recent():
        limit = request.args.get("limit", 50, type=int)
        return jsonify(_store.recent_events(limit))

    @app.route("/api/stats/hourly")
    def stats_hourly():
        return jsonify(_store.hourly_breakdown())

    @app.route("/api/arduino/status")
    def arduino_status():
        """Trả về trạng thái kết nối Arduino + servo."""
        online = bool(_serial_ref and _serial_ref.is_connected)
        return jsonify({
            "online": online,
            "servo1": _servo_cfg.get("servo1", {}).get("home_angle", 0),
            "servo2": _servo_cfg.get("servo2", {}).get("home_angle", 0),
            "ts": time.time(),
        })

    @app.route("/api/servo/calibrate", methods=["POST"])
    def servo_calibrate():
        """Test servo góc — di chuyển đến góc, giữ 1s, detach."""
        data = request.get_json() or {}
        servo_id = data.get("servo", 1)
        angle = data.get("angle", 90)

        if _serial_ref:
            from shared.serial_protocol import cmd_calibrate
            _serial_ref.send(cmd_calibrate(servo_id, angle))
            return jsonify({"ok": True, "servo": servo_id, "angle": angle})
        return jsonify({"ok": False, "msg": "No serial link"}), 503

    @app.route("/api/servo/config", methods=["POST"])
    def servo_set_config():
        """Lưu cấu hình góc home + sweep cho servo (Arduino + file JSON)."""
        data = request.get_json() or {}
        servo_id = data.get("servo", 1)
        home = data.get("home", 0)
        sweep = data.get("sweep", 90)
        label = data.get("label", f"Servo {servo_id}")

        if _serial_ref:
            from shared.serial_protocol import cmd_set_config
            _serial_ref.send(cmd_set_config(servo_id, home, sweep))

        # Save to JSON file for persistence
        config_path = Path("data/servo_config.json")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_data = {}
        if config_path.exists():
            try: config_data = json.loads(config_path.read_text())
            except: pass
        key = f"servo{servo_id}"
        config_data[key] = {"home": home, "sweep": sweep, "label": label, "ts": time.time()}
        config_path.write_text(json.dumps(config_data, indent=2, ensure_ascii=False))

        return jsonify({"ok": True, "servo": servo_id, "home": home, "sweep": sweep})

    @app.route("/api/servo/config", methods=["GET"])
    def servo_get_config():
        """Đọc cấu hình servo đã lưu từ file JSON."""
        config_path = Path("data/servo_config.json")
        if config_path.exists():
            try: return jsonify(json.loads(config_path.read_text()))
            except: pass
        return jsonify({})

    @app.route("/api/servo/manual", methods=["POST"])
    def servo_manual():
        """Trigger servo manually from dashboard button."""
        data = request.get_json() or {}
        trash_type = data.get("type", "KIM_LOAI")
        direction = data.get("dir", "left")

        # Map loại rác → servo + direction
        routes = {
            "KIM_LOAI":       (1, "left"),
            "NHUA":           (2, "left"),
            "GIAY":           (2, "right"),
            "KHONG_PHAI_RAC": (None, None),
        }
        servo_id, _dir = routes.get(trash_type, (None, None))
        if servo_id is None:
            return jsonify({"ok": False, "msg": "No servo for this type"}), 400

        cfg_key = f"servo{servo_id}"
        cfg_servo = _servo_cfg.get(cfg_key, {})

        if _serial_ref:
            from shared.serial_protocol import cmd_sort
            _serial_ref.send(cmd_sort(servo_id, _dir or direction, cfg_servo))
            _store.add(trash_type, 1.0, f"MANUAL_SERVO{servo_id}_{(_dir or direction).upper()}", 0, is_reject=False)
            return jsonify({"ok": True, "servo": servo_id, "type": trash_type})
        return jsonify({"ok": False, "msg": "No serial link"}), 503

    # ── SocketIO background push ─────────────────────────────────────────
    def _push_loop():
        while not stop_event.is_set():
            socketio.emit("stats_update", {**_store.live_counts(), "ts": time.time()})
            time.sleep(push_ivl)

    socketio.start_background_task(_push_loop)

    @socketio.on("connect")
    def on_connect():
        log.info("SocketIO client: %s", request.sid)

    @socketio.on("disconnect")
    def on_disconnect():
        log.info("SocketIO client disconnected: %s", request.sid)

    return app, socketio