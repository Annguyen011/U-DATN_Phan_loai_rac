"""
serial_protocol.py — UART JSON protocol RPi ↔ Arduino
=======================================================
Master → Slave (270° SWEEP mechanism):
  {"cmd":"SORT","servo":1,"dir":"fire","angle":120,"home":220,"max":270,"min_us":500,"max_us":2500,"sweep_ms":200,"return_ms":300}
  {"cmd":"PING"}
  {"cmd":"RESET","home1":220,"home2":0,"max":270,"min_us":500,"max_us":2500}
  {"cmd":"STATUS"}

Slave → Master:
  {"ack":"IR_TRIGGER","sensor":1,"ts":12345}
  {"ack":"SORT_DONE","servo":1,"angle":120,"home":220,"total_ms":500}
  {"ack":"PONG","uptime_s":123}
"""

from __future__ import annotations
import json
from typing import Optional


def cmd_sort(servo_id: int, direction: str, cfg_servo: dict) -> bytes:
    """Gửi lệnh SORT với đầy đủ params từ config cho servo sweep."""
    return _enc({
        "cmd":       "SORT",
        "servo":     servo_id,
        "dir":       "fire" if direction in ("left", "right") else "home",
        "angle":     cfg_servo.get("sweep_angle", 120),
        "home":      cfg_servo.get("home_angle", 220 if servo_id == 1 else 0),
        "max":       cfg_servo.get("max_angle", 270),
        "min_us":    cfg_servo.get("min_us", 500),
        "max_us":    cfg_servo.get("max_us", 2500),
        "sweep_ms":  cfg_servo.get("sweep_ms", 200),
        "return_ms": cfg_servo.get("return_ms", 300),
    })


def cmd_ping()   -> bytes: return _enc({"cmd": "PING"})
def cmd_reset(cfg: dict = None) -> bytes:
    s1 = (cfg or {}).get("servo1", {}) if cfg else {}
    s2 = (cfg or {}).get("servo2", {}) if cfg else {}
    return _enc({
        "cmd": "RESET",
        "home1": s1.get("home_angle", 220),
        "home2": s2.get("home_angle", 0),
        "max":   s1.get("max_angle", 270),
        "min_us": s1.get("min_us", 500),
        "max_us": s1.get("max_us", 2500),
        "max1":  s1.get("max_angle", 270),
        "max2":  s2.get("max_angle", 270),
        "min1_us": s1.get("min_us", 500),
        "max1_us": s1.get("max_us", 2500),
        "min2_us": s2.get("min_us", 500),
        "max2_us": s2.get("max_us", 2500),
    })
def cmd_status() -> bytes: return _enc({"cmd": "STATUS"})


def parse_response(raw: bytes) -> Optional[dict]:
    try: return json.loads(raw.decode("utf-8").strip())
    except Exception: return None


def is_ir_trigger(msg: dict) -> bool: return msg.get("ack") == "IR_TRIGGER"
def is_pong(msg: dict)      -> bool: return msg.get("ack") == "PONG"
def is_sort_done(msg: dict) -> bool: return msg.get("ack") == "SORT_DONE"


def _enc(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()