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

import logging
import threading
import time

from flask import Flask, Response, jsonify, render_template, request
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

_latest_frame_lock = threading.Lock()
_latest_frame      = None
_socketio_ref: SocketIO | None = None
_store             = None

def push_frame(jpeg_bytes: bytes):
    global _latest_frame
    with _latest_frame_lock:
        _latest_frame = jpeg_bytes

def push_detection_event(label: str, confidence: float):
    if _socketio_ref:
        _socketio_ref.emit("detection", {"label": label, "confidence": confidence, "ts": time.time()})

def create_flask_app(cfg: dict, store, stop_event: threading.Event) -> tuple[Flask, SocketIO]:
    global _socketio_ref, _store
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