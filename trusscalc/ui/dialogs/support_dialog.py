"""Dialog zum Anlegen/Bearbeiten eines Auflagers."""
import uuid
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QDoubleSpinBox, QCheckBox,
    QDialogButtonBox, QGroupBox, QVBoxLayout, QLabel,
)
from PyQt6.QtCore import Qt
from trusscalc.core.models import Support


class SupportDialog(QDialog):
    def __init__(self, position_m: float = 0.0, support: Support = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auflager" if support is None else "Auflager bearbeiten")
        self._support = support
        self._build_ui(position_m if support is None else support.position_m,
                       support.max_force_kg if support else None)

    def _build_ui(self, position_m: float, max_force: float) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._pos = QDoubleSpinBox()
        self._pos.setRange(0, 9999)
        self._pos.setDecimals(2)
        self._pos.setSuffix(" m")
        self._pos.setValue(position_m)
        form.addRow("Position:", self._pos)

        self._has_max = QCheckBox("Maximale Auflagerkraft begrenzen")
        self._has_max.setChecked(max_force is not None)
        form.addRow("", self._has_max)

        self._max_force = QDoubleSpinBox()
        self._max_force.setRange(0, 999999)
        self._max_force.setDecimals(1)
        self._max_force.setSuffix(" kg")
        self._max_force.setValue(max_force or 0.0)
        self._max_force.setEnabled(max_force is not None)
        form.addRow("Max. Kraft:", self._max_force)

        self._has_max.toggled.connect(self._max_force.setEnabled)

        layout.addLayout(form)
        layout.addWidget(QLabel(
            "<small><i>Auflager nimmt nur vertikale Druckkräfte auf (kein Zug).</i></small>"
        ))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_support(self) -> Support:
        sid = self._support.id if self._support else str(uuid.uuid4())
        max_force = self._max_force.value() if self._has_max.isChecked() else None
        return Support(
            id=sid,
            position_m=self._pos.value(),
            max_force_kg=max_force,
        )
