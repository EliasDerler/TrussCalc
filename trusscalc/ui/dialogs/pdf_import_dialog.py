"""
PDF Import & Korrektur-Dialog.
Zeigt automatisch geparste Werte an und erlaubt manuelle Korrektur.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDialogButtonBox, QMessageBox, QGroupBox, QFormLayout, QFileDialog,
    QSplitter, QScrollArea, QWidget,
)
from PyQt6.QtCore import Qt

from trusscalc.core.models import LoadType, TrussType, TrussSource, LoadTableEntry
from trusscalc.pdf.pdf_parser import parse_pdf, parsed_to_truss_type

_LOAD_TYPE_LABELS = {
    LoadType.UDL: "UDL (Streckenlast)",
    LoadType.CPL: "CPL (Mittelpunkt)",
    LoadType.THIRD: "1/3-Punkt",
    LoadType.QUARTER: "1/4-Punkt",
    LoadType.FIFTH: "1/5-Punkt",
}


class PdfImportDialog(QDialog):
    def __init__(self, pdf_path: str = None, ocr_result=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datenblatt importieren")
        self.resize(900, 650)
        self._pdf_path = pdf_path
        self._pdf_bytes: bytes = b""
        self._build_ui()
        if pdf_path and ocr_result is not None:
            self._load_from_ocr(pdf_path, ocr_result)
        elif pdf_path:
            self._load_pdf(pdf_path)

    def _load_from_ocr(self, path: str, result) -> None:
        """Befüllt den Dialog mit Ergebnissen des KI-Parsers."""
        self._pdf_path = path
        self._path_edit.setText(path)
        try:
            with open(path, "rb") as f:
                self._pdf_bytes = f.read()
        except OSError:
            pass

        md = result.metadata or {}
        if md.get("name"):
            self._name_edit.setText(md["name"])
        if md.get("manufacturer"):
            self._manuf_edit.setText(md["manufacturer"])
        if md.get("model_code"):
            self._model_edit.setText(md["model_code"])
        if md.get("material"):
            self._material_edit.setText(md["material"])
        if md.get("width_mm"):
            self._width.setValue(md["width_mm"])
        if md.get("height_mm"):
            self._height.setValue(md["height_mm"])
        if md.get("weight_per_meter_kg"):
            self._weight.setValue(md["weight_per_meter_kg"])

        notes = list(result.warnings or [])
        notes.append(f"KI-Parser hat {len(result.entries)} Einträge erkannt – "
                     "bitte prüfen.")
        self._warnings_label.setText("\n".join(notes))
        self._warnings_label.setStyleSheet("color: #66DD66;")

        self._table.setRowCount(0)
        for entry in result.entries:
            self._add_table_row(entry)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # PDF-Pfad Zeile
        path_layout = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("PDF-Datei auswählen…")
        self._path_edit.setReadOnly(True)
        btn_browse = QPushButton("Durchsuchen…")
        btn_browse.clicked.connect(self._browse_pdf)
        path_layout.addWidget(QLabel("PDF:"))
        path_layout.addWidget(self._path_edit, 1)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Linke Seite: Metadaten
        meta_group = QGroupBox("Traverse – Metadaten")
        meta_form = QFormLayout(meta_group)

        self._name_edit = QLineEdit()
        meta_form.addRow("Name:", self._name_edit)

        self._manuf_edit = QLineEdit()
        meta_form.addRow("Hersteller:", self._manuf_edit)

        self._model_edit = QLineEdit()
        meta_form.addRow("Modell:", self._model_edit)

        self._material_edit = QLineEdit()
        meta_form.addRow("Material:", self._material_edit)

        self._width = QDoubleSpinBox()
        self._width.setRange(0, 5000); self._width.setSuffix(" mm")
        meta_form.addRow("Breite:", self._width)

        self._height = QDoubleSpinBox()
        self._height.setRange(0, 5000); self._height.setSuffix(" mm")
        meta_form.addRow("Höhe:", self._height)

        self._weight = QDoubleSpinBox()
        self._weight.setRange(0, 999); self._weight.setSuffix(" kg/m"); self._weight.setDecimals(2)
        meta_form.addRow("Eigengewicht:", self._weight)

        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet("color: orange;")
        meta_form.addRow("Hinweise:", self._warnings_label)

        splitter.addWidget(meta_group)

        # Rechte Seite: Lasttabelle
        table_group = QGroupBox("Lasttabelle (bearbeitbar)")
        table_layout = QVBoxLayout(table_group)

        # Info-Block: Mindestanforderungen
        info_label = QLabel(
            "<b>Benötigte Werte aus dem Datenblatt:</b><br>"
            "&nbsp;&nbsp;• <b>Pflicht:</b> mindestens 1 × <b>UDL</b> (gleichm. Streckenlast) "
            "→ wird zur EI-Bestimmung gebraucht<br>"
            "&nbsp;&nbsp;• <b>Empfohlen:</b> alle 5 Lasttypen (UDL, CPL, 1/3, 1/4, 1/5) "
            "für korrekte Farbprüfung<br>"
            "&nbsp;&nbsp;• <b>Empfohlen:</b> ≥ 2 Stützweiten, die den geplanten Bereich abdecken "
            "(z.&nbsp;B. 6 m, 10 m, 14 m …)<br>"
            "&nbsp;&nbsp;• Pro Zeile: <i>Stützweite (m), Lasttyp, max. Last (kg bzw. kg/m bei UDL), "
            "Durchbiegung bei dieser Last (mm)</i>"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "background: #2A2A2A; border: 1px solid #444; "
            "border-radius: 3px; padding: 6px; color: #C8C8C8;"
        )
        table_layout.addWidget(info_label)

        # Live-Status: was ist abgedeckt?
        self._coverage_label = QLabel()
        self._coverage_label.setWordWrap(True)
        self._coverage_label.setStyleSheet("padding: 4px 6px;")
        table_layout.addWidget(self._coverage_label)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Zeile")
        btn_add.clicked.connect(self._add_table_row)
        btn_del = QPushButton("− Zeile löschen")
        btn_del.clicked.connect(self._delete_table_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        table_layout.addLayout(btn_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Stützweite (m)", "Lasttyp", "Max. Last (kg)", "Durchbieg. (mm)"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.itemChanged.connect(self._update_coverage)
        table_layout.addWidget(self._table)
        splitter.addWidget(table_group)

        self._update_coverage()

        layout.addWidget(splitter, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF-Datenblatt öffnen", "", "PDF-Dateien (*.pdf)"
        )
        if path:
            self._load_pdf(path)

    def _load_pdf(self, path: str) -> None:
        self._pdf_path = path
        self._path_edit.setText(path)
        try:
            with open(path, "rb") as f:
                self._pdf_bytes = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Fehler", f"PDF konnte nicht gelesen werden:\n{e}")
            return

        parsed = parse_pdf(path)

        # Metadaten: nur LEERE Felder überschreiben, vom User ausgefüllte stehen lassen
        def fill_if_empty(line_edit: QLineEdit, value: str | None) -> None:
            if value and not line_edit.text().strip():
                line_edit.setText(value)

        fill_if_empty(self._name_edit, parsed.model_code)
        fill_if_empty(self._manuf_edit, parsed.manufacturer)
        fill_if_empty(self._model_edit, parsed.model_code)
        fill_if_empty(self._material_edit, parsed.material)
        if parsed.width_mm and self._width.value() == 0:
            self._width.setValue(parsed.width_mm)
        if parsed.height_mm and self._height.value() == 0:
            self._height.setValue(parsed.height_mm)
        if parsed.weight_per_meter_kg and self._weight.value() == 0:
            self._weight.setValue(parsed.weight_per_meter_kg)

        if parsed.parse_warnings:
            self._warnings_label.setText("\n".join(parsed.parse_warnings))
        else:
            self._warnings_label.setText("")

        # Lasttabelle: nur befüllen wenn leer ODER User bestätigt
        if parsed.load_entries:
            if self._table.rowCount() > 0:
                reply = QMessageBox.question(
                    self, "Bestehende Lasttabelle",
                    f"In der Tabelle stehen bereits {self._table.rowCount()} Zeilen.\n"
                    f"Aus dem PDF wurden {len(parsed.load_entries)} Einträge erkannt.\n\n"
                    "Manuell eingegebene Werte ersetzen?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                self._table.setRowCount(0)
            for entry in parsed.load_entries:
                self._add_table_row(entry)

    def _add_table_row(self, entry: LoadTableEntry = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        span_item = QTableWidgetItem(str(entry.span_m) if entry else "")
        self._table.setItem(row, 0, span_item)

        combo = QComboBox()
        for lt, label in _LOAD_TYPE_LABELS.items():
            combo.addItem(label, lt)
        if entry:
            idx = combo.findData(entry.load_type)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(self._update_coverage)
        self._table.setCellWidget(row, 1, combo)

        load_item = QTableWidgetItem(str(entry.max_load_kg) if entry else "")
        self._table.setItem(row, 2, load_item)

        defl_item = QTableWidgetItem(str(entry.deflection_mm) if entry else "")
        self._table.setItem(row, 3, defl_item)

        self._update_coverage()

    def _delete_table_row(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)
            self._update_coverage()

    def _update_coverage(self, *_args) -> None:
        """Live-Anzeige, welche Lasttypen und wie viele Stützweiten abgedeckt sind."""
        types_present: set[LoadType] = set()
        spans: set[float] = set()
        for row in range(self._table.rowCount()):
            try:
                span_text = self._table.item(row, 0).text().replace(",", ".") if self._table.item(row, 0) else ""
                combo = self._table.cellWidget(row, 1)
                if not span_text or not combo:
                    continue
                span = float(span_text)
                lt = combo.currentData()
                if lt is not None:
                    types_present.add(lt)
                    spans.add(span)
            except (ValueError, AttributeError):
                continue

        all_types = list(_LOAD_TYPE_LABELS.keys())
        missing = [_LOAD_TYPE_LABELS[t].split(" ")[0] for t in all_types if t not in types_present]
        present = [_LOAD_TYPE_LABELS[t].split(" ")[0] for t in all_types if t in types_present]

        if LoadType.UDL not in types_present:
            color = "#FF6666"
            status = "✗ <b>UDL fehlt</b> – Berechnung nicht möglich!"
        elif missing:
            color = "#FFCC44"
            status = (
                f"⚠ Vorhanden: {', '.join(present)} &nbsp;|&nbsp; "
                f"Fehlend: {', '.join(missing)} &nbsp;|&nbsp; "
                f"Stützweiten: {len(spans)}"
            )
        else:
            color = "#66DD66"
            status = (
                f"✓ Alle Lasttypen vorhanden &nbsp;|&nbsp; "
                f"Stützweiten: {len(spans)}"
                + ("" if len(spans) >= 2 else " &nbsp;(empfohlen: ≥ 2)")
            )

        self._coverage_label.setText(f"<span style='color:{color};'>{status}</span>")

    def _on_accept(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Fehler", "Bitte einen Namen für die Traverse eingeben.")
            return
        self.accept()

    def get_truss_type(self) -> TrussType:
        entries = []
        for row in range(self._table.rowCount()):
            try:
                span = float(self._table.item(row, 0).text().replace(",", "."))
                combo = self._table.cellWidget(row, 1)
                lt = combo.currentData()
                load = float(self._table.item(row, 2).text().replace(",", "."))
                defl = float(self._table.item(row, 3).text().replace(",", "."))
                entries.append(LoadTableEntry(span_m=span, load_type=lt,
                                              max_load_kg=load, deflection_mm=defl))
            except (ValueError, AttributeError):
                continue
        return TrussType(
            name=self._name_edit.text().strip(),
            manufacturer=self._manuf_edit.text().strip() or None,
            model_code=self._model_edit.text().strip() or None,
            material=self._material_edit.text().strip() or None,
            width_mm=self._width.value() or None,
            height_mm=self._height.value() or None,
            weight_per_meter_kg=self._weight.value() or None,
            source=TrussSource.DATASHEET,
            load_table=entries,
        )

    def get_pdf_bytes(self) -> bytes:
        return self._pdf_bytes

    def get_pdf_filename(self) -> str:
        import os
        return os.path.basename(self._pdf_path) if self._pdf_path else ""
