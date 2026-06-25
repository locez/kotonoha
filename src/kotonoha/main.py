from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Any, cast

# Guard against accidental PyQt5 import conflicts before importing PyQt6.
cast(dict[str, Any], sys.modules)["PyQt5"] = None
os.environ.setdefault("QT_API", "pyqt6")


def _build_app_objects(app, config):
    """Wire state, receiver, overlay and tray together. Returns the controller."""
    from .controller import AppController

    return AppController(app, config)


async def _run(app) -> None:
    from .config import load_config

    close_event = asyncio.Event()
    app.aboutToQuit.connect(close_event.set)

    controller = _build_app_objects(app, load_config())
    await controller.start()
    try:
        await close_event.wait()
    finally:
        await controller.stop()


async def _cancel_pending(loop) -> None:
    current = asyncio.current_task(loop=loop)
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def entry_point() -> int:
    parser = argparse.ArgumentParser(description="Kotonoha desktop lyrics overlay")
    parser.add_argument("--port", "-p", type=int, default=None, help="Override WebSocket receiver port")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ.setdefault("QT_SCALE_FACTOR", "1")

    import qasync
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("kotonoha")
    app.setQuitOnLastWindowClosed(False)  # overlay close should not kill the tray
    app.setProperty("xdg_current_desktop", os.environ.get("XDG_CURRENT_DESKTOP", ""))
    app.setProperty("cli_port", args.port)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    main_task = loop.create_task(_run(app))  # noqa: F841

    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(_cancel_pending(loop))
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(entry_point())
