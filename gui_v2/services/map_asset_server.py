"""Local HTTP asset server for GUI-v2 map-selection assets.

The GUI-v2 location-map dialog serves its HTML, JavaScript, and CSS from a
loopback HTTP origin instead of ``file://``.  This keeps browser requests in a
normal origin/referrer context for external tile providers while keeping the
server private to the local machine.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Self


class MapAssetRequestHandler(SimpleHTTPRequestHandler):
    """Serve GUI-v2 map assets with a browser-friendly referrer policy."""

    def end_headers(self) -> None:
        """Add local asset headers before completing each response."""
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress per-request HTTP noise in GUI and verifier output."""
        return


class LocalMapAssetServer:
    """Lifecycle wrapper around a loopback threaded asset server.

    Parameters
    ----------
    assets_dir : str or pathlib.Path, optional
        Directory containing ``map.html`` and related static map assets.  When
        omitted, the package-local ``gui_v2/map_assets`` directory is served.
    host : str, default: "127.0.0.1"
        Loopback bind host.  Do not use a public interface for GUI-local assets.
    port : int, default: 0
        Bind port.  The default ``0`` asks the operating system to select an
        available port.
    """

    def __init__(self, assets_dir: str | Path | None = None, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.assets_dir = Path(assets_dir) if assets_dir is not None else Path(__file__).resolve().parents[1] / "map_assets"
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url: str | None = None

    def start(self) -> str:
        """Start the asset server and return its base URL.

        Returns
        -------
        str
            Base URL of the running local server.

        Raises
        ------
        FileNotFoundError
            If the asset directory or ``map.html`` is missing.
        """
        if self._server is not None and self.base_url is not None:
            return self.base_url

        self._validate_assets_dir()
        handler = partial(MapAssetRequestHandler, directory=str(self.assets_dir))
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        host, port = self._server.server_address
        self.base_url = f"http://{host}:{port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="GuiV2MapAssetServer",
            daemon=True,
        )
        self._thread.start()
        return self.base_url

    def stop(self) -> None:
        """Stop the server if running.

        The method is idempotent so callers may safely invoke it from close,
        reject, accept, and destruction paths.
        """
        server = self._server
        thread = self._thread
        if server is None:
            self._thread = None
            self.base_url = None
            return

        self._server = None
        self._thread = None
        self.base_url = None
        server.shutdown()
        server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _validate_assets_dir(self) -> None:
        """Validate that the map asset directory contains the entry page."""
        if not self.assets_dir.is_dir():
            raise FileNotFoundError(f"Map asset directory does not exist: {self.assets_dir}")
        if not (self.assets_dir / "map.html").is_file():
            raise FileNotFoundError(f"Map entry file is missing: {self.assets_dir / 'map.html'}")

    def __enter__(self) -> Self:
        """Start the server when used as a context manager."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop the server when leaving a context manager."""
        self.stop()


__all__ = ("LocalMapAssetServer", "MapAssetRequestHandler")
