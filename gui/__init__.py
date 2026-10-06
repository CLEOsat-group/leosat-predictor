"""Desktop GUI package for the LEO satellite predictor.

This is the production PyQt6 desktop application: the dashboard shell,
workflow-stage navigation, and the Overpass, Precise, and Observation Planner
workflow pages.
"""

from __future__ import annotations

__all__ = ["__version__"]

# Single source of truth for the application version. Packaging metadata in
# pyproject.toml derives from this via setuptools' dynamic ``attr`` support.
__version__ = "1.0.1"


def _preload_system_icu() -> None:
    """Load Windows' system ICU before PyQt6/Qt import it.

    Qt's ``Qt6Core.dll`` links ``icuuc.dll`` by its unversioned name and is
    built to use the ICU that ships in ``System32``.  When the interpreter runs
    inside a conda environment, conda's ``icu`` package places an incompatible,
    version-suffixed ``icuuc.dll`` on the DLL search path ahead of ``System32``.
    Qt then binds against those symbols, which do not exist, and import fails
    with ``ImportError: DLL load failed while importing QtCore``.

    Loading the ``System32`` copy first claims the ``icuuc.dll`` module name for
    the process, so Qt reuses the compatible build.  Best-effort and Windows
    only; a no-op everywhere else and when the system DLL is absent.
    """

    import sys

    if sys.platform != "win32":
        return
    import ctypes
    import os

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    icu_path = os.path.join(system_root, "System32", "icuuc.dll")
    if not os.path.exists(icu_path):
        return
    try:
        ctypes.WinDLL(icu_path)
    except OSError:
        # If the system ICU cannot be loaded we fall through and let Qt attempt
        # its normal resolution; this preload is only a hint, never a hard dep.
        pass


_preload_system_icu()
