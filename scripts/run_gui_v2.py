"""Compatibility launcher for the production desktop GUI.

Task 54A promoted GUI v2 to the production desktop GUI path.  This entry point
is retained as a convenience alias for existing local workflows; it launches the
same application as ``scripts/run_gui.py``.
"""

from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from gui_v2.app import run


if __name__ == "__main__":
    raise SystemExit(run(sys.argv))
