"""GUI-v2-native dialog for selecting an observer location from a map.

The dialog owns only GUI-v2 map presentation and selection flow.  It reuses the
shared ``SatelliteProxy`` WebChannel bridge for observatory metadata and
selection state, but it does not call legacy GUI callbacks or mutate prediction
state directly.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDialog, QFrame, QGridLayout, QLabel, QPushButton, QWidget

from src.services.satellite_proxy import SatelliteProxy

from ..services.map_asset_server import LocalMapAssetServer

logger = logging.getLogger(__name__)


class LocationMapDialog(QDialog):
    """Map dialog that emits one normalized-selection candidate.

    Signals
    -------
    locationSelected : pyqtSignal(float, float, float, str)
        Emitted when the user clicks **Apply Selected** after JavaScript has
        reported a real map or observatory selection through ``SatelliteProxy``.
    defaultLocationRequested : pyqtSignal(float, float, float, str)
        Emitted when the user clicks **Set as Default** for the current
        selection.  Only wired when the dialog is opened with
        ``show_set_default=True``.
    """

    locationSelected = pyqtSignal(float, float, float, str)
    defaultLocationRequested = pyqtSignal(float, float, float, str)

    def __init__(self, parent: QWidget | None = None, *, show_set_default: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2LocationMapDialog")
        self.setWindowTitle("Select Location from Map")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(980, 700)

        self._asset_server = LocalMapAssetServer()
        self._map_base_url = self._asset_server.start()
        self._server_stopped = False

        self.map_view = QWebEngineView(self)
        self.map_view.setObjectName("guiV2LocationMapView")
        self.proxy = SatelliteProxy(self.map_view)
        self.channel = QWebChannel(self)
        self.channel.registerObject("pyBridge", self.proxy)
        self.map_view.page().setWebChannel(self.channel)
        self.map_view.loadFinished.connect(self._on_map_load_finished)
        self.proxy.mapReady.connect(self._on_map_ready)
        self.proxy.locationSet.connect(self._on_location_set)

        self.status_label = QLabel("Loading local map assets...", self)
        self.status_label.setObjectName("guiV2CardBody")
        self.status_label.setWordWrap(True)

        self.apply_button = QPushButton("Apply Selected", self)
        self.apply_button.setObjectName("guiV2LocationMapApplyButton")
        self.apply_button.setProperty("buttonRole", "primary")
        self.apply_button.setEnabled(False)
        self.apply_button.setToolTip("Select a map point or observatory before applying.")

        self.set_default_button = QPushButton("Set as Default", self)
        self.set_default_button.setObjectName("guiV2LocationMapSetDefaultButton")
        self.set_default_button.setProperty("buttonRole", "success")
        self.set_default_button.setEnabled(False)
        self.set_default_button.setToolTip("Select a map point or observatory before setting it as your default.")
        self.set_default_button.setVisible(show_set_default)

        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("guiV2LocationMapCloseButton")
        self.close_button.setProperty("buttonRole", "secondary")

        self._build_layout()
        self.apply_button.clicked.connect(self._apply_selected_location)
        self.set_default_button.clicked.connect(self._set_default_selected_location)
        self.close_button.clicked.connect(self.reject)
        self.destroyed.connect(lambda _obj=None: self._stop_asset_server())
        self.map_view.setUrl(QUrl(f"{self._map_base_url}/map.html"))

    def _build_layout(self) -> None:
        """Build the dialog layout without parent-coupled legacy widgets."""
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        title = QLabel("Select Location from Map", self)
        title.setObjectName("guiV2CardTitle")
        layout.addWidget(title, 0, 0, 1, 4)
        layout.addWidget(self.map_view, 1, 0, 1, 4)
        layout.addWidget(self.status_label, 2, 0, 1, 4)

        spacer = QFrame(self)
        spacer.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(spacer, 3, 0)
        layout.addWidget(self.apply_button, 3, 1)
        layout.addWidget(self.set_default_button, 3, 2)
        layout.addWidget(self.close_button, 3, 3)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)
        layout.setColumnStretch(3, 0)
        layout.setRowStretch(1, 1)

    def _on_map_load_finished(self, ok: bool) -> None:
        """Report page-load status without treating it as JavaScript readiness."""
        if ok:
            self.status_label.setText("Map page loaded. Waiting for WebChannel readiness and map selection.")
            logger.info("GUI-v2 location map WebEngine page loaded successfully.")
        else:
            self.status_label.setText(
                "Map page failed to load. Manual location entry remains available in the setup page."
            )
            logger.error("GUI-v2 location map WebEngine page failed to load.")

    def _on_map_ready(self) -> None:
        """Handle JavaScript/WebChannel readiness reported by the map page."""
        self.status_label.setText("Map is ready. Select an observatory marker or click a custom location.")
        logger.info("GUI-v2 location map bridge reported ready.")

    def _on_location_set(self, latitude: float, longitude: float) -> None:
        """Enable application after JavaScript reports a real selection."""
        selected = self._selected_location()
        if selected is None:
            self.apply_button.setEnabled(False)
            self.set_default_button.setEnabled(False)
            self.status_label.setText("Map reported a selection, but no complete location payload is available yet.")
            logger.warning("Map selection signal was emitted without a complete selected_location payload.")
            return

        lat, lon, alt, name = selected
        self.apply_button.setEnabled(True)
        self.set_default_button.setEnabled(True)
        self.status_label.setText(
            f"Selected {name}: latitude {lat:.6f}, longitude {lon:.6f}, altitude {alt:.1f} m."
        )

    def _selected_location(self) -> tuple[float, float, float, str] | None:
        """Return the current proxy selection as a typed tuple, if complete."""
        selected = getattr(self.proxy, "selected_location", None)
        if not selected or len(selected) != 4:
            return None
        latitude, longitude, altitude, name = selected
        try:
            return (float(latitude), float(longitude), float(altitude), str(name))
        except (TypeError, ValueError):
            logger.exception("Invalid selected_location payload from map proxy: %r", selected)
            return None

    def _apply_selected_location(self) -> None:
        """Emit the selected location and close the dialog."""
        selected = self._selected_location()
        if selected is None:
            self.apply_button.setEnabled(False)
            self.set_default_button.setEnabled(False)
            self.status_label.setText("Select a valid map point or observatory before applying.")
            return

        latitude, longitude, altitude, name = selected
        self.locationSelected.emit(latitude, longitude, altitude, name)
        self.accept()

    def _set_default_selected_location(self) -> None:
        """Emit the selected location as a new default and close the dialog."""
        selected = self._selected_location()
        if selected is None:
            self.apply_button.setEnabled(False)
            self.set_default_button.setEnabled(False)
            self.status_label.setText("Select a valid map point or observatory before setting a default.")
            return

        latitude, longitude, altitude, name = selected
        self.defaultLocationRequested.emit(latitude, longitude, altitude, name)
        self.accept()

    def _stop_asset_server(self) -> None:
        """Stop the local asset server exactly once."""
        if self._server_stopped:
            return
        self._server_stopped = True
        self._asset_server.stop()

    def accept(self) -> None:
        """Accept the dialog and release local server resources."""
        self._stop_asset_server()
        super().accept()

    def reject(self) -> None:
        """Reject the dialog and release local server resources."""
        self._stop_asset_server()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Release local server resources when the window is closed."""
        self._stop_asset_server()
        super().closeEvent(event)


__all__ = ("LocationMapDialog",)
