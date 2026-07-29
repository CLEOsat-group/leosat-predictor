# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the production GUI application.

The same dependency graph supports both a fast-start one-folder distribution
and a portable one-file executable.  Build mode is selected through
``LEOSAT_DISTRIBUTION_MODE``; configuration is selected through
``LEOSAT_BUILD_CONFIGURATION``.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve().parents[1]
_SUPPORTED_CONFIGURATIONS = {"diagnostic", "release"}
_build_configuration = os.environ.get(
    "LEOSAT_BUILD_CONFIGURATION",
    "Release",
).strip().lower()

if _build_configuration not in _SUPPORTED_CONFIGURATIONS:
    supported = ", ".join(sorted(_SUPPORTED_CONFIGURATIONS))
    raise ValueError(
        "LEOSAT_BUILD_CONFIGURATION must be one of "
        f"{supported}; received {_build_configuration!r}."
    )

_SUPPORTED_DISTRIBUTION_MODES = {"faststart", "portable"}
_distribution_mode = os.environ.get(
    "LEOSAT_DISTRIBUTION_MODE",
    "FastStart",
).strip().lower()

if _distribution_mode not in _SUPPORTED_DISTRIBUTION_MODES:
    supported = ", ".join(sorted(_SUPPORTED_DISTRIBUTION_MODES))
    raise ValueError(
        "LEOSAT_DISTRIBUTION_MODE must be one of "
        f"{supported}; received {_distribution_mode!r}."
    )

is_portable = _distribution_mode == "portable"

is_diagnostic = _build_configuration == "diagnostic"
executable_name = (
    "LEOSatPredictor-diagnostic" if is_diagnostic else "LEOSatPredictor"
)


def _data_file(source: Path, destination: str) -> tuple[str, str]:
    """Return one validated PyInstaller data-file tuple.

    Parameters
    ----------
    source : pathlib.Path
        Required source file.
    destination : str
        Destination directory inside the frozen application.

    Returns
    -------
    tuple of str
        PyInstaller ``(source, destination)`` tuple.

    Raises
    ------
    FileNotFoundError
        If the required source file does not exist.
    """

    if not source.is_file():
        raise FileNotFoundError(
            f"Required GUI distribution resource is missing: {source}"
        )
    return (str(source), destination)


def _data_tree(
    source_root: Path,
    destination_root: str,
) -> list[tuple[str, str]]:
    """Collect a resource tree while preserving relative directories.

    Parameters
    ----------
    source_root : pathlib.Path
        Required source directory.
    destination_root : str
        Root destination directory inside the frozen application.

    Returns
    -------
    list of tuple of str
        PyInstaller data-file tuples.

    Raises
    ------
    FileNotFoundError
        If the required source directory does not exist.
    """

    if not source_root.is_dir():
        raise FileNotFoundError(
            f"Required GUI resource directory is missing: {source_root}"
        )

    collected: list[tuple[str, str]] = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative_parent = source.relative_to(source_root).parent
        destination = Path(destination_root) / relative_parent
        collected.append((str(source), destination.as_posix()))
    return collected


datas = [
    _data_file(ROOT / "config" / "config.json", "config"),
    _data_file(
        ROOT / "gui" / "styles" / "dashboard_dark.qss",
        "gui/styles",
    ),
    _data_file(
        ROOT / "gui" / "styles" / "dashboard_light.qss",
        "gui/styles",
    ),
]
datas.extend(_data_tree(ROOT / "gui" / "map_assets", "gui/map_assets"))
datas.extend(_data_tree(ROOT / "gui" / "assets" / "icons", "gui/assets/icons"))

# Pyorbital loads this package resource when ``pyorbital.tlefile`` is imported.
# PyInstaller does not collect package data automatically.
datas.extend(
    collect_data_files(
        "pyorbital",
        includes=["etc/platforms.txt"],
    )
)

def _scipy_array_api_compat_submodules() -> list[str]:
    """Collect scipy's vendored array-API compat shim, whichever vendor path
    the resolved scipy version uses.

    ``array_api_compat``'s per-backend ``__init__`` modules (numpy, dask,
    torch, ...) load their submodules via a dynamic
    ``__import__(__package__ + ".fft")`` call rather than a static import
    statement, so PyInstaller's Analysis graph cannot discover them on its
    own. scipy also renamed the vendor parent package between releases
    (``scipy._lib.array_api_compat`` before the rename, ``scipy._external``
    after it), and scipy is unpinned in requirements_gui.txt, so this checks
    both known locations against whatever scipy is actually installed in the
    build environment instead of hardcoding one.
    """

    import importlib

    for candidate in ("scipy._external.array_api_compat", "scipy._lib.array_api_compat"):
        try:
            importlib.import_module(candidate)
        except ImportError:
            continue
        return collect_submodules(candidate)

    raise ImportError(
        "Could not locate scipy's array_api_compat vendor package under "
        "scipy._external or scipy._lib; the resolved scipy version may have "
        "moved it again. Update _scipy_array_api_compat_submodules() in this "
        "spec file to match."
    )


# These modules are imported dynamically at runtime.  All ordinary imports are
# left to PyInstaller's Analysis graph and package hooks.
hiddenimports = [
    "PyQt6.QtSvg",
    "PyQt6.QtWebChannel",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "pyorbital.tlefile",
    "src.models.formatter",
    "src.models.location_manager",
    "src.services.tle_service",
    *_scipy_array_api_compat_submodules(),
]

# The frozen desktop product contains only the active PyQt6 GUI path.  Other Qt
# bindings and the Flask/web path are intentionally excluded.
excludes = [
    "Flask",
    "flask",
    "gunicorn",
    "PyQt5",
    "PySide2",
    "PySide6",
    "redis",
    "rq",
    "src.main",
    "src.routes",
    "src.web",
    "waitress",
]

analysis = Analysis(
    [str(ROOT / "scripts" / "run_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

_common_exe_options = dict(
    name=executable_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=is_diagnostic,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    runtime_tmpdir=None,
)

if is_portable:
    # Portable mode embeds all binaries and data in one executable.  The
    # PyInstaller bootloader must extract those files on every launch.
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        **_common_exe_options,
    )
else:
    # FastStart mode keeps native libraries in the distribution folder, which
    # avoids one-file extraction and substantially reduces launch latency.
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        contents_directory="_internal",
        **_common_exe_options,
    )
    collect = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name=executable_name,
    )
