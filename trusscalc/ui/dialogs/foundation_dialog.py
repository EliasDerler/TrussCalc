"""Dialog für manuelle Tower-Fundamente."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QLineEdit, QSpinBox, QVBoxLayout,
)

from trusscalc.core.models import (
    TowerConnector, TowerFoundation, TowerFoundationPreset,
)


class FoundationDialog(QDialog):
    def __init__(self, preset: TowerFoundationPreset | None = None, parent=None):
        super().__init__(parent)
        self._preset = preset
        self.setWindowTitle("Fundament" if preset is None else "Fundament bearbeiten")
        self._build_ui()
        if preset:
            self._load_preset(preset)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._top_form = form
        self._name = QLineEdit()
        self._name.setPlaceholderText("z. B. Stahlplatte 100x100")
        form.addRow("Name:", self._name)

        self._type = QComboBox()
        self._type.addItem("Stahl-Bodenplatte", "steel_plate")
        self._type.addItem("Beton-Sockel", "concrete_socket")
        self._type.currentIndexChanged.connect(self._refresh_visibility)
        form.addRow("Typ:", self._type)
        layout.addLayout(form)

        foundation_group = QGroupBox("Fundamentdaten")
        foundation_form = QFormLayout(foundation_group)
        self._foundation_form = foundation_form
        self._width = self._spin(0.05, 50.0, 1.0, " m")
        self._depth = self._spin(0.05, 50.0, 1.0, " m")
        self._weight = self._spin(0.0, 100000.0, 0.0, " kg")
        self._ballast = self._spin(0.0, 100000.0, 0.0, " kg")
        self._ballast_offset = self._spin(-50.0, 50.0, 0.0, " m")
        self._clearance = self._spin(0.0, 500.0, 0.0, " mm")
        self._insertion_depth = self._spin(0.01, 50.0, 0.5, " m")
        foundation_form.addRow("Breite in Kraftrichtung:", self._width)
        foundation_form.addRow("Tiefe:", self._depth)
        foundation_form.addRow("Eigengewicht:", self._weight)
        foundation_form.addRow("Ballast:", self._ballast)
        foundation_form.addRow("Ballast-Abstand zur Mitte:", self._ballast_offset)
        foundation_form.addRow("Spiel:", self._clearance)
        foundation_form.addRow("Einstecktiefe:", self._insertion_depth)
        layout.addWidget(foundation_group)

        connector_group = QGroupBox("Schrauben / Verbinder")
        self._connector_group = connector_group
        connector_form = QFormLayout(connector_group)
        self._connector_form = connector_form
        self._bolt_count = QSpinBox()
        self._bolt_count.setRange(0, 256)
        self._bolt_count.setValue(4)
        self._bolt_count.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._bolt_lever = self._spin(0.0, 50.0, 0.25, " m")
        self._bolt_tension = self._spin(0.0, 10000.0, 5.0, " kN")
        self._bolt_shear = self._spin(0.0, 10000.0, 5.0, " kN")
        connector_form.addRow("Schraubenanzahl:", self._bolt_count)
        connector_form.addRow("Wirksamer Hebelarm:", self._bolt_lever)
        connector_form.addRow("Zulaessige Zugkraft je Schraube:", self._bolt_tension)
        connector_form.addRow("Zulaessige Querkraft je Schraube:", self._bolt_shear)
        layout.addWidget(connector_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._apply_tooltips()
        self._refresh_visibility()

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(4)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return spin

    def _load_preset(self, preset: TowerFoundationPreset) -> None:
        self._name.setText(preset.name)
        idx = self._type.findData(preset.foundation.type)
        self._type.setCurrentIndex(idx if idx >= 0 else 0)
        self._width.setValue(preset.foundation.width_m)
        self._depth.setValue(preset.foundation.depth_m)
        self._weight.setValue(preset.foundation.weight_kg)
        self._ballast.setValue(preset.foundation.ballast_kg)
        self._ballast_offset.setValue(preset.foundation.ballast_offset_m)
        self._clearance.setValue(preset.foundation.clearance_mm)
        self._insertion_depth.setValue(preset.foundation.insertion_depth_m)
        self._bolt_count.setValue(preset.connector.bolt_count)
        self._bolt_lever.setValue(preset.connector.bolt_lever_arm_m)
        self._bolt_tension.setValue(preset.connector.allowable_tension_kn)
        self._bolt_shear.setValue(preset.connector.allowable_shear_kn)
        self._refresh_visibility()

    def get_preset(self) -> TowerFoundationPreset:
        preset_id = self._preset.id if self._preset else None
        return TowerFoundationPreset(
            id=preset_id,
            name=self._name.text().strip() or "Fundament",
            foundation=TowerFoundation(
                type=self._type.currentData(),
                width_m=self._width.value(),
                depth_m=self._depth.value(),
                weight_kg=self._weight.value(),
                ballast_kg=self._ballast.value(),
                ballast_offset_m=self._ballast_offset.value(),
                clearance_mm=self._clearance.value(),
                insertion_depth_m=self._insertion_depth.value(),
            ),
            connector=(
                TowerConnector(
                    bolt_count=self._bolt_count.value(),
                    bolt_lever_arm_m=self._bolt_lever.value(),
                    allowable_tension_kn=self._bolt_tension.value(),
                    allowable_shear_kn=self._bolt_shear.value(),
                )
                if self._type.currentData() == "concrete_socket"
                else TowerConnector(
                    bolt_count=0,
                    bolt_lever_arm_m=0.0,
                    allowable_tension_kn=0.0,
                    allowable_shear_kn=0.0,
                )
            ),
        )

    def _refresh_visibility(self) -> None:
        is_socket = self._type.currentData() == "concrete_socket"
        self._set_form_row_visible(self._foundation_form, self._clearance, is_socket)
        self._set_form_row_visible(self._foundation_form, self._insertion_depth, is_socket)
        self._connector_group.setVisible(is_socket)

    def _set_form_row_visible(self, form: QFormLayout, widget, visible: bool) -> None:
        label = form.labelForField(widget)
        if label:
            label.setVisible(visible)
        widget.setVisible(visible)

    def _apply_tooltips(self) -> None:
        tips = {
            self._name: "Interner Name des Fundaments in der Bibliothek.",
            self._type: "Stahl-Bodenplatte ist fix verbunden. Beton-Sockel nutzt Spiel, Einstecktiefe und Verbinderwerte.",
            self._width: "Breite in Kraftrichtung. Dieser Hebelarm bestimmt die Kipp- und Kantenkraft.",
            self._depth: "Tiefe quer zur Kraftrichtung, für Dokumentation und Vorschau.",
            self._weight: "Eigengewicht der Bodenplatte oder des Beton-Sockels.",
            self._ballast: "Zusatzgewicht, das gegen Kippen angesetzt wird.",
            self._ballast_offset: "Abstand des Ballast-Schwerpunkts zur Fundamentmitte in Kraftrichtung.",
            self._clearance: "Spiel zwischen Traverse und Beton-Sockel. Wird als Kopfversatz berücksichtigt.",
            self._insertion_depth: "Wirksame Einstecktiefe der Traverse im Sockel.",
            self._bolt_count: "Anzahl der tragenden Schrauben oder Verbinder beim Beton-Sockel.",
            self._bolt_lever: "Wirksamer Hebelarm des Schrauben-/Verbinderbilds.",
            self._bolt_tension: "Zulaessige Zugkraft je Schraube oder Verbinder.",
            self._bolt_shear: "Zulaessige Querkraft je Schraube oder Verbinder.",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip)
        for form in (self._top_form, self._foundation_form, self._connector_form):
            for widget, tip in tips.items():
                label = form.labelForField(widget)
                if label:
                    label.setToolTip(tip)
