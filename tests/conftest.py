"""Shared test setup.

Create a single QApplication for the whole session before any test runs. The Qt
GUI tests otherwise create it lazily via module-scoped fixtures, which leaves
QObject (e.g. LyricsState) lifetimes tied to whichever test first spun Qt up and
made the aiohttp receiver tests flaky once enough tests accumulated. One long
lived app keeps those lifetimes stable and deterministic.
"""

from __future__ import annotations

import os
from typing import Final

import pytest
from PyQt6.QtWidgets import QApplication

#: Set to "1" to run against the session that is actually there, for the tests that
#: need a live compositor. Anything else — including simply running from a Wayland
#: desktop — gets the offscreen platform.
LIVE_SESSION: Final[bool] = os.environ.get("KOTONOHA_TEST_LIVE_SESSION") == "1"

# These tests assert what an offscreen platform does: that it is not Wayland, that it
# has no blur protocol, that it can set window opacity. An inherited QT_QPA_PLATFORM
# used to win, so running the suite from a Wayland desktop checked four
# settings-dialog assertions against the real compositor while CI, whose environment
# is bare, saw nothing. Overriding unconditionally fixed that and took the live
# lifecycle test with it — it could no longer be asked for at all. So the session is
# forced away unless the caller opts in by name, which an ambient desktop cannot do
# by accident. WAYLAND_DISPLAY goes with the platform name: the blur bridge reads the
# session, not what Qt was told.
#
# Set after the imports, not before: Qt reads QT_QPA_PLATFORM when QApplication is
# constructed, which the fixture below does, not when the module is imported.
if not LIVE_SESSION:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("WAYLAND_DISPLAY", None)


@pytest.fixture(scope="session", autouse=True)
def _session_qapp():
    app = QApplication.instance() or QApplication([])
    yield app



# A module-scoped alias for the session app, kept because the overlay tests ask for
# it by name to make their dependence on Qt explicit at the test signature.
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
