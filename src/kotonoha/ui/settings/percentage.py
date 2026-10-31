"""A synchronized slider and precise numeric editor for percentage settings."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QSlider, QSpinBox, QWidget


class PercentageControl(QWidget):
    """Own two equivalent editors for one integer percentage in the 0..100 range."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create child editors with Qt-owned lifetime and synchronized values."""
        super().__init__(parent)
        self.slider: QSlider = QSlider(Qt.Orientation.Horizontal, self)
        self.number: QSpinBox = QSpinBox(self)
        self.slider.setRange(0, 100)
        self.slider.setPageStep(10)
        self.slider.setMinimumWidth(96)
        self.number.setRange(0, 100)
        self.number.setSuffix(" %")
        self.number.setFixedWidth(84)
        self.slider.valueChanged.connect(self.number.setValue)
        self.number.valueChanged.connect(self.slider.setValue)
        self.setFocusProxy(self.slider)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.number)

    def configure(self, *, value: int, label: str) -> None:
        """Bind a setting's value and accessible label to both editing methods."""
        self.slider.setAccessibleName(label)
        self.number.setAccessibleName(label)
        self.value = value

    @property
    def value(self) -> int:
        """Read the shared percentage, including live drag and numeric edits."""
        return self.slider.value()

    @value.setter
    def value(self, value: int) -> None:
        """Clamp and synchronize both editors when settings are loaded or reset."""
        self.slider.setValue(value)
