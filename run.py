#!/usr/bin/env python3
"""
TrashSorter — Quick Launcher
==============================
Usage:
  python run.py                    # Production mode
  python run.py --debug            # Debug mode with verbose logging
  python run.py --host 0.0.0.0 --port 8080

Chạy file này từ thư mục gốc của dự án.
"""

import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from main import main

if __name__ == "__main__":
    main()