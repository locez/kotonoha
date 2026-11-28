"""Settings dropdowns stay usable after saving and reapplying their theme."""

from __future__ import annotations

from typing import Literal

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QListWidget, QWidget

from kotonoha.config import Config, ThemeMode
from kotonoha.ui.settings.dialog import SettingsDialog


def _click(widget: QWidget, position: QPoint) -> None:
    """Move into a target before clicking so Qt accepts a fresh popup selection."""
    for event_type, button, buttons in (
        (QEvent.Type.MouseMove, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton),
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(
            widget,
            QMouseEvent(
                event_type,
                QPointF(position),
                QPointF(widget.mapToGlobal(position)),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


def _select_popup_row(combo: QComboBox, row: int, qapp: QApplication) -> None:
    """Select an actually visible row by mouse, not by bypassing popup layout."""
    _click(combo, combo.rect().center())
    qapp.processEvents()
    view = combo.view()
    assert view is not None
    viewport = view.viewport()
    assert viewport is not None
    assert view.isVisible()
    assert viewport.height() > 0
    model = view.model()
    assert model is not None
    index = model.index(row, combo.modelColumn())
    assert index.isValid()
    view.scrollTo(index)
    qapp.processEvents()
    row_rect = view.visualRect(index)
    assert not row_rect.isEmpty()
    assert viewport.rect().contains(row_rect.center())
    _click(viewport, row_rect.center())
    qapp.processEvents()
    assert combo.currentIndex() == row
    assert not view.isVisible()


@pytest.mark.parametrize("picker", ["font", "theme"])
@pytest.mark.parametrize(
    "save_button",
    [QDialogButtonBox.StandardButton.Apply, QDialogButtonBox.StandardButton.Ok],
    ids=["apply", "ok-and-reopen"],
)
def test_dropdown_rows_remain_clickable_after_saving(
    qapp: QApplication,
    picker: Literal["font", "theme"],
    save_button: QDialogButtonBox.StandardButton,
) -> None:
    """Repeated saves must not collapse a dropdown left on the same settings page."""
    dialog = SettingsDialog(Config(theme=ThemeMode.LIGHT, frost_window=False, fx_animate=False))
    saved: list[Config] = []
    dialog.applied.connect(saved.append)
    try:
        nav = dialog.findChild(QListWidget, "nav")
        assert nav is not None
        page = 2 if picker == "font" else 0
        nav.setCurrentRow(page)
        combo = dialog.form_widgets.font_family if picker == "font" else dialog.form_widgets.theme_combo
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        button = buttons.button(save_button)
        assert button is not None
        dialog.show()
        qapp.processEvents()
        if combo.count() < 2:
            pytest.skip(f"{picker} picker requires at least 2 entries in this environment")
        first_row = 1
        second_row = 2 if combo.count() > 2 else 0

        for row in (first_row, second_row, first_row):
            _select_popup_row(combo, row, qapp)
            _click(button, button.rect().center())
            qapp.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if picker == "font":
                assert saved[-1].font_family == combo.currentText()
            else:
                assert saved[-1].theme.value == combo.currentData()
            if save_button == QDialogButtonBox.StandardButton.Ok:
                assert not dialog.isVisible()
                dialog.show()
                qapp.processEvents()
            assert nav.currentRow() == page

        _select_popup_row(combo, second_row, qapp)
        assert len(saved) == 3
    finally:
        dialog.close()
