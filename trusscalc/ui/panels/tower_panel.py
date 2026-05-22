"""Zeichnungsbasierter Editor für freistehende Einzeltower."""
from __future__ import annotations

import copy
import uuid

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractSpinBox, QButtonGroup, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QVBoxLayout, QWidget, QGroupBox,
)

from trusscalc.core.models import (
    TowerAssembly, TowerAssemblyCantilever, TowerAssemblyLoad, TowerAssemblySection, TowerConnector,
    TowerFoundationPreset, TowerInput, TowerResult, TrussType,
)
from trusscalc.core.tower_assembly import (
    assembly_from_tower_input, cantilever_deflections_mm, refresh_section_positions,
    tower_input_from_assembly,
)

_OFFSCREEN_APP: QApplication | None = None


def render_tower_schema_png_bytes(
    assembly: TowerAssembly,
    result: TowerResult | None,
    truss_type: TrussType | None = None,
    width_px: int = 820,
    height_px: int = 480,
    render_scale: int = 2,
) -> bytes:
    """Rendert die Tower-Canvas für PDF/Exports als PNG.

    Die PDF-Ausgabe nutzt damit denselben Zeichenpfad wie die interaktive
    Tower-Ansicht. Das verhindert abweichende Label-Layouts zwischen UI und PDF.
    """
    global _OFFSCREEN_APP
    app = QApplication.instance()
    if app is None:
        _OFFSCREEN_APP = QApplication([])

    truss_lookup = {truss_type.id: truss_type} if truss_type and truss_type.id else {}
    canvas = _TowerAssemblyCanvas()
    canvas.resize(max(width_px, 600), max(height_px, 420))
    canvas.set_state(assembly, result, truss_lookup)

    scale = max(1, int(render_scale))
    image = QImage(canvas.width() * scale, canvas.height() * scale, QImage.Format.Format_ARGB32)
    image.fill(QColor("#252525"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    canvas.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class TowerPanel(QWidget):
    changed = pyqtSignal()
    calculate_requested = pyqtSignal()
    foundation_place_requested = pyqtSignal()
    element_selected = pyqtSignal(object)
    element_delete_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._assembly = TowerAssembly()
        self._result: TowerResult | None = None
        self._truss_type: TrussType | None = None
        self._truss_lookup: dict[int, TrussType] = {}
        self._last_input = TowerInput()
        self._build_ui()

    def set_tower(
        self,
        data: TowerInput,
        result: TowerResult | None,
        truss_type: TrussType | None = None,
        assembly: TowerAssembly | None = None,
    ) -> None:
        self._loading = True
        self._truss_type = truss_type
        if truss_type and truss_type.id:
            self._truss_lookup[truss_type.id] = truss_type
        self._assembly = copy.deepcopy(assembly) if assembly else assembly_from_tower_input(data)
        self._result = result
        self._last_input = copy.deepcopy(data)
        self._refresh_labels()
        self._canvas.set_state(self._assembly, self._result, self._truss_lookup)
        self._loading = False
        self.show_result(result)

    def tower_assembly(self) -> TowerAssembly:
        refresh_section_positions(self._assembly)
        return copy.deepcopy(self._assembly)

    def tower_input(self) -> TowerInput:
        data, errors = tower_input_from_assembly(self._assembly, self._truss_type)
        if errors:
            return copy.deepcopy(self._last_input)
        self._last_input = copy.deepcopy(data)
        return data

    def validated_tower_input(
        self,
        parent=None,
        ask_settings: bool = True,
        truss_type: TrussType | None = None,
    ) -> tuple[TowerInput | None, list[str]]:
        data, errors = tower_input_from_assembly(self._assembly, truss_type or self._truss_type)
        if errors:
            return None, errors
        if ask_settings:
            dlg = _TowerCalculationDialog(data, parent or self)
            if not dlg.exec():
                return None, ["Berechnung abgebrochen."]
            data = dlg.get_input()
            self._assembly.gamma = data.gamma
            if self._assembly.foundation:
                self._assembly.foundation = copy.deepcopy(data.foundation)
            self._assembly.connector = copy.deepcopy(data.connector)
        self._last_input = copy.deepcopy(data)
        return data, []

    def set_truss_type(self, truss_type: TrussType) -> TowerInput:
        self._truss_type = truss_type
        if truss_type.id:
            self._truss_lookup[truss_type.id] = truss_type
            self._last_input.truss_type_id = truss_type.id
        self._refresh_labels()
        self._canvas.set_state(self._assembly, self._result, self._truss_lookup)
        return self.tower_input()

    def set_foundation(self, preset: TowerFoundationPreset) -> None:
        self._assembly.foundation_name = preset.name
        self._assembly.foundation_source_id = preset.id
        self._assembly.foundation = copy.deepcopy(preset.foundation)
        self._assembly.connector = copy.deepcopy(preset.connector)
        self._result = None
        self._refresh_labels()
        self._emit_changed()

    def show_result(self, result: TowerResult | None) -> None:
        self._result = result
        self._canvas.set_state(self._assembly, self._result, self._truss_lookup)
        if result is None:
            self._status.setText("Nicht berechnet")
            self._status.setStyleSheet("color: #AAAAAA; font-weight: bold;")
            self._result_text.setText("Tower zeichnen und F5 oder Berechnen drücken.")
            return
        color = {
            "green": "#1FB386",
            "yellow": "#F0A500",
            "red": "#E74C3C",
        }.get(result.status, "#AAAAAA")
        label = {
            "green": "OK",
            "yellow": "Prüfen",
            "red": "Kritisch",
        }.get(result.status, result.status)
        self._status.setText(label)
        self._status.setStyleSheet(f"color: {color}; font-weight: bold;")
        ballast = (
            "nicht bestimmbar"
            if result.required_ballast_kg == float("inf")
            else f"{result.required_ballast_kg:.1f} kg"
        )
        warnings = "\n".join(
            f"- {warning}" for warning in result.warnings
            if "Vorbemessung" not in warning and "Standsicherheitsnachweis" not in warning
        )
        warning_text = f"\n\n{warnings}" if warnings else ""
        self._result_text.setText(
            f"• Bemessungsmoment [MEd]: {result.design_moment_knm:.2f} kNm\n"
            f"• Standmoment: {result.resisting_moment_knm:.2f} kNm\n"
            f"• Kippauslastung: {result.tipping_utilization * 100:.0f} %\n"
            f"• Max. Horizontalkraft [Fh,max]: {result.max_horizontal_force_kn:.2f} kN\n"
            f"• Zusätzlicher Ballastbedarf: {ballast}\n"
            f"• Kantenkraft [Fk]: {result.edge_force_kn * 1000.0:.0f} N\n"
            f"• Basis-Druckkraft [Rz]: {result.base_compression_kg * 9.80665 / 1000.0:.2f} kN\n"
            f"• Biegung Tower: {result.bending_deflection_mm:.1f} mm\n"
            f"• Biegung Auskragung: {result.cantilever_deflection_mm:.1f} mm\n"
            f"• Gesamt-Kopfversatz: {result.total_top_displacement_mm:.1f} mm"
            f"{warning_text}"
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Tower-Editor</b>"))
        self._foundation_label = QLabel("Kein Fundament")
        self._truss_label = QLabel("Kein Traversentyp")
        self._status = QLabel("Nicht berechnet")
        header.addWidget(QLabel("Fundament:"))
        header.addWidget(self._foundation_label, 1)
        header.addWidget(QLabel("Traverse:"))
        header.addWidget(self._truss_label, 1)
        header.addWidget(QLabel("Status:"))
        header.addWidget(self._status)
        root.addLayout(header)

        self._tool_buttons: dict[str, QPushButton] = {}
        self._tools_widget = QWidget()
        tools = QHBoxLayout(self._tools_widget)
        tools.setContentsMargins(0, 0, 0, 0)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for label, tool in [
            ("Auswahl", "select"),
            ("Fundament", "foundation"),
            ("Traverse", "section"),
            ("Auskragung", "cantilever"),
            ("Horizontalkraft", "horizontal"),
            ("Punktlast", "vertical"),
            ("Löschen", "delete"),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked, t=tool: self._set_tool(t))
            self._tool_group.addButton(button)
            self._tool_buttons[tool] = button
            tools.addWidget(button)
            if tool == "select":
                button.setChecked(True)
        tools.addStretch(1)
        calc = QPushButton("Berechnen [F5]")
        calc.clicked.connect(self.calculate_requested)
        tools.addWidget(calc)
        self._tools_widget.setVisible(False)
        root.addWidget(self._tools_widget)

        body = QHBoxLayout()
        self._canvas = _TowerAssemblyCanvas()
        self._canvas.set_tool("select")
        self._canvas.foundation_place_requested.connect(self.foundation_place_requested)
        self._canvas.add_section_requested.connect(self._add_section)
        self._canvas.add_cantilever_requested.connect(self._add_cantilever)
        self._canvas.add_horizontal_load_requested.connect(self._add_horizontal_load)
        self._canvas.add_vertical_load_requested.connect(self._add_vertical_load)
        self._canvas.delete_requested.connect(self._on_canvas_delete_requested)
        self._canvas.edit_requested.connect(self._edit_element)
        self._canvas.selection_changed.connect(self._on_canvas_selection)
        self._canvas.message_requested.connect(self._show_message)
        body.addWidget(self._canvas, 3)

        result_group = QGroupBox("Ergebnis")
        result_layout = QVBoxLayout(result_group)
        self._result_text = QLabel("Tower zeichnen und F5 oder Berechnen drücken.")
        self._result_text.setWordWrap(True)
        self._result_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._result_text.setStyleSheet("font-size: 13px; line-height: 150%;")
        result_layout.addWidget(self._result_text)
        body.addWidget(result_group, 2)
        root.addLayout(body, 1)

    def _set_tool(self, tool: str) -> None:
        self.set_tool(tool)
        if tool == "foundation":
            self._show_message("Fundament per Doppelklick aus der Fundamentbibliothek platzieren.")
        elif tool == "section":
            self._show_message("Klick in die Tower-Ansicht: Traversenabschnitt anfügen.")
        elif tool == "cantilever":
            self._show_message("Links oder rechts vom Tower klicken: horizontale Auskragung einfügen.")

    def set_tool(self, tool: str) -> None:
        if tool not in self._tool_buttons:
            tool = "select"
        self._tool_buttons[tool].setChecked(True)
        self._canvas.set_tool(tool)

    def _refresh_labels(self) -> None:
        self._foundation_label.setText(self._assembly.foundation_name or "Kein Fundament")
        self._truss_label.setText(
            self._truss_type.display_name if self._truss_type else "Kein Traversentyp"
        )

    def _add_section(self, height_m: float) -> None:
        if self._assembly.foundation is None:
            QMessageBox.warning(self, "Tower", "Bitte zuerst ein Fundament platzieren.")
            return
        if not self._truss_type or not self._truss_type.id:
            QMessageBox.warning(self, "Tower", "Bitte zuerst einen Traversentyp doppelklicken.")
            return
        from trusscalc.ui.dialogs.section_dialog import SectionDialog
        refresh_section_positions(self._assembly)
        dlg = SectionDialog(self._assembly.height_m, self._truss_type.id, self)
        if dlg.exec():
            section = dlg.get_section()
            self._assembly.sections.append(
                TowerAssemblySection(
                    id=section.id or str(uuid.uuid4()),
                    length_m=section.length_m,
                    position_m=self._assembly.height_m,
                    truss_type_id=self._truss_type.id or 0,
                )
            )
            refresh_section_positions(self._assembly)
            self._emit_changed()

    def _add_horizontal_load(self, x_m: float, height_m: float) -> None:
        if self._assembly.height_m <= 0:
            QMessageBox.warning(self, "Tower", "Bitte zuerst eine Traverse anlegen.")
            return
        dlg = _TowerPointLoadDialog("horizontal", height_m, parent=self, default_x_m=x_m)
        if dlg.exec():
            self._assembly.point_loads.append(dlg.get_load())
            self._emit_changed()

    def _add_vertical_load(self, x_m: float, height_m: float) -> None:
        if self._assembly.height_m <= 0:
            QMessageBox.warning(self, "Tower", "Bitte zuerst eine Traverse anlegen.")
            return
        dlg = _TowerPointLoadDialog("vertical", height_m, parent=self, default_x_m=x_m)
        if dlg.exec():
            self._assembly.point_loads.append(dlg.get_load())
            self._emit_changed()

    def _add_cantilever(self, side: str, height_m: float) -> None:
        if self._assembly.foundation is None:
            QMessageBox.warning(self, "Tower", "Bitte zuerst ein Fundament platzieren.")
            return
        if self._assembly.height_m <= 0:
            QMessageBox.warning(self, "Tower", "Bitte zuerst eine vertikale Traverse anlegen.")
            return
        if not self._truss_type or not self._truss_type.id:
            QMessageBox.warning(self, "Tower", "Bitte zuerst einen Traversentyp doppelklicken.")
            return
        height_m = max(0.0, min(height_m, self._assembly.height_m))
        dlg = _TowerCantileverDialog(side, height_m, self._truss_type, self)
        if dlg.exec():
            self._assembly.cantilevers.append(dlg.get_cantilever())
            self._emit_changed()

    def _edit_element(self, kind: str, element_id: str) -> None:
        if kind == "foundation" and self._assembly.foundation:
            from trusscalc.ui.dialogs.foundation_dialog import FoundationDialog
            preset = TowerFoundationPreset(
                name=self._assembly.foundation_name or "Projekt-Fundament",
                foundation=copy.deepcopy(self._assembly.foundation),
                connector=copy.deepcopy(self._assembly.connector),
            )
            dlg = FoundationDialog(preset, self)
            if dlg.exec():
                updated = dlg.get_preset()
                self._assembly.foundation_name = updated.name
                self._assembly.foundation = updated.foundation
                self._assembly.connector = updated.connector
                self._emit_changed()
            return
        if kind == "section":
            section = self._find_section(element_id)
            if not section:
                return
            from trusscalc.ui.dialogs.section_dialog import SectionDialog
            dlg = SectionDialog(section.position_m, section.truss_type_id, self, section=section)
            if dlg.exec():
                updated = dlg.get_section()
                section.length_m = updated.length_m
                refresh_section_positions(self._assembly)
                self._emit_changed()
            return
        if kind == "load":
            load = self._find_load(element_id)
            if not load:
                return
            dlg = _TowerPointLoadDialog(load.direction, load.height_m, load, self)
            if dlg.exec():
                updated = dlg.get_load()
                load.height_m = updated.height_m
                load.value = updated.value
                load.eccentricity_m = updated.eccentricity_m
                load.x_m = updated.x_m
                self._emit_changed()
            return
        if kind == "cantilever":
            cantilever = self._find_cantilever(element_id)
            if not cantilever:
                return
            truss = self._truss_lookup.get(cantilever.truss_type_id) or self._truss_type
            dlg = _TowerCantileverDialog(cantilever.side, cantilever.height_m, truss, self, cantilever)
            if dlg.exec():
                updated = dlg.get_cantilever()
                cantilever.height_m = max(0.0, min(updated.height_m, self._assembly.height_m))
                cantilever.length_m = updated.length_m
                cantilever.side = updated.side
                cantilever.truss_type_id = updated.truss_type_id
                self._emit_changed()

    def _delete_element(self, kind: str, element_id: str) -> None:
        if kind == "foundation":
            self._canvas.clear_selection()
            self._assembly.foundation = None
            self._assembly.foundation_name = ""
            self._assembly.foundation_source_id = None
            self._assembly.sections.clear()
            self._assembly.cantilevers.clear()
            self._assembly.point_loads.clear()
            self._emit_changed()
            return
        if kind == "section":
            if self._canvas.selected_ref() == (kind, element_id):
                self._canvas.clear_selection()
            self._assembly.sections = [
                section for section in self._assembly.sections if section.id != element_id
            ]
            refresh_section_positions(self._assembly)
            self._emit_changed()
            return
        if kind == "cantilever":
            if self._canvas.selected_ref() == (kind, element_id):
                self._canvas.clear_selection()
            self._assembly.cantilevers = [
                cantilever for cantilever in self._assembly.cantilevers if cantilever.id != element_id
            ]
            self._emit_changed()
            return
        if kind == "load":
            if self._canvas.selected_ref() == (kind, element_id):
                self._canvas.clear_selection()
            self._assembly.point_loads = [
                load for load in self._assembly.point_loads if load.id != element_id
            ]
            self._emit_changed()

    def edit_selection_ref(self, selection: dict) -> None:
        self._edit_element(selection.get("tower_kind", ""), selection.get("id", ""))

    def delete_selection_ref(self, selection: dict) -> None:
        self._delete_element(selection.get("tower_kind", ""), selection.get("id", ""))

    def selected_element(self) -> dict | None:
        return self._selection_payload(self._canvas.selected_ref())

    def _on_canvas_selection(self, hit) -> None:
        self.element_selected.emit(self._selection_payload(hit))

    def _on_canvas_delete_requested(self, kind: str, element_id: str) -> None:
        self.element_delete_requested.emit(self._selection_payload((kind, element_id)))

    def _selection_payload(self, hit) -> dict | None:
        if not hit:
            return None
        kind, element_id = hit
        if kind == "foundation" and self._assembly.foundation:
            return {
                "tower_kind": "foundation",
                "id": "foundation",
                "name": self._assembly.foundation_name,
                "foundation": copy.deepcopy(self._assembly.foundation),
                "connector": copy.deepcopy(self._assembly.connector),
            }
        if kind == "section":
            section = self._find_section(element_id)
            if section:
                return {
                    "tower_kind": "section",
                    "id": element_id,
                    "section": copy.deepcopy(section),
                    "truss_type": self._truss_lookup.get(section.truss_type_id),
                }
        if kind == "cantilever":
            cantilever = self._find_cantilever(element_id)
            if cantilever:
                return {
                    "tower_kind": "cantilever",
                    "id": element_id,
                    "cantilever": copy.deepcopy(cantilever),
                    "truss_type": self._truss_lookup.get(cantilever.truss_type_id),
                }
        if kind == "load":
            load = self._find_load(element_id)
            if load:
                return {
                    "tower_kind": "load",
                    "id": element_id,
                    "load": copy.deepcopy(load),
                }
        return None

    def _find_section(self, element_id: str) -> TowerAssemblySection | None:
        for section in self._assembly.sections:
            if section.id == element_id:
                return section
        return None

    def _find_load(self, element_id: str) -> TowerAssemblyLoad | None:
        for load in self._assembly.point_loads:
            if load.id == element_id:
                return load
        return None

    def _find_cantilever(self, element_id: str) -> TowerAssemblyCantilever | None:
        for cantilever in self._assembly.cantilevers:
            if cantilever.id == element_id:
                return cantilever
        return None

    def _emit_changed(self) -> None:
        if self._loading:
            return
        self._result = None
        self._refresh_labels()
        self._canvas.set_state(self._assembly, None, self._truss_lookup)
        self.changed.emit()

    def _show_message(self, text: str) -> None:
        self._result_text.setText(text)


class _TowerCantileverDialog(QDialog):
    def __init__(
        self,
        side: str,
        height_m: float,
        truss_type: TrussType | None,
        parent=None,
        cantilever: TowerAssemblyCantilever | None = None,
    ):
        super().__init__(parent)
        self._truss_type = truss_type
        self._cantilever = cantilever
        self._side_value = cantilever.side if cantilever else side
        self.setWindowTitle("Auskragung")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._height = self._spin(0.0, 1000.0, cantilever.height_m if cantilever else height_m, " m")
        self._length = self._spin(0.01, 1000.0, cantilever.length_m if cantilever else 1.0, " m")
        side_label = "links" if self._side_value == "left" else "rechts"
        form.addRow("Seite:", QLabel(side_label))
        form.addRow("Höhe Oberkante:", self._height)
        form.addRow("Länge:", self._length)
        form.addRow("Traversentyp:", QLabel(truss_type.display_name if truss_type else "Kein Traversentyp"))
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def get_cantilever(self) -> TowerAssemblyCantilever:
        return TowerAssemblyCantilever(
            id=self._cantilever.id if self._cantilever else str(uuid.uuid4()),
            height_m=self._height.value(),
            side=self._side_value,
            length_m=self._length.value(),
            truss_type_id=self._truss_type.id if self._truss_type and self._truss_type.id else (
                self._cantilever.truss_type_id if self._cantilever else 0
            ),
        )


class _TowerPointLoadDialog(QDialog):
    def __init__(self, direction: str, height_m: float,
                 load: TowerAssemblyLoad | None = None, parent=None,
                 default_x_m: float = 0.0):
        super().__init__(parent)
        self._direction = direction
        self._load = load
        self.setWindowTitle("Horizontalkraft" if direction == "horizontal" else "Vertikallast")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._height = self._spin(0.0, 1000.0, load.height_m if load else height_m, " m")
        if direction == "horizontal":
            self._value = self._spin(0.0, 10000.0, load.value if load else 1.0, " kN")
            self._x = self._spin(-50.0, 50.0, load.x_m if load else default_x_m, " m")
            form.addRow("Höhe [hF]:", self._height)
            form.addRow("Horizontalkraft [Fh]:", self._value)
            form.addRow("Angriffsseite X:", self._x)
            self._ecc = None
        else:
            self._value = self._spin(0.0, 100000.0, load.value if load else 100.0, " kg")
            x_value = load.x_m if load else default_x_m
            self._ecc = self._spin(-50.0, 50.0, x_value, " m")
            self._x = self._ecc
            form.addRow("Höhe:", self._height)
            form.addRow("Zuladung:", self._value)
            form.addRow("X-Position:", self._ecc)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def get_load(self) -> TowerAssemblyLoad:
        return TowerAssemblyLoad(
            id=self._load.id if self._load else str(uuid.uuid4()),
            direction=self._direction,
            height_m=self._height.value(),
            value=self._value.value(),
            eccentricity_m=self._ecc.value() if self._ecc else 0.0,
            x_m=self._x.value() if self._x else 0.0,
        )


class _TowerCalculationDialog(QDialog):
    def __init__(self, data: TowerInput, parent=None):
        super().__init__(parent)
        self._data = copy.deepcopy(data)
        self.setWindowTitle("Tower-Berechnung")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._gamma = self._spin(0.1, 10.0, data.gamma, "")
        form.addRow("Sicherheitsfaktor:", self._gamma)
        layout.addWidget(QLabel("Sicherheitsfaktor für die Tower-Vorbemessung."))
        layout.addLayout(form)

        foundation_box = QGroupBox("Fundament-Override")
        foundation_form = QFormLayout(foundation_box)
        self._foundation_width = self._spin(0.05, 50.0, data.foundation.width_m, " m")
        self._foundation_depth = self._spin(0.05, 50.0, data.foundation.depth_m, " m")
        self._foundation_weight = self._spin(0.0, 100000.0, data.foundation.weight_kg, " kg")
        self._ballast = self._spin(0.0, 100000.0, data.foundation.ballast_kg, " kg")
        self._ballast_offset = self._spin(-50.0, 50.0, data.foundation.ballast_offset_m, " m")
        self._clearance = self._spin(0.0, 500.0, data.foundation.clearance_mm, " mm")
        self._insertion_depth = self._spin(0.01, 50.0, data.foundation.insertion_depth_m, " m")
        foundation_form.addRow("Breite:", self._foundation_width)
        foundation_form.addRow("Tiefe:", self._foundation_depth)
        foundation_form.addRow("Eigengewicht:", self._foundation_weight)
        foundation_form.addRow("Ballast:", self._ballast)
        foundation_form.addRow("Ballast-Abstand:", self._ballast_offset)
        if data.foundation.type == "concrete_socket":
            foundation_form.addRow("Spiel:", self._clearance)
            foundation_form.addRow("Einstecktiefe:", self._insertion_depth)
        foundation_box.setVisible(False)
        layout.addWidget(foundation_box)

        connector_box = QGroupBox("Schrauben / Verbinder")
        connector_form = QFormLayout(connector_box)
        self._bolt_count = QDoubleSpinBox()
        self._bolt_count.setRange(0, 256)
        self._bolt_count.setDecimals(0)
        self._bolt_count.setValue(data.connector.bolt_count)
        self._bolt_count.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._bolt_lever = self._spin(0.0, 50.0, data.connector.bolt_lever_arm_m, " m")
        self._bolt_tension = self._spin(0.0, 10000.0, data.connector.allowable_tension_kn, " kN")
        self._bolt_shear = self._spin(0.0, 10000.0, data.connector.allowable_shear_kn, " kN")
        connector_form.addRow("Schraubenanzahl:", self._bolt_count)
        connector_form.addRow("Hebelarm:", self._bolt_lever)
        connector_form.addRow("Zugkraft je Schraube:", self._bolt_tension)
        connector_form.addRow("Querkraft je Schraube:", self._bolt_shear)
        connector_box.setVisible(False)
        layout.addWidget(connector_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def get_input(self) -> TowerInput:
        self._data.gamma = self._gamma.value()
        self._data.foundation.width_m = self._foundation_width.value()
        self._data.foundation.depth_m = self._foundation_depth.value()
        self._data.foundation.weight_kg = self._foundation_weight.value()
        self._data.foundation.ballast_kg = self._ballast.value()
        self._data.foundation.ballast_offset_m = self._ballast_offset.value()
        self._data.foundation.clearance_mm = self._clearance.value()
        self._data.foundation.insertion_depth_m = self._insertion_depth.value()
        self._data.connector.bolt_count = int(self._bolt_count.value())
        self._data.connector.bolt_lever_arm_m = self._bolt_lever.value()
        self._data.connector.allowable_tension_kn = self._bolt_tension.value()
        self._data.connector.allowable_shear_kn = self._bolt_shear.value()
        return self._data


class _TowerAssemblyCanvas(QWidget):
    foundation_place_requested = pyqtSignal()
    add_section_requested = pyqtSignal(float)
    add_cantilever_requested = pyqtSignal(str, float)
    add_horizontal_load_requested = pyqtSignal(float, float)
    add_vertical_load_requested = pyqtSignal(float, float)
    delete_requested = pyqtSignal(str, str)
    edit_requested = pyqtSignal(str, str)
    selection_changed = pyqtSignal(object)
    message_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._tool = "select"
        self._assembly = TowerAssembly()
        self._result: TowerResult | None = None
        self._truss_lookup: dict[int, TrussType] = {}
        self._selected: tuple[str, str] | None = None
        self._layout = {}
        self._label_rects: list[tuple[float, float, float, float]] = []
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._panning = False
        self._pan_last = QPointF()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self.setCursor(Qt.CursorShape.CrossCursor if tool != "select" else Qt.CursorShape.ArrowCursor)

    def set_state(
        self,
        assembly: TowerAssembly,
        result: TowerResult | None,
        truss_lookup: dict[int, TrussType],
    ) -> None:
        self._assembly = copy.deepcopy(assembly)
        refresh_section_positions(self._assembly)
        self._result = result
        self._truss_lookup = dict(truss_lookup)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        height_m = self._height_from_y(event.position().y())
        x_m = self._x_from_pos(event.position().x())
        hit = self._hit_test(event.position())
        if self._tool == "section":
            self.add_section_requested.emit(height_m)
        elif self._tool == "foundation":
            self.foundation_place_requested.emit()
        elif self._tool == "cantilever":
            self.add_cantilever_requested.emit("left" if x_m < 0 else "right", height_m)
        elif self._tool == "horizontal":
            self.add_horizontal_load_requested.emit(x_m, height_m)
        elif self._tool == "vertical":
            x_m = self._clamped_x_for_height(x_m, height_m)
            self.add_vertical_load_requested.emit(x_m, height_m)
        elif self._tool == "delete":
            if hit:
                self.delete_requested.emit(hit[0], hit[1])
        else:
            self._selected = hit
            self.selection_changed.emit(hit)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan += delta
            self._pan_last = event.position()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.set_tool(self._tool)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        old_zoom = self._zoom
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom = max(0.35, min(3.0, self._zoom * factor))
        if abs(self._zoom - old_zoom) > 1e-6:
            self.update()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if (
            event.modifiers() == Qt.KeyboardModifier.NoModifier
            and event.key() == Qt.Key.Key_Delete
            and self._selected
        ):
            self.delete_requested.emit(self._selected[0], self._selected[1])
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.set_tool("select")
            self.message_requested.emit("Auswahl-Werkzeug aktiv")
            event.accept()
            return
        super().keyPressEvent(event)

    def selected_ref(self) -> tuple[str, str] | None:
        return self._selected

    def clear_selection(self) -> None:
        self._selected = None
        self.selection_changed.emit(None)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        hit = self._hit_test(event.position())
        if hit:
            self.edit_requested.emit(hit[0], hit[1])

    def contextMenuEvent(self, event) -> None:
        hit = self._hit_test(event.pos())
        if not hit:
            return
        menu = QMenu(self)
        edit = menu.addAction("Bearbeiten")
        delete = menu.addAction("Löschen")
        action = menu.exec(event.globalPos())
        if action == edit:
            self.edit_requested.emit(hit[0], hit[1])
        elif action == delete:
            self.delete_requested.emit(hit[0], hit[1])

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252525"))
        self._layout = self._compute_layout()
        self._label_rects = []

        painter.setPen(QColor("#D4D4D4"))
        painter.setFont(QFont("Helvetica", 9))
        if self._assembly.foundation is None:
            painter.drawText(24, 30, "Doppelklick auf ein Fundament in der Fundamentbibliothek.")
        if not self._assembly.sections:
            painter.drawText(24, 50, "Danach Traversentyp wählen und Werkzeug 'Traverse' benutzen.")

        self._draw_foundation(painter)
        self._draw_sections(painter)
        self._draw_cantilevers(painter)
        self._draw_loads(painter)
        self._draw_result_forces(painter)
        self._draw_dimensions(painter)
        painter.end()

    def _compute_layout(self) -> dict:
        w = max(self.width(), 300)
        h = max(self.height(), 300)
        left_zone = max(110, min(180, int(w * 0.22)))
        right_zone = max(100, min(170, int(w * 0.18)))
        top = 52
        bottom = h - 116
        cx = int((left_zone + (w - right_zone)) / 2 + self._pan.x())
        height_m = max(self._assembly.height_m, 1.0)
        vertical_scale = max(20.0, (bottom - top) / height_m)
        max_left = max((c.length_m for c in self._assembly.cantilevers if c.side == "left"), default=0.0)
        max_right = max((c.length_m for c in self._assembly.cantilevers if c.side != "left"), default=0.0)
        horizontal_limits = []
        if max_left > 0:
            horizontal_limits.append(max(20.0, (cx - 24) / max_left))
        if max_right > 0:
            horizontal_limits.append(max(20.0, (w - cx - 24) / max_right))
        fit_scale = min([vertical_scale] + horizontal_limits) if horizontal_limits else vertical_scale
        scale = max(12.0, fit_scale * self._zoom)
        base_y = max(top + 80, min(bottom + 220, bottom + self._pan.y()))
        top_y = base_y - height_m * scale
        if top_y < top:
            top_y = top
            scale = max(12.0, (base_y - top_y) / height_m)
        foundation = self._assembly.foundation
        width_m = foundation.width_m if foundation else 1.0
        foundation_w = max(90, min(260, int(width_m * 120)))
        return {
            "left_zone": left_zone,
            "right_zone": right_zone,
            "cx": cx,
            "top_y": top_y,
            "base_y": base_y,
            "scale": scale,
            "foundation_w": foundation_w,
        }

    def _draw_foundation(self, painter: QPainter) -> None:
        if not self._assembly.foundation:
            return
        cx = self._layout["cx"]
        base_y = self._layout["base_y"]
        fw = self._layout["foundation_w"]
        rect = (cx - fw // 2, int(base_y), fw, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#595959"))
        painter.drawRect(*rect)
        self._layout["foundation_rect"] = rect
        self._label_rects.append((rect[0], rect[1], rect[2], rect[3]))
        if self._selected == ("foundation", "foundation"):
            painter.setPen(QPen(QColor("#70B7FF"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(*rect)
        painter.setPen(QColor("#D4D4D4"))
        painter.setFont(QFont("Helvetica", 10, QFont.Weight.Bold))
        painter.drawText(rect[0], rect[1] + rect[3] + 52, self._assembly.foundation_name or "Fundament")

    def _draw_sections(self, painter: QPainter) -> None:
        cx = self._layout["cx"]
        scale = self._layout["scale"]
        base_y = self._layout["base_y"]
        self._layout["sections"] = {}
        for section in self._assembly.sections:
            bottom = base_y - section.position_m * scale
            top = bottom - section.length_m * scale
            rect = (cx - 12, int(top), 24, int(bottom - top))
            self._layout["sections"][section.id] = rect
            self._label_rects.append((rect[0], rect[1], rect[2], rect[3]))
            self._draw_truss_symbol(painter, cx, int(top), int(bottom))
            if self._selected == ("section", section.id):
                painter.setPen(QPen(QColor("#70B7FF"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(*rect)

    def _draw_cantilevers(self, painter: QPainter) -> None:
        cx = self._layout["cx"]
        scale = self._layout["scale"]
        self._layout["cantilevers"] = {}
        for cantilever in self._assembly.cantilevers:
            top_edge_y = self._y_for_height(cantilever.height_m)
            y = top_edge_y + 10
            length_px = max(20, int(cantilever.length_m * scale))
            if cantilever.side == "left":
                x1, x2 = cx - 12, cx - 12 - length_px
            else:
                x1, x2 = cx + 12, cx + 12 + length_px
            self._draw_horizontal_truss_symbol(painter, int(x1), int(x2), int(y))
            rect = (
                min(int(x1), int(x2)),
                int(top_edge_y),
                abs(int(x2 - x1)),
                24,
            )
            self._layout["cantilevers"][cantilever.id] = rect
            self._label_rects.append((rect[0], rect[1], rect[2], rect[3]))
            if self._selected == ("cantilever", cantilever.id):
                painter.setPen(QPen(QColor("#70B7FF"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(*rect)

    def _draw_loads(self, painter: QPainter) -> None:
        self._layout["loads"] = {}
        cx = self._layout["cx"]
        for load in self._assembly.point_loads:
            y = self._y_for_height(load.height_m)
            color = QColor("#5FF0E6") if load.direction == "horizontal" else QColor("#D8B15F")
            if load.direction == "horizontal":
                if load.x_m > 0:
                    start = QPointF(cx + 150, y)
                    end = QPointF(cx + 22, y)
                    label_offset = QPointF(38, -10)
                else:
                    start = QPointF(cx - 150, y)
                    end = QPointF(cx - 22, y)
                    label_offset = QPointF(0, -10)
                label = f"Fh {load.value:.2f} kN"
                self._draw_arrow(painter, start, end, color, label, label_offset)
                hit = (
                    int(min(start.x(), end.x())),
                    int(y - 12),
                    int(abs(end.x() - start.x())),
                    24,
                )
            else:
                x = int(max(48, min(self.width() - 54, cx + load.x_m * self._layout["scale"])))
                start_y = max(24, y - 58)
                end_y = max(start_y + 30, y - 20)
                end_y = min(end_y, self.height() - 120)
                start = QPointF(x, start_y)
                end = QPointF(x, end_y)
                label = f"{load.value:.0f} kg"
                self._draw_arrow(painter, start, end, color, label, QPointF(-8, -8))
                hit = (int(x - 18), int(start_y - 4), 36, int(end_y - start_y + 12))
            self._layout["loads"][load.id] = hit
            if self._selected == ("load", load.id):
                painter.setPen(QPen(QColor("#70B7FF"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(*hit)

    def _draw_result_forces(self, painter: QPainter) -> None:
        result = self._result
        foundation = self._assembly.foundation
        if not result or not foundation:
            return
        status_color = QColor({
            "green": "#1FB386",
            "yellow": "#F0A500",
            "red": "#E74C3C",
        }.get(result.status, "#AAAAAA"))
        cx = self._layout["cx"]
        base_y = self._layout["base_y"]
        fw = self._layout["foundation_w"]
        direction = -1 if getattr(result, "moment_direction", 1) < 0 else 1
        edge_x = cx - fw // 2 - 26 if direction > 0 else cx + fw // 2 + 26
        fk_label_offset = QPointF(-62, -2) if direction > 0 else QPointF(8, -2)
        self._draw_arrow(
            painter,
            QPointF(edge_x, base_y + 62),
            QPointF(edge_x, base_y + 8),
            status_color,
            f"Fk {result.edge_force_kn * 1000.0:.0f} N",
            fk_label_offset,
        )
        self._draw_arrow(
            painter,
            QPointF(cx + fw // 2 + 58, base_y - 70),
            QPointF(cx + fw // 2 + 58, base_y - 8),
            status_color,
            f"Rz {result.base_compression_kg * 9.80665 / 1000.0:.2f} kN",
            QPointF(-82, -2),
        )
        if result.total_top_displacement_mm > 0:
            bend_px = direction * min(50, max(8, result.total_top_displacement_mm / 2.0))
            top_y = self._layout["top_y"]
            path = QPainterPath(QPointF(cx, base_y))
            path.cubicTo(cx + bend_px * 0.2, base_y - 120, cx + bend_px * 0.8, top_y + 120, cx + bend_px, top_y)
            painter.setPen(QPen(status_color, 2.4, Qt.PenStyle.DashLine))
            painter.drawPath(path)
        self._draw_cantilever_deflections(painter, status_color)

    def _draw_cantilever_deflections(self, painter: QPainter, color: QColor) -> None:
        if not self._assembly.cantilevers:
            return
        truss = None
        ids = self._assembly.truss_type_ids
        if ids:
            truss = self._truss_lookup.get(ids[0])
        deflections = cantilever_deflections_mm(self._assembly, truss, self._assembly.gamma)
        if not deflections:
            return
        cx = self._layout["cx"]
        scale = self._layout["scale"]
        painter.setPen(QPen(color, 2.0, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setFont(QFont("Helvetica", 9))
        for cantilever in self._assembly.cantilevers:
            value_mm = deflections.get(cantilever.id or "", 0.0)
            if value_mm <= 0.05:
                continue
            top_edge_y = self._y_for_height(cantilever.height_m)
            y0 = top_edge_y + 10
            length_px = max(20.0, cantilever.length_m * scale)
            sag_px = min(44.0, max(5.0, value_mm * 1.8))
            if cantilever.side == "left":
                x0 = cx - 12
                x_end = x0 - length_px
            else:
                x0 = cx + 12
                x_end = x0 + length_px
            path = QPainterPath(QPointF(x0, y0))
            mid_x = (x0 + x_end) / 2.0
            path.cubicTo(mid_x, y0 + sag_px * 0.15, mid_x, y0 + sag_px * 0.75, x_end, y0 + sag_px)
            painter.drawPath(path)
            painter.setPen(color)
            self._draw_label(
                painter,
                f"u {value_mm:.1f} mm",
                int(x_end + (8 if cantilever.side != "left" else -58)),
                int(y0 + sag_px + 14),
                color,
            )
            painter.setPen(QPen(color, 2.0, Qt.PenStyle.DashLine))

    def _draw_dimensions(self, painter: QPainter) -> None:
        if self._assembly.height_m <= 0:
            return
        cx = self._layout["cx"]
        top_y = self._layout["top_y"]
        base_y = self._layout["base_y"]
        fw = self._layout["foundation_w"]
        self._draw_dimension(
            painter,
            QPointF(cx + fw // 2 + 72, top_y),
            QPointF(cx + fw // 2 + 72, base_y),
            f"H {self._assembly.height_m:.2f} m",
            True,
        )
        if self._assembly.foundation:
            self._draw_dimension(
                painter,
                QPointF(cx - fw // 2, base_y + 54),
                QPointF(cx + fw // 2, base_y + 54),
                f"B {self._assembly.foundation.width_m:.2f} m",
                False,
            )

    def _draw_truss_symbol(self, painter: QPainter, cx: int, top_y: int, base_y: int) -> None:
        half_w = 10
        painter.setPen(QPen(QColor("#D4D4D4"), 3))
        painter.drawLine(cx - half_w, base_y, cx - half_w, top_y)
        painter.drawLine(cx + half_w, base_y, cx + half_w, top_y)
        painter.setPen(QPen(QColor("#8A8A8A"), 1))
        step = 24
        y = top_y
        flip = False
        while y + step <= base_y:
            if flip:
                painter.drawLine(QPointF(cx + half_w, y), QPointF(cx - half_w, y + step))
            else:
                painter.drawLine(QPointF(cx - half_w, y), QPointF(cx + half_w, y + step))
            painter.drawLine(QPointF(cx - half_w, y), QPointF(cx + half_w, y))
            y += step
            flip = not flip
        painter.drawLine(QPointF(cx - half_w, base_y), QPointF(cx + half_w, base_y))

    def _draw_horizontal_truss_symbol(self, painter: QPainter, x1: int, x2: int, y: int) -> None:
        half_h = 10
        left = min(x1, x2)
        right = max(x1, x2)
        painter.setPen(QPen(QColor("#D4D4D4"), 3))
        painter.drawLine(left, y - half_h, right, y - half_h)
        painter.drawLine(left, y + half_h, right, y + half_h)
        painter.setPen(QPen(QColor("#8A8A8A"), 1))
        step = 24
        x = left
        flip = False
        while x + step <= right:
            if flip:
                painter.drawLine(QPointF(x, y + half_h), QPointF(x + step, y - half_h))
            else:
                painter.drawLine(QPointF(x, y - half_h), QPointF(x + step, y + half_h))
            painter.drawLine(QPointF(x, y - half_h), QPointF(x, y + half_h))
            x += step
            flip = not flip
        painter.drawLine(QPointF(right, y - half_h), QPointF(right, y + half_h))

    def _draw_arrow(self, painter: QPainter, start: QPointF, end: QPointF,
                    color: QColor, label: str, label_offset: QPointF) -> None:
        painter.setPen(QPen(color, 2))
        painter.drawLine(start, end)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        ux, uy = dx / length, dy / length
        left = QPointF(end.x() - ux * 10 - uy * 5, end.y() - uy * 10 + ux * 5)
        right = QPointF(end.x() - ux * 10 + uy * 5, end.y() - uy * 10 - ux * 5)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([end, left, right]))
        painter.setPen(color)
        painter.setFont(QFont("Helvetica", 9))
        self._draw_label(
            painter,
            label,
            int(min(start.x(), end.x()) + label_offset.x()),
            int(min(start.y(), end.y()) + label_offset.y()),
            color,
        )

    def _draw_label(self, painter: QPainter, text: str, x: int, y: int, color: QColor) -> None:
        if not text:
            return
        painter.setPen(color)
        painter.setFont(QFont("Helvetica", 9))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text)
        height = metrics.height()
        min_x = 8
        max_x = max(min_x, self.width() - width - 8)
        x = int(max(min_x, min(max_x, x)))
        min_baseline = height + 6
        max_baseline = max(min_baseline, self.height() - 8)
        y = int(max(min_baseline, min(max_baseline, y)))

        candidates = [0, -16, 16, -32, 32, -48, 48, -64, 64]
        best_rect = None
        best_y = y
        for offset in candidates:
            candidate_y = int(max(min_baseline, min(max_baseline, y + offset)))
            rect = (x - 3, candidate_y - metrics.ascent() - 3, width + 6, height + 6)
            if not any(_intersects(rect, other) for other in self._label_rects):
                best_rect = rect
                best_y = candidate_y
                break
        if best_rect is None:
            best_rect = (x - 3, y - metrics.ascent() - 3, width + 6, height + 6)
        self._label_rects.append(best_rect)
        painter.drawText(x, best_y, text)

    def _draw_dimension(self, painter: QPainter, start: QPointF, end: QPointF,
                        label: str, vertical: bool) -> None:
        painter.setPen(QPen(QColor("#8FA7B3"), 1, Qt.PenStyle.DotLine))
        painter.drawLine(start, end)
        painter.setPen(QColor("#BFD4DD"))
        painter.setFont(QFont("Helvetica", 10))
        if vertical:
            painter.drawText(int(start.x() + 8), int((start.y() + end.y()) / 2), label)
        else:
            painter.drawText(int((start.x() + end.x()) / 2 - 30), int(start.y() - 7), label)

    def _height_from_y(self, y: float) -> float:
        if not self._layout:
            self._layout = self._compute_layout()
        base_y = self._layout["base_y"]
        scale = self._layout["scale"]
        height = max(0.0, (base_y - y) / max(scale, 1e-9))
        if self._assembly.height_m > 0:
            return min(height, self._assembly.height_m)
        return height

    def _x_from_pos(self, x: float) -> float:
        if not self._layout:
            self._layout = self._compute_layout()
        cx = self._layout["cx"]
        scale = self._layout["scale"]
        return (x - cx) / max(scale, 1e-9)

    def _clamped_x_for_height(self, x_m: float, height_m: float) -> float:
        height_m = max(0.0, min(height_m, self._assembly.height_m))
        left_limit = 0.0
        right_limit = 0.0
        tolerance = 0.35
        for cantilever in self._assembly.cantilevers:
            if abs(cantilever.height_m - height_m) > tolerance:
                continue
            if cantilever.side == "left":
                left_limit = min(left_limit, -cantilever.length_m)
            else:
                right_limit = max(right_limit, cantilever.length_m)
        if x_m < 0 and left_limit < 0:
            return max(left_limit, min(0.0, x_m))
        if x_m > 0 and right_limit > 0:
            return min(right_limit, max(0.0, x_m))
        return 0.0

    def _y_for_height(self, height_m: float) -> float:
        base_y = self._layout["base_y"]
        scale = self._layout["scale"]
        return base_y - max(0.0, min(height_m, max(self._assembly.height_m, height_m))) * scale

    def _hit_test(self, pos) -> tuple[str, str] | None:
        x = pos.x()
        y = pos.y()
        rect = self._layout.get("foundation_rect")
        if rect and _contains(rect, x, y):
            return ("foundation", "foundation")
        for element_id, section_rect in self._layout.get("sections", {}).items():
            if _contains(section_rect, x, y):
                return ("section", element_id)
        for element_id, cantilever_rect in self._layout.get("cantilevers", {}).items():
            if _contains(cantilever_rect, x, y):
                return ("cantilever", element_id)
        for element_id, load_rect in self._layout.get("loads", {}).items():
            if _contains(load_rect, x, y):
                return ("load", element_id)
        return None


def _contains(rect, x: float, y: float) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _intersects(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
