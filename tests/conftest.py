"""Shared test setup.

Create a single QApplication for the whole session before any test runs. The Qt
GUI tests otherwise create it lazily via module-scoped fixtures, which leaves
QObject (e.g. LyricsState) lifetimes tied to whichever test first spun Qt up and
made the aiohttp receiver tests flaky once enough tests accumulated. One long
lived app keeps those lifetimes stable and deterministic.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _session_qapp():
    app = QApplication.instance() or QApplication([])
    yield app
