"""Launch the production desktop GUI.

GUI v2 is the active desktop application after Task 54A. The legacy GUI v1
package is retained only under ``docs/archive/gui_v1_legacy_reference`` for
historical inspection.
"""

from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


if __name__ == "__main__":
    # PyInstaller worker processes re-enter this script. Divert them before
    # importing Qt and prediction modules, some of which allocate
    # multiprocessing synchronization primitives during import.
    from multiprocessing import freeze_support

    freeze_support()

    from gui_v2.app import run

    raise SystemExit(run(sys.argv))
