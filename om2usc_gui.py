#!/usr/bin/env python3
"""Launch the om2usc Windows GUI."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from gui.app import main as run_gui
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print("PySide6 is required for the GUI. Install dependencies with:")
            print("  python -m pip install -r requirements.txt")
            return 1
        raise
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
