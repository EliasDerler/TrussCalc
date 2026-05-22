"""Eigenschaften-Panel für selektierte Truss- und Tower-Elemente."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from trusscalc.core.models import (
    DistributedLoad, PointLoad, Support, TowerAssembly, TrussSection, UnitSystem,
)


class PropertiesPanel(QWidget):
    edit_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(180)
        self.setMaximumWidth(260)
        self._current = None
        self._unit_system = UnitSystem.KG_M
        self._build_ui()

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

        self._btn_edit = QPushButton("Bearbeiten...")
        self._btn_edit.clicked.connect(lambda: self.edit_requested.emit(self._current))
        self._btn_del = QPushButton("Löschen")
        self._btn_del.clicked.connect(lambda: self.delete_requested.emit(self._current))
        self._btn_edit.setEnabled(False)
        self._btn_del.setEnabled(False)
        layout.addWidget(self._btn_edit)
        layout.addWidget(self._btn_del)

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
        elif isinstance(element, dict) and element.get("tower_kind"):
            self._show_tower_element(element)

        self._btn_edit.setEnabled(True)
        self._btn_del.setEnabled(True)

    def show_project_summary(self, project, truss_type=None) -> None:
        self._current = None
        self._clear_inner()
        self._btn_edit.setEnabled(False)
        self._btn_del.setEnabled(False)
        if project is None:
            self._inner_layout.addWidget(QLabel("Kein Projekt aktiv."))
            return

        self._inner_layout.addWidget(QLabel("<b>Stückliste</b>"))
        sec_group = QGroupBox("Traversen")
        sec_form = QFormLayout(sec_group)
        if project.sections:
            lengths = {}
            for section in project.sections:
                lengths[round(section.length_m, 2)] = lengths.get(round(section.length_m, 2), 0) + 1
            type_name = truss_type.display_name if truss_type else "Traverse"
            for length, count in sorted(lengths.items()):
                sec_form.addRow(f"{count}x {length * 100:.0f} cm:", QLabel(type_name))
        else:
            sec_form.addRow(QLabel("Keine Traversenabschnitte"))
        self._inner_layout.addWidget(sec_group)

        sup_group = QGroupBox("Auflager")
        sup_form = QFormLayout(sup_group)
        if project.supports:
            for idx, support in enumerate(sorted(project.supports, key=lambda s: s.position_m), start=1):
                max_force = f", max. {self._force_text(support.max_force_kg)}" if support.has_max_force else ""
                sup_form.addRow(f"Auflager {idx}:", QLabel(f"{support.position_m * 100:.0f} cm{max_force}"))
        else:
            sup_form.addRow(QLabel("Keine Auflager"))
        self._inner_layout.addWidget(sup_group)

        load_group = QGroupBox("Lasten")
        load_form = QFormLayout(load_group)
        if project.point_loads or project.distributed_loads:
            for idx, load in enumerate(sorted(project.point_loads, key=lambda p: p.position_m), start=1):
                load_form.addRow(f"Punktlast {idx}:", QLabel(f"{self._force_text(load.load_kg)} @ {load.position_m * 100:.0f} cm"))
            for idx, load in enumerate(sorted(project.distributed_loads, key=lambda d: d.start_m), start=1):
                load_form.addRow(
                    f"Streckenlast {idx}:",
                    QLabel(f"{self._line_force_text(load.load_kg_per_m)}, {load.start_m * 100:.0f}-{load.end_m * 100:.0f} cm"),
                )
        else:
            load_form.addRow(QLabel("Keine Lasten"))
        self._inner_layout.addWidget(load_group)

    def show_tower_summary(self, assembly: TowerAssembly | None, truss_type=None) -> None:
        self._current = None
        self._clear_inner()
        self._btn_edit.setEnabled(False)
        self._btn_del.setEnabled(False)
        self._inner_layout.addWidget(QLabel("<b>Tower-Stückliste</b>"))
        if assembly is None:
            self._inner_layout.addWidget(QLabel("Kein Tower aktiv."))
            return

        foundation_group = QGroupBox("Fundament")
        foundation_form = QFormLayout(foundation_group)
        if assembly.foundation:
            foundation_form.addRow("Name:", QLabel(assembly.foundation_name or "Projekt-Fundament"))
            foundation_form.addRow(
                "Typ:",
                QLabel("Stahl-Bodenplatte" if assembly.foundation.type == "steel_plate" else "Beton-Sockel"),
            )
            foundation_form.addRow("Breite:", QLabel(f"{assembly.foundation.width_m:.2f} m"))
            foundation_form.addRow("Eigengewicht:", QLabel(self._force_text(assembly.foundation.weight_kg)))
        else:
            foundation_form.addRow(QLabel("Kein Fundament platziert"))
        self._inner_layout.addWidget(foundation_group)

        section_group = QGroupBox("Traversen")
        section_form = QFormLayout(section_group)
        if assembly.sections:
            for idx, section in enumerate(assembly.sections, start=1):
                name = truss_type.display_name if truss_type and truss_type.id == section.truss_type_id else f"Typ {section.truss_type_id}"
                section_form.addRow(f"Abschnitt {idx}:", QLabel(f"{name}, {section.length_m:.2f} m"))
        else:
            section_form.addRow(QLabel("Keine Traversenabschnitte"))
        self._inner_layout.addWidget(section_group)

        cantilever_group = QGroupBox("Auskragungen")
        cantilever_form = QFormLayout(cantilever_group)
        if getattr(assembly, "cantilevers", None):
            for idx, cantilever in enumerate(assembly.cantilevers, start=1):
                side = "links" if cantilever.side == "left" else "rechts"
                name = truss_type.display_name if truss_type and truss_type.id == cantilever.truss_type_id else f"Typ {cantilever.truss_type_id}"
                cantilever_form.addRow(
                    f"Arm {idx}:",
                    QLabel(f"{side}, {cantilever.length_m:.2f} m @ Oberkante {cantilever.height_m:.2f} m, {name}"),
                )
        else:
            cantilever_form.addRow(QLabel("Keine Auskragungen"))
        self._inner_layout.addWidget(cantilever_group)

        load_group = QGroupBox("Lasten")
        load_form = QFormLayout(load_group)
        if assembly.point_loads:
            for idx, load in enumerate(assembly.point_loads, start=1):
                if load.direction == "horizontal":
                    side = "rechts" if load.x_m > 0 else "links"
                    text = f"Fh {load.value:.2f} kN @ {load.height_m:.2f} m, Seite {side}"
                else:
                    text = f"{self._force_text(load.value)} @ {load.height_m:.2f} m, x={load.x_m:.2f} m"
                load_form.addRow(f"Last {idx}:", QLabel(text))
        else:
            load_form.addRow(QLabel("Keine Lasten"))
        self._inner_layout.addWidget(load_group)

    def show_result(self, support, result) -> None:
        pass

    def _show_support(self, support: Support) -> None:
        group = QGroupBox("Auflager")
        form = QFormLayout(group)
        form.addRow("Position:", QLabel(f"{support.position_m * 100:.0f} cm"))
        form.addRow("Max. Kraft:", QLabel(self._force_text(support.max_force_kg) if support.has_max_force else "unbegrenzt"))
        self._inner_layout.addWidget(group)

    def _show_point_load(self, load: PointLoad) -> None:
        group = QGroupBox("Punktlast")
        form = QFormLayout(group)
        form.addRow("Position:", QLabel(f"{load.position_m * 100:.0f} cm"))
        form.addRow("Last:", QLabel(self._force_text(load.load_kg)))
        self._inner_layout.addWidget(group)

    def _show_dist_load(self, load: DistributedLoad) -> None:
        group = QGroupBox("Streckenlast")
        form = QFormLayout(group)
        form.addRow("Von:", QLabel(f"{load.start_m * 100:.0f} cm"))
        form.addRow("Bis:", QLabel(f"{load.end_m * 100:.0f} cm"))
        form.addRow("Last:", QLabel(self._line_force_text(load.load_kg_per_m)))
        form.addRow("Gesamt:", QLabel(self._force_text(load.total_load_kg)))
        self._inner_layout.addWidget(group)

    def _show_section(self, section: TrussSection) -> None:
        group = QGroupBox("Traversenabschnitt")
        form = QFormLayout(group)
        type_name = "-"
        if section.truss_type_id:
            try:
                from trusscalc.database.db_manager import load_truss_type
                truss = load_truss_type(section.truss_type_id)
                if truss:
                    type_name = truss.display_name
            except Exception:
                pass
        label = QLabel(type_name)
        label.setWordWrap(True)
        label.setStyleSheet("color: #88BBFF;")
        form.addRow("Typ:", label)
        form.addRow("Position:", QLabel(f"{section.position_m * 100:.0f} cm"))
        form.addRow("Länge:", QLabel(f"{section.length_m * 100:.0f} cm"))
        self._inner_layout.addWidget(group)

    def _show_tower_element(self, selection: dict) -> None:
        kind = selection.get("tower_kind")
        if kind == "foundation":
            self._show_tower_foundation(selection)
        elif kind == "section":
            self._show_tower_section(selection)
        elif kind == "cantilever":
            self._show_tower_cantilever(selection)
        elif kind == "load":
            self._show_tower_load(selection)

    def _show_tower_foundation(self, selection: dict) -> None:
        foundation = selection.get("foundation")
        connector = selection.get("connector")
        group = QGroupBox("Tower-Fundament")
        form = QFormLayout(group)
        form.addRow("Name:", QLabel(selection.get("name") or "Projekt-Fundament"))
        if foundation:
            form.addRow("Typ:", QLabel("Stahl-Bodenplatte" if foundation.type == "steel_plate" else "Beton-Sockel"))
            form.addRow("Breite:", QLabel(f"{foundation.width_m:.2f} m"))
            form.addRow("Tiefe:", QLabel(f"{foundation.depth_m:.2f} m"))
            form.addRow("Eigengewicht:", QLabel(self._force_text(foundation.weight_kg)))
            form.addRow("Ballast:", QLabel(self._force_text(foundation.ballast_kg)))
            if foundation.type == "concrete_socket":
                form.addRow("Spiel:", QLabel(f"{foundation.clearance_mm:.1f} mm"))
                form.addRow("Einstecktiefe:", QLabel(f"{foundation.insertion_depth_m:.2f} m"))
                if connector:
                    form.addRow("Schrauben:", QLabel(str(connector.bolt_count)))
                    form.addRow("Hebelarm:", QLabel(f"{connector.bolt_lever_arm_m:.2f} m"))
        self._inner_layout.addWidget(group)

    def _show_tower_section(self, selection: dict) -> None:
        section = selection.get("section")
        truss_type = selection.get("truss_type")
        if not section:
            return
        group = QGroupBox("Tower-Traverse")
        form = QFormLayout(group)
        name = truss_type.display_name if truss_type else f"Typ {section.truss_type_id}"
        label = QLabel(name)
        label.setWordWrap(True)
        label.setStyleSheet("color: #88BBFF;")
        form.addRow("Typ:", label)
        form.addRow("Start:", QLabel(f"{section.position_m:.2f} m"))
        form.addRow("Länge:", QLabel(f"{section.length_m:.2f} m"))
        self._inner_layout.addWidget(group)

    def _show_tower_cantilever(self, selection: dict) -> None:
        cantilever = selection.get("cantilever")
        truss_type = selection.get("truss_type")
        if not cantilever:
            return
        group = QGroupBox("Tower-Auskragung")
        form = QFormLayout(group)
        name = truss_type.display_name if truss_type else f"Typ {cantilever.truss_type_id}"
        label = QLabel(name)
        label.setWordWrap(True)
        label.setStyleSheet("color: #88BBFF;")
        form.addRow("Typ:", label)
        form.addRow("Seite:", QLabel("links" if cantilever.side == "left" else "rechts"))
        form.addRow("Höhe Oberkante:", QLabel(f"{cantilever.height_m:.2f} m"))
        form.addRow("Länge:", QLabel(f"{cantilever.length_m:.2f} m"))
        self._inner_layout.addWidget(group)

    def _show_tower_load(self, selection: dict) -> None:
        load = selection.get("load")
        if not load:
            return
        group = QGroupBox("Tower-Last")
        form = QFormLayout(group)
        if load.direction == "horizontal":
            form.addRow("Typ:", QLabel("Horizontalkraft [Fh]"))
            form.addRow("Kraft:", QLabel(f"{load.value:.2f} kN"))
            form.addRow("Seite:", QLabel("rechts" if load.x_m > 0 else "links"))
        else:
            form.addRow("Typ:", QLabel("Vertikallast"))
            form.addRow("Last:", QLabel(self._force_text(load.value)))
            form.addRow("X-Position:", QLabel(f"{load.x_m:.2f} m"))
        form.addRow("Höhe:", QLabel(f"{load.height_m:.2f} m"))
        self._inner_layout.addWidget(group)

    def _clear_inner(self) -> None:
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
