"""Traversenbibliothek-Panel (links)."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QHBoxLayout, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

from trusscalc.core.models import TrussType
from trusscalc import database


class TrussLibraryPanel(QWidget):
    truss_selected = pyqtSignal(object)  # TrussType
    truss_double_clicked = pyqtSignal(object)  # TrussType (use in project)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("<b>Traversenbibliothek</b>"))

        btn_row = QHBoxLayout()
        btn_pdf = QPushButton("PDF")
        btn_pdf.setToolTip("Datenblatt als PDF importieren (heuristisch)")
        btn_pdf_ai = QPushButton("PDF (KI)")
        btn_pdf_ai.setToolTip("Datenblatt mit PaddleOCR auslesen "
                               "(genauer, aber ~ 2 Min Laufzeit)")
        btn_manual = QPushButton("Manuell")
        btn_manual.setToolTip("Traversentyp manuell anlegen")
        btn_row.addWidget(btn_pdf)
        btn_row.addWidget(btn_pdf_ai)
        btn_row.addWidget(btn_manual)
        layout.addLayout(btn_row)

        self._btn_pdf = btn_pdf
        self._btn_pdf_ai = btn_pdf_ai
        self._btn_manual = btn_manual

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemClicked.connect(self._on_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree, 1)

    def refresh(self) -> None:
        from trusscalc.database.db_manager import list_truss_types
        self._tree.clear()
        truss_types = list_truss_types()

        # Gruppieren nach Hersteller
        groups: dict[str, list[TrussType]] = {}
        for t in truss_types:
            key = t.manufacturer or "Unbekannt"
            groups.setdefault(key, []).append(t)

        for manuf, types in sorted(groups.items()):
            parent = QTreeWidgetItem(self._tree, [manuf])
            parent.setExpanded(True)
            for t in sorted(types, key=lambda x: x.name):
                child = QTreeWidgetItem(parent, [t.name])
                child.setData(0, Qt.ItemDataRole.UserRole, t)

    def _on_click(self, item: QTreeWidgetItem, col: int) -> None:
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if t:
            self.truss_selected.emit(t)

    def _on_double_click(self, item: QTreeWidgetItem, col: int) -> None:
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if t:
            self.truss_double_clicked.emit(t)

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return
        t = item.data(0, Qt.ItemDataRole.UserRole)
        if not t:
            return
        menu = QMenu(self)
        act_edit = QAction("Bearbeiten…", self)
        act_del = QAction("Löschen", self)
        menu.addAction(act_edit)
        menu.addAction(act_del)
        action = menu.exec(self._tree.mapToGlobal(pos))
        if action == act_edit:
            self._edit_truss(t)
        elif action == act_del:
            self._delete_truss(t)

    def _edit_truss(self, truss: TrussType) -> None:
        from trusscalc.ui.dialogs.manual_truss_dialog import ManualTrussDialog
        from trusscalc.database.db_manager import (
            save_truss_type, save_truss_pdf, get_connection,
        )
        dlg = ManualTrussDialog(truss, self)
        if dlg.exec():
            updated = dlg.get_truss_type()
            tid = save_truss_type(updated)
            # PDF-Anhang behandeln
            if dlg.get_pdf_bytes():
                save_truss_pdf(tid, dlg.get_pdf_bytes(), dlg.get_pdf_filename())
            elif dlg.should_remove_pdf():
                with get_connection() as conn:
                    conn.execute("DELETE FROM truss_pdfs WHERE truss_type_id=?", (tid,))
            self.refresh()

    def _delete_truss(self, truss: TrussType) -> None:
        from trusscalc.database.db_manager import delete_truss_type
        reply = QMessageBox.question(self, "Löschen",
                                     f"Traversentyp '{truss.name}' wirklich löschen?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_truss_type(truss.id)
            self.refresh()
