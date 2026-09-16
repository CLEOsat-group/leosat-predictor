"""Compatibility wrapper for the GUI v2 header status surface."""

from __future__ import annotations

from gui_v2.widgets.header_status_widget import HeaderStatusWidget


class StatusEventStrip(HeaderStatusWidget):
    """Backward-compatible alias for the header-integrated status widget.

    The production shell instantiates :class:`HeaderStatusWidget` directly.  This
    class remains temporarily available for older imports and historical Task 43
    verifiers while GUI v2 continues its replacement path.
    """


__all__ = ["StatusEventStrip"]
