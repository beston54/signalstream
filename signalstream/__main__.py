"""Application entry point for `python -m signalstream`.

Default port: 5001 (not 5000 — macOS AirPlay conflict).
If port in use, tries next 5 sequential ports.
Binds to 127.0.0.1 by default. Warns if overridden.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import webbrowser

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5001
MAX_PORT_ATTEMPTS = 5


def _find_open_port(host: str, start_port: int) -> int:
    """Find an open port starting from start_port, trying up to MAX_PORT_ATTEMPTS."""
    for offset in range(MAX_PORT_ATTEMPTS + 1):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            if offset < MAX_PORT_ATTEMPTS:
                logger.info("Port %d in use, trying %d...", port, port + 1)
            continue
    logger.error(
        "Could not find open port in range %d-%d",
        start_port,
        start_port + MAX_PORT_ATTEMPTS,
    )
    sys.exit(1)


def _open_browser(url: str) -> None:
    """Open browser after a short delay to let the server start."""
    import time
    time.sleep(1.0)
    webbrowser.open(url)


def main() -> None:
    """Run the Signalstream web server."""
    host = os.environ.get("SIGNALSTREAM_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SIGNALSTREAM_PORT", str(DEFAULT_PORT)))
    debug = os.environ.get("SIGNALSTREAM_DEBUG", "0") == "1"

    # Security warning for non-localhost binding
    if host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "WARNING: Binding to %s exposes the server to your network. "
            "Signalstream has no authentication — anyone on your network can access it.",
            host,
        )

    # Find open port
    port = _find_open_port(host, port)

    # Database setup
    from signalstream.db.engine import DatabaseEngine
    from signalstream.db.migrations import MigrationManager

    engine = DatabaseEngine()
    MigrationManager(engine).migrate()

    # Create app
    from signalstream.app import create_app

    app = create_app()

    # Graceful shutdown
    from signalstream.jobs.manager import JobManager

    job_manager = JobManager()

    def shutdown_handler(signum, frame):
        logger.info("Shutting down gracefully...")
        job_manager.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Open browser (only when running locally, not in containers)
    url = f"http://{host}:{port}"
    if host in ("127.0.0.1", "localhost"):
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    logger.info("Signalstream running at %s", url)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
