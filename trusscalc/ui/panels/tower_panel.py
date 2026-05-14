"""Tower-Eingabemaske für freistehende Einzeltower."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
    QDoubleSpinBox, QSpinBox, QComboBox, QPushButton, QScrollArea,
    QAbstractSpinBox,
)

from trusscalc.core.models import (
    TowerConnector, TowerFoundation, TowerInput, TowerResult, TrussType,
)


class TowerPanel(QWidget):
    changed = pyqtSignal()
    calculate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._truss_type: TrussType | None = None
        self._truss_type_id = 0
        self._build_ui()

    def set_tower(self, data: TowerInput, result: TowerResult | None,
                  truss_type: TrussType | None = None) -> None:
        self._loading = True
        self._truss_type = truss_type
        self._truss_type_id = (
            truss_type.id if truss_type and truss_type.id else data.truss_type_id
        )
        self._truss_label.setText(
            truss_type.display_name if truss_type else "Kein Traversentyp ausgewählt"
        )
        self._height.setValue(data.height_m)
        self._force.setValue(data.horizontal_force_kn)
        if abs(data.horizontal_force_kn - 0.5) < 1e-9:
            self._force_preset.setCurrentIndex(0)
        elif abs(data.horizontal_force_kn - 1.0) < 1e-9:
            self._force_preset.setCurrentIndex(1)
        else:
            self._force_preset.setCurrentIndex(2)
        self._force_height.setValue(data.force_height_m)
        self._payload.setValue(data.payload_kg)
        self._payload_ecc.setValue(data.payload_eccentricity_m)
        self._gamma.setValue(data.gamma)
        self._foundation_type.setCurrentIndex(
            1 if data.foundation.type == "concrete_socket" else 0
        )
        self._foundation_width.setValue(data.foundation.width_m)
        self._foundation_depth.setValue(data.foundation.depth_m)
        self._foundation_weight.setValue(data.foundation.weight_kg)
        self._ballast.setValue(data.foundation.ballast_kg)
        self._ballast_offset.setValue(data.foundation.ballast_offset_m)
        self._clearance.setValue(data.foundation.clearance_mm)
        self._insertion_depth.setValue(data.foundation.insertion_depth_m)
        self._bolt_count.setValue(data.connector.bolt_count)
        self._bolt_lever.setValue(data.connector.bolt_lever_arm_m)
        self._bolt_tension.setValue(data.connector.allowable_tension_kn)
        self._bolt_shear.setValue(data.connector.allowable_shear_kn)
        self._refresh_foundation_fields()
        self._refresh_force_fields()
        self._loading = False
        self.show_result(result)
        self._preview.set_tower(data, result)

    def set_truss_type(self, truss_type: TrussType) -> TowerInput:
        self._truss_type = truss_type
        self._truss_type_id = truss_type.id or 0
        self._truss_label.setText(truss_type.display_name)
        data = self.tower_input()
        data.truss_type_id = truss_type.id or 0
        return data

    def tower_input(self) -> TowerInput:
        return TowerInput(
            truss_type_id=self._truss_type_id,
            height_m=self._height.value(),
            horizontal_force_kn=self._force.value(),
            force_height_m=self._force_height.value(),
            payload_kg=self._payload.value(),
            payload_eccentricity_m=self._payload_ecc.value(),
            gamma=self._gamma.value(),
            foundation=TowerFoundation(
                type=self._foundation_type.currentData(),
                width_m=self._foundation_width.value(),
                depth_m=self._foundation_depth.value(),
                weight_kg=self._foundation_weight.value(),
                ballast_kg=self._ballast.value(),
                ballast_offset_m=self._ballast_offset.value(),
                clearance_mm=self._clearance.value(),
                insertion_depth_m=self._insertion_depth.value(),
            ),
            connector=TowerConnector(
                bolt_count=self._bolt_count.value(),
                bolt_lever_arm_m=self._bolt_lever.value(),
                allowable_tension_kn=self._bolt_tension.value(),
                allowable_shear_kn=self._bolt_shear.value(),
            ),
        )

    def show_result(self, result: TowerResult | None) -> None:
        if result is None:
            self._status.setText("Nicht berechnet")
            self._status.setStyleSheet("color: #AAAAAA; font-weight: bold;")
            self._result_text.setText("F5 oder Berechnen drücken.")
            self._preview.set_tower(self.tower_input(), None)
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
            f"- {w}" for w in result.warnings
            if "Vorbemessung" not in w and "Standsicherheitsnachweis" not in w
        )
        suffix = f"\n\n{warnings}" if warnings else ""
        foundation_lines = (
            "Anschluss Bodenplatte: fix verbunden. Schrauben-/Verbinderwerte werden für diesen Fundamenttyp nicht angesetzt.\n"
            if self.tower_input().foundation.type == "steel_plate"
            else (
                f"Schraubenzug je belasteter Schraube: {result.bolt_tension_kn:.2f} kN. Zugkraft aus Kippmoment auf die belastete Schraubenseite.\n"
                f"Schraubenquerkraft je Schraube: {result.bolt_shear_kn:.2f} kN. Horizontalkraft [Fh] verteilt auf alle Schrauben.\n"
                f"Schraubenauslastung: {result.bolt_utilization * 100:.0f} %. Höchste Auslastung aus Zug und Querkraft.\n"
                f"Kopfversatz durch Spiel: {result.top_offset_mm:.1f} mm. Geometrischer Versatz aus Sockelspiel und Einstecktiefe.\n"
            )
        )
        self._result_text.setText(
            f"• Bemessungsmoment [MEd]: {result.design_moment_knm:.2f} kNm\n"
            f"• Standmoment: {result.resisting_moment_knm:.2f} kNm\n"
            f"• Kippauslastung: {result.tipping_utilization * 100:.0f} %\n"
            f"• Max. Horizontalkraft [Fh,max]: {result.max_horizontal_force_kn:.2f} kN\n"
            f"• Zusätzlicher Ballastbedarf: {ballast}\n"
            f"• Kantenkraft [Fk]: {result.edge_force_kn * 1000.0:.0f} N\n"
            f"• Basis-Druckkraft [Rz]: {result.base_compression_kg * 9.80665 / 1000.0:.2f} kN\n"
            f"• {foundation_lines.strip()}\n"
            f"• Biegung Tower: {result.bending_deflection_mm:.1f} mm\n"
            f"• Gesamt-Kopfversatz: {result.total_top_displacement_mm:.1f} mm"
            f"{suffix}"
        )
        self._result_text.setToolTip(
            "MEd: kippendes Moment aus Horizontalkraft [Fh] und exzentrischer Zuladung.\n"
            "Standmoment: Gegenmoment aus Fundament, Ballast, Towergewicht und Zuladung zur Kippkante.\n"
            "Kippauslastung: Verhältnis aus Bemessungsmoment zu Standmoment.\n"
            "Fh,max: theoretische maximale Horizontalkraft bis zur ersten V1-Grenze aus Kippen/Anschluss.\n"
            "Ballastbedarf: zusätzlich benötigte Masse beim aktuellen Ballast-Hebelarm.\n"
            "Fk: vertikale Zug-/Druckkraft an der Bodenplattenkante aus MEd / Bodenplattenbreite. "
            "Sie ist eine Momentenwirkung, nicht die horizontale Kraft selbst.\n"
            "Rz: vertikale Drucklast auf Fundament/Bodenplatte.\n"
            "Biegung: elastische Kopfverformung aus Tower-Biegesteifigkeit.\n"
            "Gesamt-Kopfversatz: Summe aus Spielversatz und Biegung."
        )
        self._preview.set_tower(self.tower_input(), result)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("<b>Tower-Rechner</b>")
        self._status = QLabel("Nicht berechnet")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("Status:"))
        header.addWidget(self._status)
        root.addLayout(header)

        body = QHBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_holder = QWidget()
        form_layout = QVBoxLayout(form_holder)
        form_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._truss_label = QLabel("Kein Traversentyp ausgewählt")
        self._truss_label.setWordWrap(True)
        self._truss_label.setStyleSheet("color: #88BBFF; font-weight: bold;")
        self._truss_label.setToolTip(
            "Traversentyp für den vertikalen Tower. Doppelklick in der Bibliothek setzt diesen Wert."
        )

        general = QGroupBox("Tower")
        general_form = QFormLayout(general)
        self._general_form = general_form
        self._forms = [general_form]
        general_form.addRow("Traversentyp:", self._truss_label)
        self._height = self._spin(0.1, 50.0, 4.0, " m")
        self._force = self._spin(0.0, 100.0, 1.0, " kN")
        self._force_height = self._spin(0.0, 50.0, 4.0, " m")
        self._payload = self._spin(0.0, 10000.0, 0.0, " kg")
        self._payload_ecc = self._spin(-10.0, 10.0, 0.0, " m")
        self._gamma = self._spin(0.1, 5.0, 1.30, "")
        self._force_preset = QComboBox()
        self._force_preset.addItem("0,5 kN", 0.5)
        self._force_preset.addItem("1,0 kN", 1.0)
        self._force_preset.addItem("Custom", None)
        self._force_preset.setCurrentIndex(1)
        self._force_preset.setToolTip("Vordefinierte horizontale Bemessungskraft oder Custom-Eingabe.")
        self._force_preset.currentIndexChanged.connect(self._on_force_preset)
        general_form.addRow("Horizontalkraft [Fh] Preset:", self._force_preset)
        general_form.addRow("Horizontalkraft [Fh]:", self._force)
        general_form.addRow("Angriffshöhe [hF]:", self._force_height)
        general_form.addRow("Tower-Höhe [H]:", self._height)
        general_form.addRow("Zuladung:", self._payload)
        general_form.addRow("Exzentrizität Zuladung:", self._payload_ecc)
        general_form.addRow("Sicherheitsfaktor:", self._gamma)
        form_layout.addWidget(general)

        foundation = QGroupBox("Fundament")
        foundation_form = QFormLayout(foundation)
        self._foundation_form = foundation_form
        self._forms.append(foundation_form)
        self._foundation_type = QComboBox()
        self._foundation_type.addItem("Stahl-Bodenplatte", "steel_plate")
        self._foundation_type.addItem("Beton-Sockel", "concrete_socket")
        self._foundation_type.currentIndexChanged.connect(self._refresh_foundation_fields)
        self._foundation_width = self._spin(0.05, 20.0, 1.0, " m")
        self._foundation_depth = self._spin(0.05, 20.0, 1.0, " m")
        self._foundation_weight = self._spin(0.0, 50000.0, 120.0, " kg")
        self._ballast = self._spin(0.0, 50000.0, 0.0, " kg")
        self._ballast_offset = self._spin(-10.0, 10.0, 0.0, " m")
        self._clearance = self._spin(0.0, 200.0, 0.0, " mm")
        self._insertion_depth = self._spin(0.01, 10.0, 0.5, " m")
        foundation_form.addRow("Typ:", self._foundation_type)
        foundation_form.addRow("Breite in Kraftrichtung:", self._foundation_width)
        foundation_form.addRow("Tiefe:", self._foundation_depth)
        foundation_form.addRow("Eigengewicht:", self._foundation_weight)
        foundation_form.addRow("Ballast:", self._ballast)
        foundation_form.addRow("Ballast-Abstand zur Mitte:", self._ballast_offset)
        foundation_form.addRow("Spiel:", self._clearance)
        foundation_form.addRow("Einstecktiefe:", self._insertion_depth)
        form_layout.addWidget(foundation)

        connector = QGroupBox("Schrauben / Verbinder")
        self._connector_group = connector
        connector_form = QFormLayout(connector)
        self._forms.append(connector_form)
        self._bolt_count = QSpinBox()
        self._bolt_count.setRange(0, 128)
        self._bolt_count.setValue(4)
        self._bolt_count.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._bolt_count.valueChanged.connect(self._changed)
        self._bolt_lever = self._spin(0.0, 10.0, 0.25, " m")
        self._bolt_tension = self._spin(0.0, 1000.0, 5.0, " kN")
        self._bolt_shear = self._spin(0.0, 1000.0, 5.0, " kN")
        connector_form.addRow("Schraubenanzahl:", self._bolt_count)
        connector_form.addRow("Wirksamer Hebelarm:", self._bolt_lever)
        connector_form.addRow("Zulässige Zugkraft je Schraube:", self._bolt_tension)
        connector_form.addRow("Zulässige Querkraft je Schraube:", self._bolt_shear)
        form_layout.addWidget(connector)

        calculate = QPushButton("Berechnen [F5]")
        calculate.setToolTip("Berechnet Standmoment, Kippauslastung, Schraubenkräfte und Tower-Kopfversatz.")
        calculate.clicked.connect(self.calculate_requested)
        form_layout.addWidget(calculate)

        scroll.setWidget(form_holder)
        body.addWidget(scroll, 2)

        right = QVBoxLayout()
        self._preview = _TowerPreview()
        right.addWidget(self._preview, 2)
        result_group = QGroupBox("Ergebnis")
        result_layout = QVBoxLayout(result_group)
        self._result_text = QLabel("F5 oder Berechnen drücken.")
        self._result_text.setWordWrap(True)
        self._result_text.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._result_text.setStyleSheet("font-size: 13px; line-height: 150%;")
        result_layout.addWidget(self._result_text)
        right.addWidget(result_group, 3)
        body.addLayout(right, 3)
        root.addLayout(body, 1)

        for widget in (
            self._height, self._force, self._force_height, self._payload,
            self._payload_ecc, self._gamma, self._foundation_width,
            self._foundation_depth, self._foundation_weight, self._ballast,
            self._ballast_offset, self._clearance, self._insertion_depth,
            self._bolt_lever, self._bolt_tension, self._bolt_shear,
        ):
            widget.valueChanged.connect(self._changed)
        self._foundation_type.currentIndexChanged.connect(self._changed)
        self._apply_tooltips()
        self._refresh_force_fields()

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def _apply_tooltips(self) -> None:
        tips = {
            self._truss_label: "Traversentyp für den vertikalen Tower. Doppelklick in der Bibliothek setzt diesen Wert.",
            self._force_preset: "Vordefinierte horizontale Bemessungskraft oder Custom-Eingabe.",
            self._height: "Gesamthöhe [H] des vertikalen Towers ab Fundamentoberkante.",
            self._force: "Horizontalkraft [Fh] am Tower, z. B. aus Wind, Publikum oder seitlicher Belastung.",
            self._force_height: "Angriffshöhe [hF], in der die Horizontalkraft am Tower angreift.",
            self._payload: "Zusätzliche vertikale Last am Tower, z. B. Scheinwerfer oder Auslegerlast.",
            self._payload_ecc: "Horizontaler Abstand der Zuladung zur Tower-Mitte; erzeugt ein Kippmoment.",
            self._gamma: "Sicherheitsfaktor auf Horizontalkraft [Fh] und exzentrisches Lastmoment.",
            self._foundation_type: "Fundamentart: Stahlplatte oder Beton-Sockel mit Spielbetrachtung.",
            self._foundation_width: "Fundamentbreite in Kraftrichtung; bestimmt den Hebelarm gegen Kippen.",
            self._foundation_depth: "Fundamenttiefe quer zur Kraftrichtung; dient der Dokumentation und Vorschau.",
            self._foundation_weight: "Eigengewicht von Bodenplatte oder Beton-Sockel.",
            self._ballast: "Zusätzlicher Ballast, der gegen Kippen angesetzt wird.",
            self._ballast_offset: "Abstand des Ballast-Schwerpunktes zur Fundamentmitte in Kraftrichtung.",
            self._clearance: "Spiel zwischen Traverse und Beton-Sockel; wird als Kopfversatz ausgegeben.",
            self._insertion_depth: "Wirksame Einstecktiefe der Traverse im Beton-Sockel.",
            self._bolt_count: "Anzahl der tragenden Schrauben oder Verbinder im betrachteten Anschluss.",
            self._bolt_lever: "Wirksamer Abstand zwischen Zug- und Druckseite des Schraubenbilds.",
            self._bolt_tension: "Zulässige Zugkraft je einzelner Schraube laut Hersteller/Statiker.",
            self._bolt_shear: "Zulässige Querkraft je einzelner Schraube laut Hersteller/Statiker.",
        }
        for widget, tip in tips.items():
            self._set_tooltip(widget, tip)

    def _set_tooltip(self, widget, tip: str) -> None:
        widget.setToolTip(tip)
        for form in getattr(self, "_forms", []):
            label = form.labelForField(widget)
            if label:
                label.setToolTip(tip)

    def _on_force_preset(self) -> None:
        value = self._force_preset.currentData()
        if value is not None:
            self._force.setValue(float(value))
        self._refresh_force_fields()
        self._changed()

    def _refresh_force_fields(self) -> None:
        is_custom = self._force_preset.currentData() is None
        self._set_form_row_visible(self._general_form, self._force, is_custom)

    def _refresh_foundation_fields(self) -> None:
        is_socket = self._foundation_type.currentData() == "concrete_socket"
        self._set_form_row_visible(self._foundation_form, self._clearance, is_socket)
        self._set_form_row_visible(self._foundation_form, self._insertion_depth, is_socket)
        self._connector_group.setVisible(is_socket)
        self._changed()

    def _set_form_row_visible(self, form: QFormLayout, widget: QWidget, visible: bool) -> None:
        label = form.labelForField(widget)
        if label:
            label.setVisible(visible)
        widget.setVisible(visible)

    def _changed(self) -> None:
        if self._loading:
            return
        self._preview.set_tower(self.tower_input(), None)
        self.changed.emit()


class _TowerPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._data: TowerInput | None = None
        self._result: TowerResult | None = None

    def set_tower(self, data: TowerInput, result: TowerResult | None) -> None:
        self._data = data
        self._result = result
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        p.fillRect(self.rect(), QColor("#252525"))
        data = self._data or TowerInput()
        result = self._result

        label_pad = max(36, min(76, int(w * 0.12)))
        left = label_pad
        right = w - max(30, int(w * 0.05))
        top = 30
        bottom = h - 78
        draw_w = max(160, right - left)
        draw_h = max(180, bottom - top)
        cx = int(max(left + 110, min(w // 2, right - 95)))
        base_y = bottom - 16
        top_y = top + 28
        max_foundation_w = max(78, min(int(draw_w * 0.48), w - 2 * label_pad - 40))
        foundation_w = max(70, min(max_foundation_w, int(max_foundation_w * min(data.foundation.width_m / 2.0, 1.0))))

        force_y = self._y_for_height(data.force_height_m, data.height_m, top_y, base_y)
        force_arrow_y = min(max(force_y, top_y + 24), base_y - 34)
        payload_x = cx + int(max(-90, min(90, data.payload_eccentricity_m * 45)))
        status_color = self._status_color(result)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#555555"))
        p.drawRect(cx - foundation_w // 2, base_y, foundation_w, 28)
        self._draw_truss_symbol(p, cx, top_y, base_y)

        # Kopf-/Lastträger symbolisch, damit ungleichmäßige Lasten sichtbar werden.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4B4B4B"))
        p.drawRect(cx - 70, top_y - 4, 140, 10)

        self._draw_arrow(
            p,
            QPointF(max(14, cx - foundation_w // 2 - 88), force_arrow_y),
            QPointF(cx - 18, force_arrow_y),
            QColor("#5FF0E6") if not result else status_color,
            f"Fh {data.horizontal_force_kn:.2f} kN",
            label_offset=QPointF(0, -10),
        )
        self._draw_arrow(
            p,
            QPointF(payload_x, top_y - 44),
            QPointF(payload_x, top_y - 14),
            QColor("#D8B15F"),
            f"{data.payload_kg:.0f} kg",
        )
        if result:
            edge_x = cx - foundation_w // 2 - 18
            self._draw_arrow(
                p,
                QPointF(edge_x, base_y + 60),
                QPointF(edge_x, base_y + 10),
                status_color,
                f"Fk {result.edge_force_kn * 1000.0:.0f} N",
                label_offset=QPointF(-58, -2),
            )
            self._draw_arrow(
                p,
                QPointF(cx - 26, base_y - 48),
                QPointF(cx - 26, base_y - 8),
                status_color,
                f"Rz {result.base_compression_kg * 9.80665 / 1000.0:.2f} kN",
                label_offset=QPointF(-64, -2),
            )
            if data.foundation.type == "concrete_socket":
                p.setPen(QPen(status_color, 2))
                p.drawLine(cx - 24, base_y + 5, cx - 42, base_y - 26)
                p.drawLine(cx + 24, base_y + 5, cx + 42, base_y - 26)
                p.setPen(status_color)
                p.drawText(cx + 46, base_y - 18, f"T {result.bolt_tension_kn:.2f} kN")

        # Ergebnis-Biegung im Vordergrund, damit die Kipp-/Biegelinie lesbar bleibt.
        if result and result.total_top_displacement_mm > 0:
            bend_px = min(44, max(8, result.total_top_displacement_mm / 2.0))
            path = QPainterPath(QPointF(cx, base_y))
            path.cubicTo(cx + bend_px * 0.2, base_y - draw_h * 0.35,
                         cx + bend_px * 0.8, top_y + draw_h * 0.35,
                         cx + bend_px, top_y)
            p.setPen(QPen(status_color, 2.4, Qt.PenStyle.DashLine))
            p.drawPath(path)

        self._draw_dimension(
            p, QPointF(cx + foundation_w // 2 + 36, top_y), QPointF(cx + foundation_w // 2 + 36, base_y),
            f"H {data.height_m:.2f} m", vertical=True,
            x_offset=0,
        )
        self._draw_dimension(
            p, QPointF(cx - foundation_w // 2, base_y + 48),
            QPointF(cx + foundation_w // 2, base_y + 48),
            f"B {data.foundation.width_m:.2f} m",
            vertical=False,
        )
        self._draw_dimension(
            p, QPointF(cx, force_y), QPointF(cx, base_y),
            f"hF {data.force_height_m:.2f} m",
            vertical=True,
            x_offset=34,
        )
        if abs(data.payload_eccentricity_m) > 0.01:
            self._draw_dimension(
                p, QPointF(cx, top_y - 36), QPointF(payload_x, top_y - 36),
                f"e {data.payload_eccentricity_m:.2f} m",
                vertical=False,
            )

        p.setPen(QColor("#D4D4D4"))
        p.setFont(QFont("Helvetica", 8))
        p.drawText(12, 20, f"MEd: {(result.design_moment_knm if result else data.gamma * data.horizontal_force_kn * data.force_height_m):.2f} kNm")
        if result:
            p.drawText(12, 38, f"Kopf: {result.total_top_displacement_mm:.1f} mm")
        p.end()

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

    @staticmethod
    def _y_for_height(value: float, tower_height: float, top_y: int, base_y: int) -> int:
        if tower_height <= 0:
            return base_y
        ratio = max(0.0, min(1.0, value / tower_height))
        return int(base_y - ratio * (base_y - top_y))

    @staticmethod
    def _status_color(result: TowerResult | None) -> QColor:
        if result is None:
            return QColor("#5FF0E6")
        return QColor({
            "green": "#1FB386",
            "yellow": "#F0A500",
            "red": "#E74C3C",
        }.get(result.status, "#AAAAAA"))

    @staticmethod
    def _status_label(result: TowerResult) -> str:
        return {
            "green": "OK",
            "yellow": "Prüfen",
            "red": "Kritisch",
        }.get(result.status, result.status)

    def _draw_arrow(self, painter: QPainter, start: QPointF, end: QPointF,
                    color: QColor, label: str, label_offset: QPointF | None = None) -> None:
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
        painter.setFont(QFont("Helvetica", 8))
        offset = label_offset or QPointF(0, -6)
        painter.drawText(
            int(min(start.x(), end.x()) - 2 + offset.x()),
            int(min(start.y(), end.y()) + offset.y()),
            label,
        )

    def _draw_dimension(self, painter: QPainter, start: QPointF, end: QPointF,
                        label: str, vertical: bool, x_offset: int = 0) -> None:
        pen = QPen(QColor("#8FA7B3"), 1, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        if vertical:
            x = start.x() + x_offset
            painter.drawLine(QPointF(x, start.y()), QPointF(x, end.y()))
            painter.drawLine(QPointF(x - 6, start.y()), QPointF(x + 6, start.y()))
            painter.drawLine(QPointF(x - 6, end.y()), QPointF(x + 6, end.y()))
            painter.setPen(QColor("#BFD4DD"))
            painter.drawText(int(x + 8), int((start.y() + end.y()) / 2), label)
        else:
            painter.drawLine(start, end)
            painter.drawLine(QPointF(start.x(), start.y() - 5), QPointF(start.x(), start.y() + 5))
            painter.drawLine(QPointF(end.x(), end.y() - 5), QPointF(end.x(), end.y() + 5))
            painter.setPen(QColor("#BFD4DD"))
            painter.drawText(int((start.x() + end.x()) / 2 - 28), int(start.y() - 6), label)
