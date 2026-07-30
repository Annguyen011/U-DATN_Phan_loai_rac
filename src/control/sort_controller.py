"""
control/sort_controller.py  ·  Thread 2 — Control
===================================================
Lắng nghe IR_TRIGGER từ Arduino Slave qua Serial
→ FIFO dequeue DetectionResult
→ Kiểm tra timing window
→ Gửi lệnh SORT về Arduino
→ Đẩy SortEvent vào db_write_queue

Tương đương: master/utils/control_bridge.py (cũ)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from drivers.serial_link import SerialLink
from shared.detection_result import DetectionResult, SortAction, TrashType
from shared.serial_protocol import cmd_sort, parse_response, is_ir_trigger

log = logging.getLogger(__name__)


class SortController(threading.Thread):
    """Thread 2 — nhận IR event từ Arduino, quyết định servo nào kích."""

    def __init__(
        self,
        cfg: dict,
        serial_link: SerialLink,
        detection_queue: deque,
        queue_lock: threading.Lock,
        store,
        stop_event: threading.Event,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._cfg      = cfg
        self._serial   = serial_link
        self._queue    = detection_queue
        self._lock     = queue_lock
        self._store    = store
        self._stop     = stop_event

        timing = cfg["conveyor"]["timing"]
        self._windows = {
            1: timing.get("ir1_window_ms", [700,  1000]),
            2: timing.get("ir2_window_ms", [1200, 1800]),
        }

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("SortController (T2) started — listening for IR triggers")
        while not self._stop.is_set():
            raw = self._serial.read_line()
            if not raw:
                time.sleep(0.001)
                continue

            msg = parse_response(raw)
            if not msg:
                continue

            if is_ir_trigger(msg):
                self._handle_ir_trigger(msg)

        log.info("SortController stopped")

    # ── IR trigger handler ─────────────────────────────────────────────────

    def _handle_ir_trigger(self, msg: dict) -> None:
        sensor_id = msg.get("sensor", 1)
        now_ms    = time.monotonic() * 1000

        with self._lock:
            if not self._queue:
                log.warning(f"IR{sensor_id} triggered — queue empty, ignoring")
                return

            item: DetectionResult = self._queue[0]
            delta_ms = now_ms - item.timestamp_ms
            window   = self._windows.get(sensor_id, [0, 9999])

            if not (window[0] <= delta_ms <= window[1]):
                log.warning(
                    f"IR{sensor_id} timing mismatch: "
                    f"delta={delta_ms:.0f}ms, expected {window[0]}–{window[1]}ms"
                )
                return

            self._queue.popleft()

        self._dispatch(sensor_id, item)

    def _dispatch(self, sensor_id: int, item: DetectionResult) -> None:
        if item.action == SortAction.REJECT:
            log.info(f"IR{sensor_id}: {item.trash_type.value} → REJECT")
            self._store.add(item.trash_type.value, item.confidence, item.action.value, sensor_id, is_reject=True)
            return

        parts     = item.action.value.split("_")
        servo_id  = int(parts[0].replace("SERVO", ""))
        direction = parts[1].lower()

        # Đọc config servo từ hardware_config.yaml
        servo_key = f"servo{servo_id}"
        cfg_servo = self._cfg.get("hardware", {}).get("servos", {}).get(servo_key, {})

        ok = self._serial.send(cmd_sort(servo_id, direction, cfg_servo))
        status = "OK" if ok else "SERIAL_ERR"
        self._store.add(item.trash_type.value, item.confidence, item.action.value, sensor_id, is_reject=False)
        log.info(
            f"IR{sensor_id}: {item.trash_type.value} → "
            f"SERVO{servo_id} {direction.upper()} "
            f"[conf={item.confidence:.2f}] [{status}]"
        )
