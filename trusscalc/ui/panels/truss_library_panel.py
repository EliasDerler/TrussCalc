"""Linkes Bibliotheks-Panel für Traversen und Tower-Fundamente."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from trusscalc.core.models import TowerFoundationPreset, TrussType


class TrussLibraryPanel(QWidget):
    truss_selected = pyqtSignal(object)  # TrussType
    truss_double_clicked = pyqtSignal(object)  # TrussType
    foundation_selected = pyqtSignal(object)  # TowerFoundationPreset
    foundation_double_clicked = pyqtSignal(object)  # TowerFoundationPreset

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(300)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("<b>Traversenbibliothek</b>"))
        btn_row = QHBoxLayout()
        self._btn_pdf = QPushButton("PDF")
        self._btn_pdf.setToolTip("Datenblatt als PDF importieren (heuristisch)")
        self._btn_pdf_ai = QPushButton("PDF (KI)")
        self._btn_pdf_ai.setToolTip("Datenblatt mit PaddleOCR auslesen")
        self._btn_manual = QPushButton("Manuell")
        self._btn_manual.setToolTip("Traversentyp manuell anlegen")
        btn_row.addWidget(self._btn_pdf)
        btn_row.addWidget(self._btn_pdf_ai)
        btn_row.addWidget(self._btn_manual)
        layout.addLayout(btn_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemClicked.connect(self._on_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree, 1)

        layout.addWidget(QLabel("<b>Fundamentbibliothek</b>"))
        foundation_btn_row = QHBoxLayout()
        self._btn_foundation_new = QPushButton("Neu")
        self._btn_foundation_new.setToolTip("Neues Fundament für Tower anlegen")
        self._btn_foundation_edit = QPushButton("Bearbeiten")
        self._btn_foundation_edit.setToolTip("Ausgewähltes Fundament bearbeiten")
        self._btn_foundation_delete = QPushButton("Löschen")
        self._btn_foundation_delete.setToolTip("Ausgewähltes Fundament löschen")
        self._btn_foundation_new.clicked.connect(self._add_foundation)
        self._btn_foundation_edit.clicked.connect(self._edit_selected_foundation)
        self._btn_foundation_delete.clicked.connect(self._delete_selected_foundation)
        foundation_btn_row.addWidget(self._btn_foundation_new)
        foundation_btn_row.addWidget(self._btn_foundation_edit)
        foundation_btn_row.addWidget(self._btn_foundation_delete)
        layout.addLayout(foundation_btn_row)

        self._foundation_tree = QTreeWidget()
        self._foundation_tree.setHeaderHidden(True)
        self._foundation_tree.setMaximumHeight(170)
        self._foundation_tree.itemClicked.connect(self._on_foundation_click)
        self._foundation_tree.itemDoubleClicked.connect(self._on_foundation_double_click)
        self._foundation_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._foundation_tree.customContextMenuRequested.connect(self._foundation_context_menu)
        layout.addWidget(self._foundation_tree, 0)

    def refresh(self) -> None:
        from trusscalc.database.db_manager import list_truss_types
        self._tree.clear()
        groups: dict[str, list[TrussType]] = {}
        for truss in list_truss_types():
            groups.setdefault(truss.manufacturer or "Unbekannt", []).append(truss)
        for manufacturer, types in sorted(groups.items()):
            parent = QTreeWidgetItem(self._tree, [manufacturer])
            parent.setExpanded(True)
            for truss in sorted(types, key=lambda item: item.name):
                child = QTreeWidgetItem(parent, [truss.name])
                child.setData(0, Qt.ItemDataRole.UserRole, truss)
        self.refresh_foundations()

    def refresh_foundations(self) -> None:
        from trusscalc.database.db_manager import list_tower_foundations
        self._foundation_tree.clear()
        foundations = list_tower_foundations()
        if not foundations:
            item = QTreeWidgetItem(self._foundation_tree, ["Keine Fundamente - mit 'Neu' anlegen"])
            item.setToolTip(0, "Tower benötigen zuerst ein Fundament aus dieser Bibliothek.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            return
        for foundation in foundations:
            item = QTreeWidgetItem(self._foundation_tree, [foundation.name])
            item.setData(0, Qt.ItemDataRole.UserRole, foundation)

    def _on_click(self, item: QTreeWidgetItem, col: int) -> None:
        truss = item.data(0, Qt.ItemDataRole.UserRole)
        if truss:
            self.truss_selected.emit(truss)

    def _on_double_click(self, item: QTreeWidgetItem, col: int) -> None:
        truss = item.data(0, Qt.ItemDataRole.UserRole)
        if truss:
            self.truss_double_clicked.emit(truss)

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if not item:
            return
        truss = item.data(0, Qt.ItemDataRole.UserRole)
        if not truss:
            return
        menu = QMenu(self)
        act_edit = QAction("Bearbeiten...", self)
        act_del = QAction("Löschen", self)
        menu.addAction(act_edit)
        menu.addAction(act_del)
        action = menu.exec(self._tree.mapToGlobal(pos))
        if action == act_edit:
            self._edit_truss(truss)
        elif action == act_del:
            self._delete_truss(truss)

    def _edit_truss(self, truss: TrussType) -> None:
        from trusscalc.database.db_manager import (
            get_connection, save_truss_pdf, save_truss_type,
        )
        from trusscalc.ui.dialogs.manual_truss_dialog import ManualTrussDialog
        dlg = ManualTrussDialog(truss, self)
        if dlg.exec():
            updated = dlg.get_truss_type()
            tid = save_truss_type(updated)
            if dlg.get_pdf_bytes():
                save_truss_pdf(tid, dlg.get_pdf_bytes(), dlg.get_pdf_filename())
            elif dlg.should_remove_pdf():
                with get_connection() as conn:
                    conn.execute("DELETE FROM truss_pdfs WHERE truss_type_id=?", (tid,))
            self.refresh()

    def _delete_truss(self, truss: TrussType) -> None:
        from trusscalc.database.db_manager import delete_truss_type
        reply = QMessageBox.question(
            self,
            "Löschen",
            f"Traversentyp '{truss.name}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_truss_type(truss.id)
            self.refresh()

    def _selected_foundation(self) -> TowerFoundationPreset | None:
        item = self._foundation_tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _on_foundation_click(self, item: QTreeWidgetItem, col: int) -> None:
        foundation = item.data(0, Qt.ItemDataRole.UserRole)
        if foundation:
            self.foundation_selected.emit(foundation)

    def _on_foundation_double_click(self, item: QTreeWidgetItem, col: int) -> None:
        foundation = item.data(0, Qt.ItemDataRole.UserRole)
        if foundation:
            self.foundation_double_clicked.emit(foundation)

    def _foundation_context_menu(self, pos) -> None:
        item = self._foundation_tree.itemAt(pos)
        if not item:
            return
        foundation = item.data(0, Qt.ItemDataRole.UserRole)
        if not foundation:
            return
        menu = QMenu(self)
        act_use = QAction("Platzieren", self)
        act_edit = QAction("Bearbeiten...", self)
        act_del = QAction("Löschen", self)
        menu.addAction(act_use)
        menu.addAction(act_edit)
        menu.addAction(act_del)
        action = menu.exec(self._foundation_tree.mapToGlobal(pos))
        if action == act_use:
            self.foundation_double_clicked.emit(foundation)
        elif action == act_edit:
            self._edit_foundation(foundation)
        elif action == act_del:
            self._delete_foundation(foundation)

    def _add_foundation(self) -> None:
        from trusscalc.database.db_manager import save_tower_foundation
        from trusscalc.ui.dialogs.foundation_dialog import FoundationDialog
        dlg = FoundationDialog(parent=self)
        if dlg.exec():
            save_tower_foundation(dlg.get_preset())
            self.refresh_foundations()

    def _edit_selected_foundation(self) -> None:
        foundation = self._selected_foundation()
        if foundation:
            self._edit_foundation(foundation)

    def _delete_selected_foundation(self) -> None:
        foundation = self._selected_foundation()
        if foundation:
            self._delete_foundation(foundation)

    def _edit_foundation(self, foundation: TowerFoundationPreset) -> None:
        from trusscalc.database.db_manager import save_tower_foundation
        from trusscalc.ui.dialogs.foundation_dialog import FoundationDialog
        dlg = FoundationDialog(foundation, self)
        if dlg.exec():
            save_tower_foundation(dlg.get_preset())
            self.refresh_foundations()

    def _delete_foundation(self, foundation: TowerFoundationPreset) -> None:
        from trusscalc.database.db_manager import delete_tower_foundation
        reply = QMessageBox.question(
            self,
            "Löschen",
            f"Fundament '{foundation.name}' wirklich löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_tower_foundation(foundation.id)
            self.refresh_foundations()
