"""Qt WebChannel bridge for the GUI map dialog.

The proxy exposes the shared observatory catalog and selected-location updates
to the local WebEngine map page.  Observatory marker rendering is owned by the
JavaScript side after Leaflet and the WebChannel bridge are ready.
"""

from __future__ import annotations

import json
import logging

from PyQt6.QtCore import QObject, QRect, pyqtProperty, pyqtSignal, pyqtSlot

from src.models.formatter import get_elevation
from src.services.observatory_catalog import build_observatory_catalog

logger = logging.getLogger(__name__)


class SatelliteProxy(QObject):
    """Expose map data and location selection slots to JavaScript.

    Parameters
    ----------
    target_widget : QObject
        WebEngine view used as the proxy target for visibility/enabled
        properties.  The proxy does not execute JavaScript against this widget.
    """

    geometryChanged = pyqtSignal(QRect)
    visibleChanged = pyqtSignal()
    enabledChanged = pyqtSignal()
    locationSet = pyqtSignal(float, float)
    mapReady = pyqtSignal()

    def __init__(self, target_widget):
        super().__init__()
        self._target = target_widget
        self.selected_location = None
        self.observatories: dict[str, dict[str, object]] = {}
        self._map_ready = False

        self.load_observatories()

    @pyqtProperty(bool, notify=visibleChanged)
    def isVisible(self):
        """Return whether the target widget is visible."""
        return self._target.isVisible()

    @isVisible.setter
    def isVisible(self, value):
        if self._target.isVisible() != value:
            self._target.setVisible(value)
            self.visibleChanged.emit()

    @pyqtProperty(bool, notify=enabledChanged)
    def isEnabled(self):
        """Return whether the target widget is enabled."""
        return self._target.isEnabled()

    @isEnabled.setter
    def isEnabled(self, value):
        if self._target.isEnabled() != value:
            self._target.setEnabled(value)
            self.enabledChanged.emit()

    @pyqtProperty(QRect, notify=geometryChanged)
    def geometry(self):
        """Return the target widget geometry."""
        return self._target.geometry()

    @geometry.setter
    def geometry(self, rect):
        if self._target.geometry() != rect:
            self._target.setGeometry(rect)
            self.geometryChanged.emit()

    @pyqtSlot(result=str)
    def getObservatories(self) -> str:
        """Return the canonical observatory catalog as JSON for the map page."""
        return json.dumps(build_observatory_catalog())

    def load_observatories(self) -> None:
        """Cache canonical observatory records by stable identifier."""
        self.observatories.clear()
        for observatory in build_observatory_catalog():
            identifier = str(observatory["id"])
            self.observatories[identifier] = dict(observatory)

    @pyqtSlot()
    def notifyMapReady(self) -> None:
        """Record that JavaScript completed map and WebChannel readiness."""
        if self._map_ready:
            return
        self._map_ready = True
        logger.info("Map WebChannel bridge reported ready.")
        self.mapReady.emit()

    @pyqtSlot(str)
    def setObservatory(self, observatory_id: str) -> None:
        """Select one catalog observatory by stable identifier.

        Parameters
        ----------
        observatory_id : str
            Catalog identifier supplied by the map marker or grouped-site
            chooser.  Identifier-based selection keeps colocated observatories
            distinguishable even when they share the same coordinates.
        """

        observatory = self.observatories.get(str(observatory_id))
        if observatory is None:
            logger.warning("Unknown observatory identifier received from map: %s", observatory_id)
            return

        latitude = float(observatory["latitude"])
        longitude = float(observatory["longitude"])
        altitude = float(observatory.get("altitude", 0.0))
        name = str(observatory["name"])
        self.selected_location = (latitude, longitude, altitude, name)
        logger.info("Selected observatory: %s (%s)", name, observatory_id)
        self.locationSet.emit(latitude, longitude)

    @pyqtSlot(float, float)
    def setLocation(self, lat: float, lon: float) -> None:
        """Receive a custom map coordinate from JavaScript."""
        logger.info("Custom location received from JS: Lat=%s, Lon=%s", lat, lon)
        elevation = get_elevation(lat, lon)
        self.selected_location = (lat, lon, elevation, "Custom Location")
        self.locationSet.emit(lat, lon)

    def applyMapSelection(self, lat, lon, alt, name):
        """Apply the selected map location through the owning main window."""
        logger.info("Location selected: %s, %s, %s, %s", lat, lon, alt, name)
        self.parent().applyMapSelection(lat, lon, alt, name)
