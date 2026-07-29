/* Local map page controller for the PyQt WebEngine map dialog.
 *
 * Observatory plotting is JavaScript-owned. Python exposes the canonical
 * observatory catalog through pyBridge.getObservatories(); this file requests
 * it only after Leaflet and the Qt WebChannel bridge are ready.
 */

const mapDialogState = {
    map: null,
    selectedMarker: null,
    observatoryLayer: null,
    observatoriesLoaded: false,
    observatoriesLoading: false,
    pyBridge: null,
    bridgeReadyNotified: false,
};

function isFiniteCoordinate(latitude, longitude) {
    return Number.isFinite(latitude) && Number.isFinite(longitude);
}

function initializeMap() {
    if (mapDialogState.map) {
        return;
    }

    mapDialogState.map = L.map('map').setView([20, 0], 2);
    mapDialogState.observatoryLayer = L.layerGroup().addTo(mapDialogState.map);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        referrerPolicy: 'strict-origin-when-cross-origin',
        maxZoom: 19,
    }).addTo(mapDialogState.map);

    mapDialogState.map.on('click', function (event) {
        setSelectedLocation(event.latlng.lat, event.latlng.lng);
    });
}

function notifyBridgeReady() {
    if (mapDialogState.bridgeReadyNotified || !mapDialogState.pyBridge) {
        return;
    }

    mapDialogState.bridgeReadyNotified = true;
    if (typeof mapDialogState.pyBridge.notifyMapReady === 'function') {
        mapDialogState.pyBridge.notifyMapReady();
    }
}

function initializeBridge() {
    if (mapDialogState.pyBridge) {
        return;
    }

    if (typeof qt === 'undefined' || !qt.webChannelTransport || typeof QWebChannel === 'undefined') {
        console.error('Qt WebChannel is not available for the map dialog.');
        return;
    }

    new QWebChannel(qt.webChannelTransport, function (channel) {
        mapDialogState.pyBridge = channel.objects.pyBridge;
        window.pyBridge = mapDialogState.pyBridge;

        if (!mapDialogState.pyBridge) {
            console.error('pyBridge is not available on the Qt WebChannel.');
            return;
        }

        notifyBridgeReady();
        loadObservatoriesOnce();
    });
}

function clearObservatoryLayer() {
    if (mapDialogState.observatoryLayer) {
        mapDialogState.observatoryLayer.clearLayers();
    }
}

function setSelectedLocation(latitude, longitude) {
    if (!mapDialogState.map || !isFiniteCoordinate(latitude, longitude)) {
        return;
    }

    if (mapDialogState.selectedMarker) {
        mapDialogState.map.removeLayer(mapDialogState.selectedMarker);
    }

    const latLng = L.latLng(latitude, longitude);
    mapDialogState.selectedMarker = L.marker(latLng).addTo(mapDialogState.map);
    mapDialogState.selectedMarker
        .bindPopup(`Lat: ${latitude.toFixed(6)}<br>Lon: ${longitude.toFixed(6)}`)
        .openPopup();

    if (mapDialogState.pyBridge) {
        mapDialogState.pyBridge.setLocation(latitude, longitude);
    }
}

function selectObservatory(observatory, marker, statusElement) {
    if (!mapDialogState.pyBridge || typeof mapDialogState.pyBridge.setObservatory !== 'function') {
        console.error('Cannot select observatory because pyBridge.setObservatory is unavailable.');
        return;
    }

    mapDialogState.pyBridge.setObservatory(String(observatory.id));
    if (statusElement) {
        statusElement.textContent = `Selected: ${observatory.name}`;
    }
    marker.openPopup();
}

function groupObservatories(observatories) {
    const groups = new Map();
    observatories.forEach(function (observatory) {
        const fallbackKey = `${Number(observatory.latitude).toFixed(3)},${Number(observatory.longitude).toFixed(3)}`;
        const key = String(observatory.map_group || fallbackKey);
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key).push(observatory);
    });
    return Array.from(groups.values());
}

function buildObservatoryPopup(observatories, marker) {
    const container = document.createElement('div');
    container.className = 'observatory-site-popup';

    const heading = document.createElement('strong');
    heading.textContent = observatories.length === 1
        ? observatories[0].name
        : `${observatories.length} observatories at this site`;
    container.appendChild(heading);

    const status = document.createElement('div');
    status.className = 'observatory-site-status';

    observatories.forEach(function (observatory) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'observatory-site-choice';
        button.textContent = observatory.name;
        button.title = `Altitude: ${Number(observatory.altitude || 0).toFixed(1)} m`;
        button.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            selectObservatory(observatory, marker, status);
        });
        container.appendChild(button);
    });

    container.appendChild(status);
    return container;
}

window.plotObservatories = function (observatories) {
    if (!mapDialogState.map || !mapDialogState.observatoryLayer) {
        console.error('Map is not initialized.');
        return;
    }

    if (!Array.isArray(observatories)) {
        console.error('Invalid observatory payload:', observatories);
        return;
    }

    clearObservatoryLayer();

    groupObservatories(observatories).forEach(function (siteObservatories) {
        const valid = siteObservatories.filter(function (observatory) {
            const latitude = Number(observatory.latitude);
            const longitude = Number(observatory.longitude);
            return isFiniteCoordinate(latitude, longitude);
        });
        if (valid.length === 0) {
            console.error('Observatory site has no valid coordinates:', siteObservatories);
            return;
        }

        const latitude = valid.reduce((sum, observatory) => sum + Number(observatory.latitude), 0) / valid.length;
        const longitude = valid.reduce((sum, observatory) => sum + Number(observatory.longitude), 0) / valid.length;
        const marker = L.marker([latitude, longitude]).addTo(mapDialogState.observatoryLayer);
        marker.bindPopup(buildObservatoryPopup(valid, marker));

        if (valid.length === 1) {
            marker.on('click', function () {
                selectObservatory(valid[0], marker, null);
            });
        }
    });

    console.log(`Loaded ${observatories.length} observatories into ${groupObservatories(observatories).length} map sites.`);
};

function loadObservatoriesOnce() {
    if (mapDialogState.observatoriesLoaded || mapDialogState.observatoriesLoading) {
        return;
    }

    if (!mapDialogState.pyBridge || typeof mapDialogState.pyBridge.getObservatories !== 'function') {
        console.error('Cannot load observatories because pyBridge.getObservatories is unavailable.');
        return;
    }

    mapDialogState.observatoriesLoading = true;
    mapDialogState.pyBridge.getObservatories().then(function (observatoriesJson) {
        let parsedObservatories;
        try {
            parsedObservatories = JSON.parse(observatoriesJson);
        } catch (error) {
            console.error('Failed to parse observatory JSON:', error);
            mapDialogState.observatoriesLoading = false;
            return;
        }

        if (!Array.isArray(parsedObservatories)) {
            console.error('Observatory payload is not an array:', parsedObservatories);
            mapDialogState.observatoriesLoading = false;
            return;
        }

        window.plotObservatories(parsedObservatories);
        mapDialogState.observatoriesLoaded = true;
        mapDialogState.observatoriesLoading = false;
    }).catch(function (error) {
        console.error('Failed to load observatories from pyBridge:', error);
        mapDialogState.observatoriesLoading = false;
    });
}

function initializeMapDialog() {
    initializeMap();
    initializeBridge();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeMapDialog, { once: true });
} else {
    initializeMapDialog();
}
