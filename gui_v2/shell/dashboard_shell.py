"""Professional dashboard shell for GUI v2."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui_v2.shell.navigation_model import NavigationNode, breadcrumb_for_page
from gui_v2.shell.navigation_sidebar import NavigationSidebar
from gui_v2.state import ActivityState, StatusEvent, StatusLevel
from gui_v2.styles.icon_provider import set_themed_icon
from gui_v2.widgets import HeaderStatusWidget, LoadingOverlay, TimeContextWidget

_logger = logging.getLogger(__name__)


class DashboardShell(QWidget):
    """Navigation and stacked workspace container for GUI v2."""

    def __init__(self, nodes: tuple[NavigationNode, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2Shell")
        self._nodes = nodes
        self._page_indexes: dict[str, int] = {}
        self._navigation_compact = False
        self._activities = ActivityState()
        self._deferred_status_event: StatusEvent | None = None
        self._deferred_terminal_event: StatusEvent | None = None

        root = QGridLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(14, 14, 14, 14)
        root.setHorizontalSpacing(0)
        root.setVerticalSpacing(12)

        self._header_context = QLabel("Predictions / Overpass Prediction / Setup & Run", self)
        self._header_context.setObjectName("guiV2ContextLabel")
        self._navigation_toggle = QPushButton("", self)
        self._navigation_toggle.setObjectName("guiV2NavigationToggle")
        self._navigation_toggle.clicked.connect(self.toggle_navigation_compact)
        self._update_navigation_toggle()
        self._time_context_widget = TimeContextWidget(self)
        self._status_event_surface = HeaderStatusWidget(self)

        header = self._build_header()
        root.addWidget(header, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setObjectName("guiV2MainSplitter")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(8)

        self._navigation = NavigationSidebar(nodes, self._splitter)
        self._navigation.pageSelected.connect(self.set_current_page)
        self._splitter.addWidget(self._navigation)

        workspace_frame = QFrame(self._splitter)
        workspace_frame.setObjectName("guiV2Workspace")
        workspace_layout = QGridLayout(workspace_frame)
        workspace_layout.setContentsMargins(14, 14, 14, 14)
        workspace_layout.setHorizontalSpacing(0)
        workspace_layout.setVerticalSpacing(0)

        self._stack = QStackedWidget(workspace_frame)
        self._stack.setObjectName("guiV2WorkspaceStack")
        workspace_layout.addWidget(self._stack, 0, 0)
        workspace_layout.setColumnStretch(0, 1)
        workspace_layout.setRowStretch(0, 1)

        self._loading_overlay = LoadingOverlay(workspace_frame, minimum_visible_ms=0)

        self._splitter.addWidget(workspace_frame)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([300, 1000])

        root.addWidget(self._splitter, 1, 0)
        root.setColumnStretch(0, 1)
        root.setRowStretch(0, 0)
        root.setRowStretch(1, 1)

        self._status_event_surface.set_ready("Ready.", detail="Idle")
        self.start_time_context()

    @property
    def is_navigation_compact(self) -> bool:
        """Return whether the sidebar is currently compact."""
        return self._navigation_compact

    def add_page(self, page_id: str, widget: QWidget) -> None:
        """Add a workspace page for a stable page ID."""
        if page_id in self._page_indexes:
            raise ValueError(f"Duplicate page id: {page_id}")
        self._page_indexes[page_id] = self._stack.addWidget(widget)

    def set_current_page(self, page_id: str) -> None:
        """Show the workspace associated with ``page_id``."""
        if page_id not in self._page_indexes:
            raise KeyError(f"Unknown page id: {page_id}")
        self._stack.setCurrentIndex(self._page_indexes[page_id])
        breadcrumb = self._breadcrumb_for(page_id)
        self._header_context.setText(breadcrumb)
        self._navigation.set_current_page_context(page_id)
        _logger.debug("Page selected: %s", page_id)
        self.set_info_status(
            f"Selected {breadcrumb}.",
            detail="Page selected",
            auto_clear_ms=4000,
        )

    def select_initial_page(self, page_id: str) -> None:
        """Select the initial page after all pages have been registered."""
        self._navigation.select_page(page_id)

    @property
    def active_activity_keys(self) -> tuple[str, ...]:
        """Return active shell activity keys in presentation order."""

        return self._activities.active_task_keys

    def set_status_event(self, event: StatusEvent) -> None:
        """Display or defer a global status event.

        Non-busy events cannot replace the header while a registered activity
        remains active.  The newest deferred event may be shown once the final
        activity ends without an explicit terminal outcome.
        """

        if self._activities.is_busy and event.level is not StatusLevel.BUSY:
            self._defer_status_event(event, terminal=False)
            return
        self._status_event_surface.set_event(event)

    def set_ready_status(self, message: str, *, detail: str = "") -> None:
        """Display a ready-level global status message."""
        self.set_status_event(StatusEvent.ready(message, detail=detail))

    def set_info_status(self, message: str, *, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display an informational global status message."""
        self.set_status_event(StatusEvent.info(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_success_status(self, message: str, *, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display a success-level global status message."""
        self.set_status_event(StatusEvent.success(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_warning_status(self, message: str, *, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display a warning-level global status message."""
        self.set_status_event(StatusEvent.warning(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_error_status(self, message: str, *, detail: str = "") -> None:
        """Display an error-level global status message."""
        self.set_status_event(StatusEvent.error(message, detail=detail))

    def set_busy_status(self, message: str, *, detail: str = "") -> None:
        """Display a busy-level global status message.

        This method remains available for short non-task transitions. Long
        operations must use :meth:`begin_activity` so overlay and header state
        cannot diverge.
        """

        self.set_status_event(StatusEvent.busy(message, detail=detail))

    def begin_activity(
        self,
        task_key: str,
        message: str,
        *,
        detail: str = "",
        overlay_delay_ms: int = 250,
    ) -> None:
        """Start one task-keyed activity on the header and loading overlay."""

        entry = self._activities.begin(task_key, message, detail=detail)
        self._loading_overlay.begin(entry.task_key, entry.message, delay_ms=overlay_delay_ms)
        self._render_current_activity()

    def update_activity(self, task_key: str, message: str, *, detail: str | None = None) -> None:
        """Update one active task without changing overlap accounting."""

        entry = self._activities.update(task_key, message, detail=detail)
        if entry is None:
            _logger.debug("Ignoring update for unknown activity key: %s", task_key)
            return
        self._loading_overlay.update(entry.task_key, entry.message)
        self._render_current_activity()

    def end_activity(self, task_key: str, terminal_event: StatusEvent | None = None) -> None:
        """End one activity and publish its terminal outcome when appropriate."""

        ended = self._activities.end(task_key)
        self._loading_overlay.end(task_key)
        if ended is None:
            _logger.debug("Ignoring duplicate/unknown activity end: %s", task_key)
            return
        if terminal_event is not None:
            self._defer_status_event(terminal_event, terminal=True)
        if self._activities.is_busy:
            self._render_current_activity()
            return

        event = self._deferred_terminal_event or self._deferred_status_event
        self._deferred_terminal_event = None
        self._deferred_status_event = None
        if event is None:
            event = StatusEvent.ready("Ready.", detail="Idle")
        self._status_event_surface.set_event(event)

    def _defer_status_event(self, event: StatusEvent, *, terminal: bool) -> None:
        """Retain deferred ordinary or terminal status by severity.

        Explicit task outcomes are stored separately from page-navigation and
        log-derived messages.  Once the final overlapping task ends, a terminal
        outcome therefore takes precedence over incidental messages emitted
        during the task lifecycle.
        """

        priority = {
            StatusLevel.READY: 0,
            StatusLevel.INFO: 1,
            StatusLevel.SUCCESS: 2,
            StatusLevel.WARNING: 3,
            StatusLevel.ERROR: 4,
            StatusLevel.BUSY: 5,
        }
        attribute = "_deferred_terminal_event" if terminal else "_deferred_status_event"
        current = getattr(self, attribute)
        if current is None or priority[event.level] >= priority[current.level]:
            setattr(self, attribute, event)

    def clear_activities(self) -> None:
        """Clear all activity feedback immediately during shutdown/reset."""

        self._activities.clear()
        self._deferred_status_event = None
        self._deferred_terminal_event = None
        self._loading_overlay.clear()
        self._status_event_surface.set_ready("Ready.", detail="Idle")

    def _render_current_activity(self) -> None:
        """Render the newest active activity as an immediate busy status."""

        current = self._activities.current
        if current is None:
            return
        self._status_event_surface.set_event(
            StatusEvent.busy(current.message, detail=current.detail or "Active task")
        )

    # Compatibility wrappers retained for call sites migrated in this task.
    def begin_loading(self, task_key: str, message: str, *, delay_ms: int = 250) -> None:
        """Begin unified task feedback for a legacy loading call site."""

        self.begin_activity(task_key, message, overlay_delay_ms=delay_ms)

    def update_loading(self, task_key: str, message: str) -> None:
        """Update unified task feedback for a legacy loading call site."""

        self.update_activity(task_key, message)

    def end_loading(self, task_key: str) -> None:
        """End unified task feedback for a legacy loading call site."""

        self.end_activity(task_key)

    def clear_loading(self) -> None:
        """Clear all unified task feedback during reset or shutdown."""

        self.clear_activities()

    def configure_observatory_context(self, location: Mapping[str, Any] | None) -> None:
        """Configure the header OBS field from the loaded/default location."""
        self._time_context_widget.configure_observatory_context(location)

    def start_time_context(self) -> None:
        """Start live GUI-thread time-context updates."""
        self._time_context_widget.start()

    def stop_time_context(self) -> None:
        """Stop live GUI-thread time-context updates."""
        self._time_context_widget.stop()

    def toggle_navigation_compact(self) -> None:
        """Toggle between expanded and compact sidebar modes."""
        self.set_navigation_compact(not self._navigation_compact)

    def set_navigation_compact(self, compact: bool) -> None:
        """Set explicit navigation compact state."""
        self._navigation_compact = bool(compact)
        self._navigation.set_compact(self._navigation_compact)
        if self._navigation_compact:
            self._update_navigation_toggle()
            self._splitter.setSizes([150, max(900, self.width() - 150)])
            self.set_info_status(
                "Navigation collapsed to workflow rail.",
                detail="Expand for full navigation",
                auto_clear_ms=4000,
            )
        else:
            self._update_navigation_toggle()
            self._splitter.setSizes([300, max(900, self.width() - 300)])
            self.set_info_status(
                "Navigation expanded.",
                detail="Full navigation available",
                auto_clear_ms=4000,
            )

    def _update_navigation_toggle(self) -> None:
        """Update the icon and accessibility text for the current nav mode."""

        if self._navigation_compact:
            tooltip = "Expand full navigation"
            icon_name = "menu"
        else:
            tooltip = "Collapse to workflow rail"
            icon_name = "menu_close"
        self._navigation_toggle.setToolTip(tooltip)
        self._navigation_toggle.setAccessibleName(tooltip)
        set_themed_icon(self._navigation_toggle, icon_name, size=18)

    def _build_header(self) -> QFrame:
        """Build the three-area application header.

        The header uses three stable areas:

        1. Left: navigation toggle, product title, and breadcrumb/context.
        2. Center: global status capsule, horizontally stretched.
        3. Right: time context widget.

        The left and right areas keep stable widths so that changes in the
        title, breadcrumb, or time labels do not shift the status capsule.
        """

        header = QFrame(self)
        header.setObjectName("guiV2Header")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(18)

        # ------------------------------------------------------------------
        # Left area: stable title / breadcrumb block
        # ------------------------------------------------------------------
        title_area = QWidget(header)
        title_area.setObjectName("guiV2HeaderTitleArea")
        title_area.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        title_area.setFixedWidth(390)

        title_layout = QHBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(10)

        title_layout.addWidget(
            self._navigation_toggle,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        title_text = QWidget(title_area)
        title_text.setObjectName("guiV2HeaderTitleText")
        title_text.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        title_text_layout = QVBoxLayout(title_text)
        title_text_layout.setContentsMargins(0, 0, 0, 0)
        title_text_layout.setSpacing(2)

        title = QLabel("LEO Satellite Predictor", title_text)
        title.setObjectName("guiV2ProductTitle")
        title.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        title.setMinimumWidth(0)

        self._header_context.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._header_context.setMinimumWidth(0)

        title_text_layout.addWidget(title)
        title_text_layout.addWidget(self._header_context)

        title_layout.addWidget(
            title_text,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )

        # ------------------------------------------------------------------
        # Center area: stretched status capsule
        # ------------------------------------------------------------------
        status_area = QWidget(header)
        status_area.setObjectName("guiV2HeaderStatusArea")
        status_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        status_area.setMinimumWidth(360)

        status_layout = QHBoxLayout(status_area)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)

        self._status_event_surface.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._status_event_surface.setMinimumWidth(360)

        # Important:
        # Do not use AlignCenter here. Horizontal alignment prevents the widget
        # from taking the full available width. Align only vertically.
        status_layout.addWidget(
            self._status_event_surface,
            1,
            Qt.AlignmentFlag.AlignVCenter,
        )

        # ------------------------------------------------------------------
        # Right area: stable time context block
        # ------------------------------------------------------------------
        time_area = QWidget(header)
        time_area.setObjectName("guiV2HeaderTimeArea")
        time_area.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        time_area.setFixedWidth(300)

        time_layout = QHBoxLayout(time_area)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(0)

        # Legacy verifier compatibility token: layout.addWidget(self._time_context_widget)
        time_layout.addWidget(
            self._time_context_widget,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )

        # ------------------------------------------------------------------
        # Three-column header composition
        # ------------------------------------------------------------------
        layout.addWidget(title_area, 0)
        layout.addWidget(status_area, 1)
        layout.addWidget(time_area, 0)

        return header

    def _breadcrumb_for(self, page_id: str) -> str:
        return " / ".join(breadcrumb_for_page(self._nodes, page_id))
