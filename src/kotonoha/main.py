from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import tempfile
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from PyQt6.QtCore import QLockFile
    from PyQt6.QtWidgets import QApplication

    from .app.application_controller import AppController

# Guard against accidental PyQt5 import conflicts before importing PyQt6.
cast(dict[str, Any], sys.modules)["PyQt5"] = None
os.environ.setdefault("QT_API", "pyqt6")

logger = logging.getLogger(__name__)


async def _build_app_objects(app: QApplication, cli_port: int | None = None) -> AppController:
    """Build the application graph and return its lifecycle owner."""
    from .app.composition import ApplicationComposition

    composition = await ApplicationComposition.production(app, cli_port=cli_port)
    return composition.build()


def _read_cli_port(app: QApplication) -> int | None:
    """Read the typed CLI override from the Qt application property boundary."""
    value = app.property("cli_port")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


async def _run(app: QApplication) -> None:
    close_event = asyncio.Event()
    app.aboutToQuit.connect(close_event.set)

    controller = await _build_app_objects(app, _read_cli_port(app))
    try:
        await controller.start()
        await close_event.wait()
    finally:
        await controller.stop()


async def _cancel_pending(loop: asyncio.AbstractEventLoop) -> None:
    current = asyncio.current_task(loop=loop)
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _main_task_finished(task: asyncio.Task[None], quit_application: Callable[[], None]) -> None:
    """Report a failed application task and stop the Qt loop instead of hanging."""
    if task.cancelled():
        return
    error = task.exception()
    if error is None:
        return
    logger.error(
        "Kotonoha application task failed: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    quit_application()


def _single_instance_lock(path: str | None = None) -> QLockFile | None:
    """Return a held QLockFile, or None if another Kotonoha instance owns it.

    Prevents the stacked tray icons / duplicate overlays from launching it twice."""
    from PyQt6.QtCore import QLockFile

    if path is None:
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        path = os.path.join(runtime, "kotonoha.lock")
    lock = QLockFile(path)
    lock.setStaleLockTime(30_000)  # reclaim after 30s if a previous instance crashed
    return lock if lock.tryLock(50) else None


def entry_point() -> int:
    parser = argparse.ArgumentParser(description="Kotonoha desktop lyrics overlay")
    parser.add_argument("--port", "-p", type=int, default=None, help="Override WebSocket receiver port")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # qasync logs every thread-pool callback at DEBUG — including the full args, so a
    # cached LyricsArtifact dumps the entire lyric text on each store. Keep -v about
    # Kotonoha's own logs and mute that third-party firehose.
    logging.getLogger("qasync").setLevel(logging.INFO)

    # Single instance: a second launch would just stack another tray icon + overlay.
    instance_lock = _single_instance_lock()  # noqa: F841 - held for the process lifetime
    if instance_lock is None:
        logger.warning("Kotonoha is already running; exiting.")
        return 0

    # Pin the device pixel ratio to 1 so the layer-shell surface's pixel geometry
    # (set_input_rect / set_anchor_position work in physical pixels) matches what we
    # paint. QT_AUTO_SCREEN_SCALE_FACTOR is a dead Qt5 knob under Qt6 — dropped.
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

    import qasync
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from .platform.detect import current_desktop

    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("kotonoha")
    app.setQuitOnLastWindowClosed(False)  # overlay close should not kill the tray
    app.setProperty("xdg_current_desktop", current_desktop())
    app.setProperty("cli_port", args.port)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    main_task = loop.create_task(_run(app))
    main_task.add_done_callback(partial(_main_task_finished, quit_application=app.quit))

    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(_cancel_pending(loop))
        loop.close()
    if main_task.cancelled() or main_task.exception() is not None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(entry_point())
