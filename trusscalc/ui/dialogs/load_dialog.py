"""Dialog für Punkt- und Streckenlasten."""
import uuid
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QDoubleSpinBox,
    QDialogButtonBox, QVBoxLayout, QLabel,
)
from trusscalc.core.models import PointLoad, DistributedLoad


class PointLoadDialog(QDialog):
    def __init__(self, position_m: float = 0.0, load: PointLoad = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Punktlast" if load is None else "Punktlast bearbeiten")
        self._load = load
        self._build_ui(position_m if load is None else load.position_m,
                       load.load_kg if load else 100.0)

    def _build_ui(self, position_m: float, load_kg: float) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._pos = QDoubleSpinBox()
        self._pos.setRange(0, 9999)
        self._pos.setDecimals(2)
        self._pos.setSuffix(" m")
        self._pos.setValue(position_m)
        form.addRow("Position:", self._pos)

        self._load_val = QDoubleSpinBox()
        self._load_val.setRange(0.1, 999999)
        self._load_val.setDecimals(1)
        self._load_val.setSuffix(" kg")
        self._load_val.setValue(load_kg)
        form.addRow("Last:", self._load_val)

        layout.addLayout(form)
        layout.addWidget(QLabel("<small><i>Richtung: vertikal nach unten.</i></small>"))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_load(self) -> PointLoad:
        lid = self._load.id if self._load else str(uuid.uuid4())
        return PointLoad(id=lid, position_m=self._pos.value(), load_kg=self._load_val.value())


class DistributedLoadDialog(QDialog):
    def __init__(self, start_m: float = 0.0, end_m: float = 1.0,
                 load: DistributedLoad = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Streckenlast" if load is None else "Streckenlast bearbeiten")
        self._load = load
        s = load.start_m if load else start_m
        e = load.end_m if load else end_m
        q = load.load_kg_per_m if load else 10.0
        self._build_ui(s, e, q)

    def _build_ui(self, start: float, end: float, q: float) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._start = QDoubleSpinBox()
        self._start.setRange(0, 9999); self._start.setDecimals(2); self._start.setSuffix(" m")
        self._start.setValue(start)
        form.addRow("Von:", self._start)

        self._end = QDoubleSpinBox()
        self._end.setRange(0, 9999); self._end.setDecimals(2); self._end.setSuffix(" m")
        self._end.setValue(end)
        form.addRow("Bis:", self._end)

        self._q = QDoubleSpinBox()
        self._q.setRange(0.1, 999999); self._q.setDecimals(2); self._q.setSuffix(" kg/m")
        self._q.setValue(q)
        form.addRow("Last:", self._q)

        layout.addLayout(form)
        layout.addWidget(QLabel("<small><i>Gleichmäßig verteilte Last nach unten.</i></small>"))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_load(self) -> DistributedLoad:
        lid = self._load.id if self._load else str(uuid.uuid4())
        return DistributedLoad(
            id=lid,
            start_m=self._start.value(),
            end_m=self._end.value(),
            load_kg_per_m=self._q.value(),
        )
