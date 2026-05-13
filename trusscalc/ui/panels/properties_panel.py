"""Eigenschaften-Panel (rechts) für das selektierte Element."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFormLayout, QScrollArea,
    QPushButton, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from trusscalc.core.models import (
    DistributedLoad, PointLoad, Support, TrussSection, UnitSystem,
)


class PropertiesPanel(QWidget):
    edit_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.setMaximumWidth(260)
        self._build_ui()
        self._current = None
        self._unit_system = UnitSystem.KG_M

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system

    def _force_text(self, kg: float) -> str:
        if self._unit_system == UnitSystem.N_M:
            return f"{kg * 9.80665 / 1000:.2f} kN"
        return f"{kg:.1f} kg"

    def _line_force_text(self, kg_per_m: float) -> str:
        if self._unit_system == UnitSystem.N_M:
            return f"{kg_per_m * 9.80665 / 1000:.2f} kN/m"
        return f"{kg_per_m:.1f} kg/m"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel("<b>Eigenschaften</b>"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._inner)
        layout.addWidget(scroll, 1)

        btn_row = QVBoxLayout()
        self._btn_edit = QPushButton("Bearbeiten…")
        self._btn_edit.clicked.connect(lambda: self.edit_requested.emit(self._current))
        self._btn_del = QPushButton("Löschen")
        self._btn_del.clicked.connect(lambda: self.delete_requested.emit(self._current))
        self._btn_edit.setEnabled(False)
        self._btn_del.setEnabled(False)
        btn_row.addWidget(self._btn_edit)
        btn_row.addWidget(self._btn_del)
        layout.addLayout(btn_row)

    def show_element(self, element) -> None:
        self._current = element
        self._clear_inner()

        if element is None:
            self._btn_edit.setEnabled(False)
            self._btn_del.setEnabled(False)
            return

        if isinstance(element, Support):
            self._show_support(element)
        elif isinstance(element, PointLoad):
            self._show_point_load(element)
        elif isinstance(element, DistributedLoad):
            self._show_dist_load(element)
        elif isinstance(element, TrussSection):
            self._show_section(element)

        self._btn_edit.setEnabled(element is not None)
        self._btn_del.setEnabled(element is not None)

    def show_project_summary(self, project, truss_type=None) -> None:
        self._current = None
        self._clear_inner()
        self._btn_edit.setEnabled(False)
        self._btn_del.setEnabled(False)

        if project is None:
            self._inner_layout.addWidget(QLabel("Kein Projekt aktiv."))
            return

        title = QLabel("<b>Stückliste</b>")
        self._inner_layout.addWidget(title)

        sec_group = QGroupBox("Traversen")
        sec_form = QFormLayout(sec_group)
        if project.sections:
            lengths = {}
            for section in project.sections:
                lengths[round(section.length_m, 2)] = lengths.get(round(section.length_m, 2), 0) + 1
            type_name = truss_type.display_name if truss_type else "Traverse"
            for length, count in sorted(lengths.items()):
                sec_form.addRow(
                    f"{count}× {length * 100:.0f} cm:",
                    QLabel(type_name),
                )
        else:
            sec_form.addRow(QLabel("Keine Traversenabschnitte"))
        self._inner_layout.addWidget(sec_group)

        sup_group = QGroupBox("Auflager")
        sup_form = QFormLayout(sup_group)
        if project.supports:
            for i, support in enumerate(sorted(project.supports, key=lambda s: s.position_m), start=1):
                max_force = (
                    f", max. {self._force_text(support.max_force_kg)}"
                    if support.has_max_force else ""
                )
                sup_form.addRow(
                    f"Auflager {i}:",
                    QLabel(f"{support.position_m * 100:.0f} cm{max_force}"),
                )
        else:
            sup_form.addRow(QLabel("Keine Auflager"))
        self._inner_layout.addWidget(sup_group)

        load_group = QGroupBox("Lasten")
        load_form = QFormLayout(load_group)
        if project.point_loads or project.distributed_loads:
            for i, load in enumerate(sorted(project.point_loads, key=lambda p: p.position_m), start=1):
                load_form.addRow(
                    f"Punktlast {i}:",
                    QLabel(f"{self._force_text(load.load_kg)} @ {load.position_m * 100:.0f} cm"),
                )
            for i, load in enumerate(sorted(project.distributed_loads, key=lambda d: d.start_m), start=1):
                load_form.addRow(
                    f"Streckenlast {i}:",
                    QLabel(
                        f"{self._line_force_text(load.load_kg_per_m)}, "
                        f"{load.start_m * 100:.0f}-{load.end_m * 100:.0f} cm"
                    ),
                )
        else:
            load_form.addRow(QLabel("Keine Lasten"))
        self._inner_layout.addWidget(load_group)

    def show_result(self, support, result) -> None:
        """Zeigt Berechnungsergebnis für ein Auflager."""
        pass  # Wird in Phase 7 erweitert

    def _show_support(self, s: Support) -> None:
        group = QGroupBox("Auflager")
        form = QFormLayout(group)
        form.addRow("Position:", QLabel(f"{s.position_m*100:.0f} cm"))
        max_f = self._force_text(s.max_force_kg) if s.has_max_force else "unbegrenzt"
        form.addRow("Max. Kraft:", QLabel(max_f))
        self._inner_layout.addWidget(group)

    def _show_point_load(self, p: PointLoad) -> None:
        group = QGroupBox("Punktlast")
        form = QFormLayout(group)
        form.addRow("Position:", QLabel(f"{p.position_m*100:.0f} cm"))
        form.addRow("Last:", QLabel(self._force_text(p.load_kg)))
        self._inner_layout.addWidget(group)

    def _show_dist_load(self, d: DistributedLoad) -> None:
        group = QGroupBox("Streckenlast")
        form = QFormLayout(group)
        form.addRow("Von:", QLabel(f"{d.start_m*100:.0f} cm"))
        form.addRow("Bis:", QLabel(f"{d.end_m*100:.0f} cm"))
        form.addRow("Last:", QLabel(self._line_force_text(d.load_kg_per_m)))
        form.addRow("Gesamt:", QLabel(self._force_text(d.total_load_kg)))
        self._inner_layout.addWidget(group)

    def _show_section(self, s: TrussSection) -> None:
        group = QGroupBox("Traversenabschnitt")
        form = QFormLayout(group)
        # Traversentyp-Name aus DB laden
        type_name = "—"
        if s.truss_type_id:
            try:
                from trusscalc.database.db_manager import load_truss_type
                t = load_truss_type(s.truss_type_id)
                if t:
                    type_name = t.display_name
            except Exception:
                pass
        type_label = QLabel(type_name)
        type_label.setWordWrap(True)
        type_label.setStyleSheet("color: #88BBFF;")
        form.addRow("Typ:", type_label)
        form.addRow("Position:", QLabel(f"{s.position_m*100:.0f} cm"))
        form.addRow("Länge:", QLabel(f"{s.length_m*100:.0f} cm"))
        self._inner_layout.addWidget(group)

    def _clear_inner(self) -> None:
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
