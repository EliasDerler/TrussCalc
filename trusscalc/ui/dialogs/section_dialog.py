"""Dialog zum Hinzufügen eines Traversenabschnitts."""
import uuid
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QDoubleSpinBox,
    QDialogButtonBox, QVBoxLayout, QLabel,
)
from trusscalc.core.models import TrussSection


class SectionDialog(QDialog):
    def __init__(self, next_position_m: float = 0.0, truss_type_id: int = None,
                 parent=None, section: TrussSection | None = None):
        super().__init__(parent)
        self.setWindowTitle("Traversenabschnitt hinzufügen")
        self._truss_type_id = truss_type_id
        self._position_m = next_position_m
        self._section = section
        self._build_ui(next_position_m)

    def _build_ui(self, position_m: float) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Position wird automatisch gesetzt — nur als Info anzeigen
        lbl_pos = QLabel(f"{position_m * 100:.0f} cm (automatisch)")
        lbl_pos.setStyleSheet("color: #888888;")
        form.addRow("Startposition:", lbl_pos)

        self._length = QDoubleSpinBox()
        self._length.setRange(0.1, 99)
        self._length.setDecimals(2)
        self._length.setSuffix(" m")
        self._length.setValue(self._section.length_m if self._section else 3.0)
        self._length.setFocus()
        form.addRow("Länge:", self._length)

        layout.addLayout(form)
        layout.addWidget(QLabel(
            "<small><i>Abschnitte werden lückenlos aneinandergereiht.<br>"
            "Alle Abschnitte müssen vom gleichen Traversentyp sein.</i></small>"
        ))

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_section(self) -> TrussSection:
        return TrussSection(
            id=str(uuid.uuid4()),
            position_m=self._position_m,
            length_m=self._length.value(),
            truss_type_id=self._truss_type_id or 0,
        )
