"""
shared/detection_result.py
Cấu trúc dữ liệu dùng chung toàn project.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time


class TrashType(str, Enum):
    KIM_LOAI       = "KIM_LOAI"
    NHUA           = "NHUA"
    GIAY           = "GIAY"
    KHONG_PHAI_RAC = "KHONG_PHAI_RAC"
    UNKNOWN        = "UNKNOWN"

# Alias for backward compatibility during migration
FruitColor = TrashType


class SortAction(str, Enum):
    SERVO1_LEFT  = "SERVO1_LEFT"
    SERVO1_RIGHT = "SERVO1_RIGHT"
    SERVO2_LEFT  = "SERVO2_LEFT"
    SERVO2_RIGHT = "SERVO2_RIGHT"
    REJECT       = "REJECT"


@dataclass
class DetectionResult:
    """Thread 1 → Thread 2 qua Shared Queue."""
    trash_type:   TrashType
    confidence:   float
    timestamp_ms: float    = field(default_factory=lambda: time.monotonic() * 1000)
    frame_id:     int      = 0
    bbox:         tuple    = field(default_factory=tuple)
    action:       SortAction = SortAction.REJECT

    @property
    def fruit_color(self) -> TrashType:
        """Backward compatibility alias."""
        return self.trash_type

    def __repr__(self) -> str:
        return (
            f"DetectionResult({self.trash_type.value} "
            f"conf={self.confidence:.2f} action={self.action.value})"
        )


@dataclass
class SortEvent:
    """Ghi vào SQLite sau khi servo đã kích."""
    trash_type:   str
    confidence:   float
    action:       str
    sorted_at_ms: float = field(default_factory=lambda: time.time() * 1000)
    station:      int   = 1
    is_reject:    bool  = False

    @property
    def fruit_color(self) -> str:
        """Backward compatibility alias."""
        return self.trash_type
