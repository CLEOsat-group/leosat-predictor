"""Shell components for the GUI replacement path.

The package exposes shell widgets lazily so lightweight services can import
``gui.shell.mode_registry`` without importing PyQt-backed dashboard widgets.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DashboardShell",
    "NavigationNode",
    "NavigationSidebar",
    "build_navigation_tree",
]


def __getattr__(name: str) -> Any:
    """Lazily import shell exports to keep non-visual service imports light."""
    if name == "DashboardShell":
        from gui.shell.dashboard_shell import DashboardShell

        return DashboardShell
    if name in {"NavigationNode", "build_navigation_tree"}:
        from gui.shell.navigation_model import NavigationNode, build_navigation_tree

        exports = {
            "NavigationNode": NavigationNode,
            "build_navigation_tree": build_navigation_tree,
        }
        return exports[name]
    if name == "NavigationSidebar":
        from gui.shell.navigation_sidebar import NavigationSidebar

        return NavigationSidebar
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
