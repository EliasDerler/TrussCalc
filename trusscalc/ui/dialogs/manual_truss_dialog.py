"""Dialog zum manuellen Anlegen eines Traversentyps."""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDialogButtonBox, QMessageBox, QGroupBox, QHBoxLayout, QLabel, QFileDialog,
)
from trusscalc.core.models import TrussType, TrussSource, LoadTableEntry, LoadType

_LOAD_TYPE_LABELS = {
    LoadType.UDL: "UDL (Streckenlast)",
    LoadType.CPL: "CPL (Mittelpunkt)",
    LoadType.THIRD: "1/3-Punkt",
    LoadType.QUARTER: "1/4-Punkt",
    LoadType.FIFTH: "1/5-Punkt",
}


class ManualTrussDialog(QDialog):
    def __init__(self, truss: TrussType = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Traversentyp manuell anlegen" if truss is None else "Traversentyp bearbeiten")
        self.resize(720, 640)
        self._truss = truss
        # PDF-Status
        self._pdf_bytes: bytes = b""
        self._pdf_filename: str = ""
        self._pdf_remove_flag: bool = False
        self._pdf_existing_in_db: bool = False
        self._build_ui()
        if truss:
            self._fill_from_truss(truss)
            self._load_existing_pdf_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # PDF-Sektion (Datenblatt anhängen / ersetzen / entfernen)
        pdf_group = QGroupBox("Datenblatt (PDF) – optional")
        pdf_layout = QHBoxLayout(pdf_group)
        self._pdf_status = QLabel("Kein PDF angehängt")
        self._pdf_status.setStyleSheet("color: #AAAAAA;")
        btn_attach = QPushButton("PDF anhängen…")
        btn_attach.clicked.connect(self._attach_pdf)
        self._btn_remove_pdf = QPushButton("PDF entfernen")
        self._btn_remove_pdf.clicked.connect(self._remove_pdf)
        self._btn_remove_pdf.setEnabled(False)
        pdf_layout.addWidget(self._pdf_status, 1)
        pdf_layout.addWidget(btn_attach)
        pdf_layout.addWidget(self._btn_remove_pdf)
        layout.addWidget(pdf_group)

        meta_group = QGroupBox("Allgemeine Daten")
        form = QFormLayout(meta_group)

        self._name = QLineEdit(); form.addRow("Name*:", self._name)
        self._manuf = QLineEdit(); form.addRow("Hersteller:", self._manuf)
        self._model = QLineEdit(); form.addRow("Modell:", self._model)
        self._material = QLineEdit(); form.addRow("Material:", self._material)

        self._width = QDoubleSpinBox(); self._width.setRange(0, 5000); self._width.setSuffix(" mm")
        form.addRow("Breite:", self._width)
        self._height = QDoubleSpinBox(); self._height.setRange(0, 5000); self._height.setSuffix(" mm")
        form.addRow("Höhe:", self._height)
        self._weight = QDoubleSpinBox(); self._weight.setRange(0, 999); self._weight.setSuffix(" kg/m"); self._weight.setDecimals(2)
        form.addRow("Eigengewicht:", self._weight)

        layout.addWidget(meta_group)

        table_group = QGroupBox("Lasttabelle")
        table_layout = QVBoxLayout(table_group)
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Zeile"); btn_add.clicked.connect(self._add_row)
        btn_del = QPushButton("− Zeile"); btn_del.clicked.connect(self._del_row)
        btn_row.addWidget(btn_add); btn_row.addWidget(btn_del); btn_row.addStretch()
        table_layout.addLayout(btn_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Stützweite (m)", "Lasttyp", "Max. Last (kg)", "Durchbieg. (mm)"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self._table)
        layout.addWidget(table_group)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_existing_pdf_status(self) -> None:
        """Prüft, ob in der DB bereits ein PDF für diese Traverse hinterlegt ist."""
        if not self._truss or self._truss.id is None:
            return
        from trusscalc.database.db_manager import load_truss_pdf
        pdf = load_truss_pdf(self._truss.id)
        if pdf:
            self._pdf_existing_in_db = True
            self._pdf_status.setText(
                f"<span style='color:#66DD66;'>✓ PDF bereits in DB hinterlegt "
                f"({len(pdf)//1024} KB)</span>"
            )
            self._btn_remove_pdf.setEnabled(True)

    def _attach_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF-Datenblatt anhängen", "", "PDF-Dateien (*.pdf)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                self._pdf_bytes = f.read()
        except OSError as e:
            QMessageBox.warning(self, "Fehler", f"PDF konnte nicht gelesen werden:\n{e}")
            return
        self._pdf_filename = os.path.basename(path)
        self._pdf_remove_flag = False
        self._pdf_status.setText(
            f"<span style='color:#66DD66;'>✓ Neues PDF: {self._pdf_filename} "
            f"({len(self._pdf_bytes)//1024} KB)</span>"
        )
        self._btn_remove_pdf.setEnabled(True)

    def _remove_pdf(self) -> None:
        # Lokal angehängtes PDF zurücknehmen
        if self._pdf_bytes:
            self._pdf_bytes = b""
            self._pdf_filename = ""
            if self._pdf_existing_in_db:
                self._pdf_status.setText(
                    "<span style='color:#66DD66;'>✓ PDF in DB hinterlegt</span>"
                )
            else:
                self._pdf_status.setText("Kein PDF angehängt")
                self._btn_remove_pdf.setEnabled(False)
            return
        # Bereits in DB hinterlegtes PDF zum Löschen markieren
        if self._pdf_existing_in_db:
            self._pdf_remove_flag = True
            self._pdf_existing_in_db = False
            self._pdf_status.setText(
                "<span style='color:#FF8844;'>⚠ PDF wird beim Speichern aus DB entfernt</span>"
            )
            self._btn_remove_pdf.setEnabled(False)

    def get_pdf_bytes(self) -> bytes:
        return self._pdf_bytes

    def get_pdf_filename(self) -> str:
        return self._pdf_filename

    def should_remove_pdf(self) -> bool:
        return self._pdf_remove_flag

    def _fill_from_truss(self, t: TrussType) -> None:
        self._name.setText(t.name or "")
        self._manuf.setText(t.manufacturer or "")
        self._model.setText(t.model_code or "")
        self._material.setText(t.material or "")
        if t.width_mm: self._width.setValue(t.width_mm)
        if t.height_mm: self._height.setValue(t.height_mm)
        if t.weight_per_meter_kg: self._weight.setValue(t.weight_per_meter_kg)
        for e in t.load_table:
            self._add_row(e)

    def _add_row(self, entry: LoadTableEntry = None) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(str(entry.span_m) if entry else ""))
        combo = QComboBox()
        for lt, lbl in _LOAD_TYPE_LABELS.items():
            combo.addItem(lbl, lt)
        if entry:
            idx = combo.findData(entry.load_type)
            if idx >= 0: combo.setCurrentIndex(idx)
        self._table.setCellWidget(r, 1, combo)
        self._table.setItem(r, 2, QTableWidgetItem(str(entry.max_load_kg) if entry else ""))
        self._table.setItem(r, 3, QTableWidgetItem(str(entry.deflection_mm) if entry else ""))

    def _del_row(self) -> None:
        r = self._table.currentRow()
        if r >= 0: self._table.removeRow(r)

    def _accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "Fehler", "Name ist erforderlich.")
            return
        self.accept()

    def get_truss_type(self) -> TrussType:
        entries = []
        for r in range(self._table.rowCount()):
            try:
                span = float(self._table.item(r, 0).text().replace(",", "."))
                lt = self._table.cellWidget(r, 1).currentData()
                load = float(self._table.item(r, 2).text().replace(",", "."))
                defl = float(self._table.item(r, 3).text().replace(",", "."))
                entries.append(LoadTableEntry(span_m=span, load_type=lt, max_load_kg=load, deflection_mm=defl))
            except (ValueError, AttributeError):
                continue
        tid = self._truss.id if self._truss else None
        return TrussType(
            id=tid,
            name=self._name.text().strip(),
            manufacturer=self._manuf.text().strip() or None,
            model_code=self._model.text().strip() or None,
            material=self._material.text().strip() or None,
            width_mm=self._width.value() or None,
            height_mm=self._height.value() or None,
            weight_per_meter_kg=self._weight.value() or None,
            source=TrussSource.MANUAL,
            load_table=entries,
        )
