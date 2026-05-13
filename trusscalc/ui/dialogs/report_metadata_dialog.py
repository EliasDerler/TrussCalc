"""Dialog für Report-Metadaten (Sprache, Projektname, E-Mail) vor PDF-Erstellung."""
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QLineEdit, QComboBox,
    QDialogButtonBox, QLabel,
)
from PyQt6.QtCore import QSettings


@dataclass
class ReportMetadata:
    language: str            # "de" oder "en"
    project_name: str
    sub_project_name: str
    creator_email: str


class ReportMetadataDialog(QDialog):
    """Fragt Sprache, Projektnamen, Sub-Projektnamen und Ersteller-E-Mail ab."""

    SETTINGS_KEY_EMAIL = "report/creator_email"
    SETTINGS_KEY_LANG = "report/language"

    def __init__(self, default_project_name: str = "",
                 default_sub_name: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PDF-Report erstellen")
        self.resize(480, 260)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Report-Daten</b><br>"
            "<small>Diese Angaben erscheinen im Report-Header und der Fußzeile.</small>"
        ))

        form = QFormLayout()

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("Deutsch", "de")
        self._lang_combo.addItem("English", "en")
        form.addRow("Sprache / Language:", self._lang_combo)

        self._project_edit = QLineEdit()
        self._project_edit.setPlaceholderText("z. B. Projekt – EuroTruss XD")
        form.addRow("Projektname:", self._project_edit)

        self._subname_edit = QLineEdit()
        self._subname_edit.setPlaceholderText("z. B. Hauptbühne – Front Truss")
        form.addRow("Sub-Projektname:", self._subname_edit)

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText("name@firma.at")
        form.addRow("Ersteller-E-Mail:", self._email_edit)

        layout.addLayout(form)

        # Persistente Werte aus QSettings laden
        s = QSettings("NoiseGate", "TrussCalc")
        saved_email = s.value(self.SETTINGS_KEY_EMAIL, "")
        saved_lang = s.value(self.SETTINGS_KEY_LANG, "de")
        self._email_edit.setText(saved_email)
        idx = self._lang_combo.findData(saved_lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)

        self._project_edit.setText(default_project_name)
        self._subname_edit.setText(default_sub_name)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        # Validierung
        if not self._project_edit.text().strip():
            self._project_edit.setFocus()
            return
        # Speichern für nächstes Mal
        s = QSettings("NoiseGate", "TrussCalc")
        s.setValue(self.SETTINGS_KEY_EMAIL, self._email_edit.text().strip())
        s.setValue(self.SETTINGS_KEY_LANG, self._lang_combo.currentData())
        self.accept()

    def get_metadata(self) -> ReportMetadata:
        return ReportMetadata(
            language=self._lang_combo.currentData(),
            project_name=self._project_edit.text().strip(),
            sub_project_name=self._subname_edit.text().strip(),
            creator_email=self._email_edit.text().strip(),
        )
