"""
Hauptfenster von TrussCalc.
LTSpice-inspiriertes Layout: Menüleiste, Toolbar, Bibliothek-Panel (links),
2D-Canvas (Mitte), Eigenschaften-Panel (rechts), Statusleiste.
"""
import copy
import uuid
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QToolBar,
    QStatusBar, QMessageBox, QFileDialog, QInputDialog, QLabel,
    QComboBox, QSplitter, QDialog, QApplication, QProgressDialog,
    QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox,
    QPushButton, QTabWidget,
)
from PyQt6.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from trusscalc.core.models import (
    Project, ProjectBundle, TrussType, TrussSection, Support, PointLoad, DistributedLoad,
    UnitSystem, CalculationResult,
)
from trusscalc.core import calculator
from trusscalc.core.interpolator import LoadTableInterpolator
from trusscalc.ui.canvas.truss_canvas import TrussCanvas
from trusscalc.ui.canvas.canvas_tools import CanvasTool
from trusscalc.ui.panels.truss_library_panel import TrussLibraryPanel
from trusscalc.ui.panels.properties_panel import PropertiesPanel
from trusscalc.ui.dialogs.support_dialog import SupportDialog
from trusscalc.ui.dialogs.load_dialog import PointLoadDialog, DistributedLoadDialog
from trusscalc.ui.dialogs.section_dialog import SectionDialog
from trusscalc.version import APP_VERSION


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TrussCalc")
        self.resize(1280, 780)
        self._project_bundle: Optional[ProjectBundle] = None
        self._project: Optional[Project] = None
        self._truss_type: Optional[TrussType] = None
        self._last_result: Optional[CalculationResult] = None
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._active_subproject_index = 0
        self._subproject_truss_types: list[Optional[TrussType]] = []
        self._subproject_results: list[Optional[CalculationResult]] = []
        self._subproject_undo_stacks: list[list] = []
        self._subproject_redo_stacks: list[list] = []
        self._updating_tabs = False
        self._project_path: Optional[str] = None
        self._update_worker = None
        self._pdf_worker = None
        self._copy_templates: list = []
        self._setup_ui()
        self._apply_dark_theme()
        self._new_project()
        QTimer.singleShot(1500, self._start_update_check)

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_central()

    def _setup_menu(self) -> None:
        mb = self.menuBar()

        # Datei
        file_menu = mb.addMenu("&Datei")
        file_menu.addAction(self._action("Neues Projekt", self._new_project, "Ctrl+N"))
        file_menu.addAction(self._action("Projekt öffnen…", self._open_project, "Ctrl+O"))
        file_menu.addAction(self._action("Projekt speichern", self._save_project, "Ctrl+S"))
        file_menu.addAction(self._action("Projekt speichern unter…", self._save_project_as, "Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Default-Bibliothek importieren…",
                                          self._import_default_library))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Beenden", self.close, "Ctrl+Q"))

        # Bearbeiten
        edit_menu = mb.addMenu("&Bearbeiten")
        edit_menu.addAction(self._action("Rückgängig", self._undo, "Ctrl+Z"))
        edit_menu.addAction(self._action("Wiederholen", self._redo, "Ctrl+Y"))
        edit_menu.addAction(self._action("Auswahl kopieren", self._copy_selected, "Ctrl+C"))
        edit_menu.addAction(self._action("Kopie platzieren", self._paste_copy, "Ctrl+V"))
        edit_menu.addAction(self._action("Auswahl spiegeln", self._mirror_selected, "Ctrl+M"))
        edit_menu.addAction(self._action("Alles zurücksetzen", self._reset_canvas))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("Ausgewähltes löschen", self._delete_selected, "Del"))

        # Simulation
        sim_menu = mb.addMenu("&Simulation")
        sim_menu.addAction(self._action("Berechnen", self._run_calculation, "F5"))
        sim_menu.addAction(self._action("Ergebnisse löschen", self._clear_results, "F6"))

        # Ausgabe
        out_menu = mb.addMenu("&Ausgabe")
        out_menu.addAction(self._action("PDF-Report erstellen…", self._generate_pdf))

        # Ansicht
        view_menu = mb.addMenu("&Ansicht")
        view_menu.addAction(self._action("Ansicht anpassen", self._fit_view, "Space"))

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Werkzeuge")
        tb.setIconSize(QSize(22, 22))
        tb.setMovable(False)
        self.addToolBar(tb)

        def tool_action(label: str, tool: CanvasTool, shortcut: str = "") -> QAction:
            act = QAction(label, self)
            act.setCheckable(True)
            if shortcut:
                act.setShortcut(shortcut)
            act.triggered.connect(lambda checked, t=tool: self._set_tool(t))
            return act

        self._act_select = tool_action("▶ Auswahl", CanvasTool.SELECT)
        self._act_section = tool_action("━ Abschnitt", CanvasTool.ADD_SECTION, "T")
        self._act_support = tool_action("▽ Auflager", CanvasTool.ADD_SUPPORT, "A")
        self._act_point = tool_action("↓ Punktlast", CanvasTool.ADD_POINT_LOAD, "P")
        self._act_dist = tool_action("⇊ Streckenlast", CanvasTool.ADD_DIST_LOAD, "S")

        self._tool_actions = [
            self._act_select, self._act_section,
            self._act_support, self._act_point, self._act_dist,
        ]
        for act in self._tool_actions:
            tb.addAction(act)

        tb.addSeparator()
        tb.addAction(self._action("Kopieren", self._copy_selected))
        tb.addAction(self._action("Spiegeln", self._mirror_selected))
        tb.addSeparator()
        tb.addAction(self._action("▶▶ Berechnen [F5]", self._run_calculation))
        tb.addAction(self._action("✕ Reset", self._clear_results))

        tb.addSeparator()
        tb.addWidget(QLabel("  Einheit: "))
        self._unit_combo = QComboBox()
        self._unit_combo.addItem("kg", UnitSystem.KG_M)
        self._unit_combo.addItem("N / kN", UnitSystem.N_M)
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        tb.addWidget(self._unit_combo)

        self._act_select.setChecked(True)

    def _setup_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._library = TrussLibraryPanel()
        self._library.truss_double_clicked.connect(self._use_truss_type)
        self._library._btn_pdf.clicked.connect(self._import_pdf)
        self._library._btn_pdf_ai.clicked.connect(self._import_pdf_ai)
        self._library._btn_manual.clicked.connect(self._add_manual_truss)

        self._canvas = TrussCanvas()
        self._canvas.request_support_dialog.connect(self._on_add_support)
        self._canvas.request_point_load_dialog.connect(self._on_add_point_load)
        self._canvas.request_dist_load_dialog.connect(self._on_add_dist_load)
        self._canvas.request_section_dialog.connect(self._on_add_section)
        self._canvas.element_selected.connect(self._on_element_selected)
        self._canvas.element_deleted.connect(self._on_element_deleted)
        self._canvas.element_context_requested.connect(self._on_edit_element)
        self._canvas.copy_place_requested.connect(self._place_copy_at)
        self._canvas.copy_cancel_requested.connect(
            lambda: self._status.showMessage("Kopieren abgebrochen")
        )
        self._canvas.copy_requested.connect(self._copy_selected)
        self._canvas.paste_requested.connect(self._paste_copy)
        self._canvas.mirror_requested.connect(self._mirror_selected)
        self._canvas.delete_requested.connect(self._delete_selected)
        self._canvas.status_message.connect(self._status.showMessage)

        self._props = PropertiesPanel()
        self._props.edit_requested.connect(self._on_edit_element)
        self._props.delete_requested.connect(self._on_element_deleted)

        self._tabs = QTabWidget()
        self._tabs.setMovable(True)
        self._tabs.setMaximumHeight(34)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().tabMoved.connect(self._on_tab_moved)

        tab_buttons = QHBoxLayout()
        tab_buttons.setContentsMargins(0, 0, 0, 0)
        self._btn_tab_new = QPushButton("Neu")
        self._btn_tab_rename = QPushButton("Umbenennen")
        self._btn_tab_duplicate = QPushButton("Duplizieren")
        self._btn_tab_delete = QPushButton("Löschen")
        self._btn_tab_new.clicked.connect(self._add_subproject_tab)
        self._btn_tab_rename.clicked.connect(self._rename_subproject_tab)
        self._btn_tab_duplicate.clicked.connect(self._duplicate_subproject_tab)
        self._btn_tab_delete.clicked.connect(self._delete_subproject_tab)
        for btn in (
            self._btn_tab_new, self._btn_tab_rename,
            self._btn_tab_duplicate, self._btn_tab_delete,
        ):
            tab_buttons.addWidget(btn)
        tab_buttons.addStretch(1)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)
        center_layout.addWidget(self._tabs)
        center_layout.addLayout(tab_buttons)
        center_layout.addWidget(self._canvas, 1)

        splitter.addWidget(self._library)
        splitter.addWidget(center)
        splitter.addWidget(self._props)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

    def _setup_statusbar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._lbl_truss = QLabel("Kein Traversentyp ausgewählt")
        self._status.addPermanentWidget(self._lbl_truss)
        self._status.showMessage("Bereit – Traversentyp aus Bibliothek auswählen oder importieren")

    # ── Werkzeuge ─────────────────────────────────────────────────────────────

    def _set_tool(self, tool: CanvasTool) -> None:
        for act in self._tool_actions:
            act.setChecked(False)
        mapping = {
            CanvasTool.SELECT: self._act_select,
            CanvasTool.ADD_SECTION: self._act_section,
            CanvasTool.ADD_SUPPORT: self._act_support,
            CanvasTool.ADD_POINT_LOAD: self._act_point,
            CanvasTool.ADD_DIST_LOAD: self._act_dist,
        }
        mapping[tool].setChecked(True)
        self._canvas.set_tool(tool)
        self._status.showMessage({
            CanvasTool.SELECT: "Auswahl-Werkzeug aktiv",
            CanvasTool.ADD_SECTION: "Klick auf Canvas: Traversenabschnitt hinzufügen",
            CanvasTool.ADD_SUPPORT: "Klick auf Canvas: Auflager setzen",
            CanvasTool.ADD_POINT_LOAD: "Klick auf Canvas: Punktlast setzen",
            CanvasTool.ADD_DIST_LOAD: "Klick auf Canvas: Streckenlast setzen",
        }[tool])

    def _create_empty_subproject(self, name: str = "Sub-Projekt 1") -> Project:
        unit = self._unit_combo.currentData() if hasattr(self, "_unit_combo") else UnitSystem.KG_M
        return Project(name=name, truss_type_id=0, unit_system=unit)

    def _load_project_bundle(self, bundle: ProjectBundle) -> None:
        if not bundle.subprojects:
            bundle.subprojects.append(self._create_empty_subproject())
        self._project_bundle = bundle
        self._subproject_truss_types = [None for _ in bundle.subprojects]
        self._subproject_results = [None for _ in bundle.subprojects]
        self._subproject_undo_stacks = [[] for _ in bundle.subprojects]
        self._subproject_redo_stacks = [[] for _ in bundle.subprojects]
        self._active_subproject_index = 0
        self._refresh_tabs()
        self._activate_subproject(0)

    def _refresh_tabs(self) -> None:
        self._updating_tabs = True
        self._tabs.clear()
        if self._project_bundle:
            for project in self._project_bundle.subprojects:
                self._tabs.addTab(QWidget(), project.name or "Sub-Projekt")
            self._tabs.setCurrentIndex(self._active_subproject_index)
        self._updating_tabs = False

    def _commit_active_subproject_state(self) -> None:
        if not self._project_bundle or self._project is None:
            return
        idx = self._active_subproject_index
        if 0 <= idx < len(self._project_bundle.subprojects):
            self._project_bundle.subprojects[idx] = self._project
            self._subproject_truss_types[idx] = self._truss_type
            self._subproject_results[idx] = self._last_result
            self._subproject_undo_stacks[idx] = self._undo_stack
            self._subproject_redo_stacks[idx] = self._redo_stack

    def _activate_subproject(self, idx: int) -> None:
        if not self._project_bundle or not (0 <= idx < len(self._project_bundle.subprojects)):
            return
        self._active_subproject_index = idx
        self._project = self._project_bundle.subprojects[idx]
        self._truss_type = self._subproject_truss_types[idx]
        if self._truss_type is None and self._project.truss_type_id:
            from trusscalc.database.db_manager import load_truss_type
            self._truss_type = load_truss_type(self._project.truss_type_id)
            self._subproject_truss_types[idx] = self._truss_type
        self._last_result = self._subproject_results[idx]
        self._undo_stack = self._subproject_undo_stacks[idx]
        self._redo_stack = self._subproject_redo_stacks[idx]
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        if self._truss_type:
            self._lbl_truss.setText(f"Traversentyp: {self._truss_type.display_name}")
        else:
            self._lbl_truss.setText("Kein Traversentyp ausgewählt")
        if self._last_result and self._truss_type:
            interp = LoadTableInterpolator(self._truss_type)
            ei = interp.effective_ei(self._project.total_length_m)
            sw = self._truss_type.weight_per_meter_kg if self._truss_type.has_weight else None
            self._canvas.show_results(self._last_result, ei or 1.0, sw)
        self._update_window_title()

    def _on_tab_changed(self, idx: int) -> None:
        if self._updating_tabs or idx < 0 or idx == self._active_subproject_index:
            return
        self._commit_active_subproject_state()
        self._activate_subproject(idx)

    def _on_tab_moved(self, from_idx: int, to_idx: int) -> None:
        if (
            self._updating_tabs
            or not self._project_bundle
            or from_idx == to_idx
            or not (0 <= from_idx < len(self._project_bundle.subprojects))
            or not (0 <= to_idx < len(self._project_bundle.subprojects))
        ):
            return
        self._commit_active_subproject_state()
        active_project = self._project

        def move_item(items: list) -> None:
            item = items.pop(from_idx)
            items.insert(to_idx, item)

        move_item(self._project_bundle.subprojects)
        move_item(self._subproject_truss_types)
        move_item(self._subproject_results)
        move_item(self._subproject_undo_stacks)
        move_item(self._subproject_redo_stacks)

        try:
            new_active = self._project_bundle.subprojects.index(active_project)
        except ValueError:
            new_active = self._tabs.currentIndex()
        self._updating_tabs = True
        self._tabs.setCurrentIndex(new_active)
        self._updating_tabs = False
        self._activate_subproject(new_active)
        self._status.showMessage("Sub-Projekt-Reihenfolge aktualisiert")

    def _add_subproject_tab(self) -> None:
        if not self._project_bundle:
            self._new_project()
        name = f"Sub-Projekt {len(self._project_bundle.subprojects) + 1}"
        project = self._create_empty_subproject(name)
        self._commit_active_subproject_state()
        self._project_bundle.subprojects.append(project)
        self._subproject_truss_types.append(None)
        self._subproject_results.append(None)
        self._subproject_undo_stacks.append([])
        self._subproject_redo_stacks.append([])
        self._active_subproject_index = len(self._project_bundle.subprojects) - 1
        self._refresh_tabs()
        self._activate_subproject(self._active_subproject_index)

    def _rename_subproject_tab(self) -> None:
        if not self._project:
            return
        name, ok = QInputDialog.getText(
            self, "Sub-Projekt umbenennen", "Name:",
            text=self._project.name or "Sub-Projekt",
        )
        if not ok or not name.strip():
            return
        self._project.name = name.strip()
        self._commit_active_subproject_state()
        self._refresh_tabs()
        self._status.showMessage(f"Sub-Projekt umbenannt: {self._project.name}")

    def _duplicate_subproject_tab(self) -> None:
        if not self._project_bundle or not self._project:
            return
        self._commit_active_subproject_state()
        clone = copy.deepcopy(self._project)
        clone.name = f"{self._project.name or 'Sub-Projekt'} Kopie"
        self._regenerate_element_ids(clone)
        idx = self._active_subproject_index + 1
        self._project_bundle.subprojects.insert(idx, clone)
        self._subproject_truss_types.insert(idx, copy.deepcopy(self._truss_type))
        self._subproject_results.insert(idx, None)
        self._subproject_undo_stacks.insert(idx, [])
        self._subproject_redo_stacks.insert(idx, [])
        self._active_subproject_index = idx
        self._refresh_tabs()
        self._activate_subproject(idx)

    def _delete_subproject_tab(self) -> None:
        if not self._project_bundle or len(self._project_bundle.subprojects) <= 1:
            QMessageBox.information(self, "Sub-Projekt löschen", "Mindestens ein Sub-Projekt muss bestehen bleiben.")
            return
        idx = self._active_subproject_index
        reply = QMessageBox.question(
            self, "Sub-Projekt löschen",
            f"Sub-Projekt '{self._project.name}' löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self._project_bundle.subprojects[idx]
        del self._subproject_truss_types[idx]
        del self._subproject_results[idx]
        del self._subproject_undo_stacks[idx]
        del self._subproject_redo_stacks[idx]
        self._active_subproject_index = max(0, min(idx, len(self._project_bundle.subprojects) - 1))
        self._refresh_tabs()
        self._activate_subproject(self._active_subproject_index)

    @staticmethod
    def _regenerate_element_ids(project: Project) -> None:
        for collection in (
            project.sections, project.supports,
            project.point_loads, project.distributed_loads,
        ):
            for element in collection:
                element.id = str(uuid.uuid4())

    # ── Projekt-Verwaltung ────────────────────────────────────────────────────

    def _new_project(self) -> None:
        first = self._create_empty_subproject()
        self._project_bundle = ProjectBundle(
            name="Projekt",
            unit_system=self._unit_combo.currentData(),
            subprojects=[first],
        )
        self._subproject_truss_types = [None]
        self._subproject_results = [None]
        self._subproject_undo_stacks = [[]]
        self._subproject_redo_stacks = [[]]
        self._active_subproject_index = 0
        self._project_path = None
        self._refresh_tabs()
        self._activate_subproject(0)
        self._status.showMessage("Neues Projekt – Traversentyp auswählen")

    def _use_truss_type(self, truss: TrussType) -> None:
        if not self._project_bundle:
            self._new_project()
        if self._project and self._project.truss_type_id not in (0, truss.id):
            reply = QMessageBox.question(
                self, "Traversentyp wechseln",
                "Das aktuelle Sub-Projekt hat bereits einen anderen Traversentyp. "
                "Neues Sub-Projekt anlegen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
            self._add_subproject_tab()

        if not truss.has_weight:
            QMessageBox.warning(
                self, "Eigengewicht unbekannt",
                f"Der Traversentyp '{truss.name}' hat kein Eigengewicht im Datenblatt.\n"
                "Das Eigengewicht wird in der Berechnung nicht berücksichtigt.",
            )

        self._truss_type = truss
        if self._project is None:
            self._project = self._create_empty_subproject()
        self._project.truss_type_id = truss.id
        self._project.unit_system = self._unit_combo.currentData()
        if not self._project.name:
            self._project.name = f"Sub-Projekt {self._active_subproject_index + 1}"
        self._commit_active_subproject_state()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._refresh_tabs()
        self._lbl_truss.setText(f"Traversentyp: {truss.display_name}")
        self._status.showMessage(f"Traversentyp '{truss.display_name}' ausgewählt – Abschnitte und Auflager hinzufügen")

    def _open_project(self) -> None:
        from trusscalc.database.db_manager import load_project_from_file
        path, _ = QFileDialog.getOpenFileName(
            self, "Projekt öffnen", "",
            "TrussCalc-Projekt (*.tcproj);;JSON-Datei (*.json);;Alle Dateien (*)",
        )
        if not path:
            return
        try:
            bundle = load_project_from_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Projekt laden fehlgeschlagen", str(exc))
            return
        self._project_path = path
        self._load_project_bundle(bundle)
        if self._project and self._project.truss_type_id and self._truss_type is None:
            QMessageBox.warning(
                self, "Traversentyp fehlt",
                "Der zugehörige Traversentyp ist in dieser Datenbank nicht vorhanden. "
                "Bitte den Typ zuerst importieren oder anlegen.",
            )
        self._status.showMessage(f"Projekt '{bundle.name}' geladen ({path})")

    def _save_project(self) -> None:
        if not self._project_bundle:
            return
        if self._project_path:
            self._write_project_file(self._project_path)
        else:
            self._save_project_as()

    def _save_project_as(self) -> None:
        if not self._project_bundle:
            QMessageBox.information(self, "Speichern", "Kein Projekt zum Speichern vorhanden.")
            return
        suggested = self._project_bundle.name or "Projekt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Projekt speichern unter", f"{suggested}.tcproj",
            "TrussCalc-Projekt (*.tcproj);;JSON-Datei (*.json);;Alle Dateien (*)",
        )
        if not path:
            return
        # Namen ggf. aus Dateinamen ableiten
        from pathlib import Path as _P
        if not self._project_bundle.name or self._project_bundle.name == "Projekt":
            self._project_bundle.name = _P(path).stem
        self._project_path = path
        self._write_project_file(path)

    def _write_project_file(self, path: str) -> None:
        from trusscalc.database.db_manager import save_project_to_file
        try:
            self._commit_active_subproject_state()
            save_project_to_file(path, self._project_bundle)
        except Exception as exc:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", str(exc))
            return
        self._update_window_title()
        self._status.showMessage(f"Projekt gespeichert: {path}")

    def _update_window_title(self) -> None:
        title = "TrussCalc"
        if self._project_bundle and self._project_bundle.name:
            title = f"TrussCalc – {self._project_bundle.name}"
            if self._project and self._project.name:
                title += f" / {self._project.name}"
            if self._project_path:
                title += f"  [{self._project_path}]"
        self.setWindowTitle(title)

    def _start_update_check(self) -> None:
        if self._update_worker is not None:
            return
        if bool(int(__import__("os").environ.get("TRUSSCALC_DISABLE_UPDATE_CHECK", "0"))):
            return

        class _UpdateWorker(QThread):
            done_signal = pyqtSignal(object)

            def run(self):
                from trusscalc.core.update_checker import check_for_updates
                from trusscalc.database.db_manager import _resources_path
                result = check_for_updates(
                    _resources_path() / "default_truss_types.json"
                )
                self.done_signal.emit(result)

        worker = _UpdateWorker(self)
        worker.done_signal.connect(self._on_update_check_done)
        worker.finished.connect(worker.deleteLater)
        self._update_worker = worker
        worker.start()

    def _on_update_check_done(self, result) -> None:
        self._update_worker = None
        if not getattr(result, "ok", False):
            self._status.showMessage(
                "Update-Pruefung uebersprungen (offline oder GitHub nicht erreichbar)",
                5000,
            )
            return
        messages = []
        if result.program_update_available:
            messages.append(
                f"Neue TrussCalc-Version verfuegbar: {result.latest_version} "
                f"(installiert: {APP_VERSION})"
            )
        if result.new_default_trusses:
            shown = ", ".join(result.new_default_trusses[:6])
            if len(result.new_default_trusses) > 6:
                shown += f" und {len(result.new_default_trusses) - 6} weitere"
            messages.append(f"Neue Default-Traversen in der Bibliothek verfuegbar: {shown}")
        if not messages:
            self._status.showMessage(
                "TrussCalc ist aktuell; Default-Bibliothek geprueft.",
                5000,
            )
            return
        detail = "\n".join(messages)
        if result.release_url:
            detail += f"\n\nDownload: {result.release_url}"
        QMessageBox.information(self, "Update verfuegbar", detail)

    def _reset_canvas(self) -> None:
        if not self._project:
            return
        reply = QMessageBox.question(self, "Zurücksetzen",
                                     "Alle Elemente auf dem Canvas löschen?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._push_undo()
            self._project.sections.clear()
            self._project.supports.clear()
            self._project.point_loads.clear()
            self._project.distributed_loads.clear()
            self._canvas.load_project(self._project)
            self._props.show_project_summary(self._project, self._truss_type)

    # ── Elemente hinzufügen / löschen ─────────────────────────────────────────

    def _on_add_section(self, pos_m: float = 0.0) -> None:
        if not self._truss_type:
            QMessageBox.warning(self, "Kein Traversentyp",
                                "Bitte zuerst einen Traversentyp aus der Bibliothek wählen.")
            return
        # Nächste Position = Ende des letzten Abschnitts (lückenlose Reihung)
        if self._project.sections:
            last = max(self._project.sections, key=lambda s: s.position_m + s.length_m)
            next_pos = last.position_m + last.length_m
        else:
            next_pos = 0.0
        dlg = SectionDialog(next_pos, self._truss_type.id, self)
        if dlg.exec():
            section = dlg.get_section()
            self._push_undo()
            self._project.sections.append(section)
            self._canvas.add_section_to_scene(section)
            self._clear_results()
            self._props.show_project_summary(self._project, self._truss_type)

    def _on_add_support(self, pos_m: float) -> None:
        if not self._project:
            return
        total = self._project.total_length_m
        # Position auf Traversenstrecke begrenzen
        pos_m = max(0.0, min(pos_m, total)) if total > 0 else pos_m
        dlg = SupportDialog(pos_m, parent=self)
        if dlg.exec():
            support = dlg.get_support()
            # Validierung: Position muss auf der Strecke liegen
            if total > 0 and (support.position_m < 0 or support.position_m > total):
                QMessageBox.warning(self, "Ungültige Position",
                                    f"Auflager muss zwischen 0 und {total*100:.0f} cm liegen.")
                return
            self._push_undo()
            self._project.supports.append(support)
            self._canvas.add_support_to_scene(support)
            self._clear_results()
            self._props.show_project_summary(self._project, self._truss_type)

    def _on_add_point_load(self, pos_m: float) -> None:
        if not self._project:
            return
        total = self._project.total_length_m
        pos_m = max(0.0, min(pos_m, total)) if total > 0 else pos_m
        dlg = PointLoadDialog(pos_m, parent=self)
        if dlg.exec():
            load = dlg.get_load()
            if total > 0 and (load.position_m < 0 or load.position_m > total):
                QMessageBox.warning(self, "Ungültige Position",
                                    f"Last muss zwischen 0 und {total*100:.0f} cm liegen.")
                return
            self._push_undo()
            self._project.point_loads.append(load)
            self._canvas.add_point_load_to_scene(load)
            self._clear_results()
            self._props.show_project_summary(self._project, self._truss_type)

    def _on_add_dist_load(self, start_m: float, end_m: float) -> None:
        if not self._project:
            return
        dlg = DistributedLoadDialog(start_m, end_m, parent=self)
        if dlg.exec():
            load = dlg.get_load()
            self._push_undo()
            self._project.distributed_loads.append(load)
            self._canvas.add_dist_load_to_scene(load)
            self._clear_results()
            self._props.show_project_summary(self._project, self._truss_type)

    def _on_element_selected(self, element) -> None:
        if element is None:
            self._props.show_project_summary(self._project, self._truss_type)
        else:
            self._props.show_element(element)

    def _on_element_deleted(self, element) -> None:
        if not self._project:
            return
        self._push_undo()
        if isinstance(element, Support):
            self._project.supports = [s for s in self._project.supports if s.id != element.id]
        elif isinstance(element, PointLoad):
            self._project.point_loads = [p for p in self._project.point_loads if p.id != element.id]
        elif isinstance(element, DistributedLoad):
            self._project.distributed_loads = [d for d in self._project.distributed_loads if d.id != element.id]
        elif isinstance(element, TrussSection):
            self._project.sections = [s for s in self._project.sections if s.id != element.id]
        self._clear_results()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)

    def _on_edit_element(self, element) -> None:
        if not element:
            return
        if isinstance(element, Support):
            dlg = SupportDialog(support=element, parent=self)
            if dlg.exec():
                updated = dlg.get_support()
                self._push_undo()
                for i, s in enumerate(self._project.supports):
                    if s.id == element.id:
                        self._project.supports[i] = updated
                        break
                self._canvas.load_project(self._project)
        elif isinstance(element, PointLoad):
            dlg = PointLoadDialog(load=element, parent=self)
            if dlg.exec():
                updated = dlg.get_load()
                self._push_undo()
                for i, p in enumerate(self._project.point_loads):
                    if p.id == element.id:
                        self._project.point_loads[i] = updated
                        break
                self._canvas.load_project(self._project)
        elif isinstance(element, DistributedLoad):
            dlg = DistributedLoadDialog(load=element, parent=self)
            if dlg.exec():
                updated = dlg.get_load()
                self._push_undo()
                for i, d in enumerate(self._project.distributed_loads):
                    if d.id == element.id:
                        self._project.distributed_loads[i] = updated
                        break
                self._canvas.load_project(self._project)
        elif isinstance(element, TrussSection):
            dlg = SectionDialog(
                element.position_m, element.truss_type_id, self,
                section=element,
            )
            if dlg.exec():
                updated = dlg.get_section()
                updated.id = element.id
                updated.position_m = element.position_m
                self._push_undo()
                for i, s in enumerate(self._project.sections):
                    if s.id == element.id:
                        self._project.sections[i] = updated
                        break
                self._canvas.load_project(self._project)
        self._clear_results()
        self._props.show_project_summary(self._project, self._truss_type)

    def _copy_selected(self) -> None:
        if not self._project:
            return
        selected = self._canvas.selected_elements()
        if not selected:
            QMessageBox.information(self, "Kopieren", "Bitte zuerst ein Objekt auswÃ¤hlen.")
            return
        self._copy_templates = [copy.deepcopy(e) for e in selected]
        self._canvas.begin_copy_mode(self._copy_templates)
        self._status.showMessage(
            f"{len(selected)} Objekt(e) kopiert - Linksklick platziert, Rechtsklick/Esc bricht ab"
        )

    def _paste_copy(self) -> None:
        if not self._copy_templates:
            self._copy_selected()
            return
        self._canvas.begin_copy_mode(self._copy_templates)
        self._status.showMessage("Kopie bereit - Linksklick platziert, Rechtsklick/Esc bricht ab")

    def _place_copy_at(self, anchor_m: float) -> None:
        if not self._project or not self._copy_templates:
            self._canvas.finish_copy_placement()
            return
        clones = self._clones_at_anchor(self._copy_templates, anchor_m)
        if not clones:
            self._canvas.finish_copy_placement()
            return
        self._push_undo()
        for clone in clones:
            self._append_project_element(clone)
        self._clear_results()
        self._canvas.finish_copy_placement()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._status.showMessage(f"{len(clones)} Objekt(e) platziert")
        if len(clones) == 1:
            self._on_edit_element(clones[0])

    def _mirror_selected(self) -> None:
        if not self._project:
            return
        selected = self._canvas.selected_elements()
        if not selected:
            QMessageBox.information(self, "Spiegeln", "Bitte zuerst ein Objekt auswÃ¤hlen.")
            return
        total = self._project.total_length_m
        if total <= 0:
            return
        self._push_undo()
        clones = []
        for element in selected:
            clone = copy.deepcopy(element)
            clone.id = str(uuid.uuid4())
            if isinstance(element, TrussSection):
                clone.position_m = max(0.0, total - (element.position_m + element.length_m))
            elif isinstance(element, Support):
                clone.position_m = max(0.0, min(total, total - element.position_m))
            elif isinstance(element, PointLoad):
                clone.position_m = max(0.0, min(total, total - element.position_m))
            elif isinstance(element, DistributedLoad):
                start = total - element.end_m
                end = total - element.start_m
                clone.start_m = max(0.0, min(total, start))
                clone.end_m = max(0.0, min(total, end))
            clones.append(clone)
        for clone in clones:
            self._append_project_element(clone)
        self._clear_results()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._status.showMessage(f"{len(clones)} Objekt(e) kopiert und gespiegelt")

    def _delete_selected(self) -> None:
        if not self._project:
            return
        selected = self._canvas.selected_elements()
        if not selected:
            return
        ids = {element.id for element in selected if getattr(element, "id", None)}
        if not ids:
            return
        self._push_undo()
        self._project.sections = [s for s in self._project.sections if s.id not in ids]
        self._project.supports = [s for s in self._project.supports if s.id not in ids]
        self._project.point_loads = [p for p in self._project.point_loads if p.id not in ids]
        self._project.distributed_loads = [d for d in self._project.distributed_loads if d.id not in ids]
        self._clear_results()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._status.showMessage(f"{len(ids)} Objekt(e) geloescht")

    def _clones_at_anchor(self, templates: list, anchor_m: float) -> list:
        if not templates:
            return []
        source_anchor = min(self._element_start_m(e) for e in templates)
        total = self._project.total_length_m if self._project else 0.0
        clones = []
        for template in templates:
            clone = copy.deepcopy(template)
            clone.id = str(uuid.uuid4())
            offset = anchor_m - source_anchor
            if isinstance(clone, TrussSection):
                clone.position_m = max(0.0, clone.position_m + offset)
            elif isinstance(clone, Support):
                clone.position_m = max(0.0, clone.position_m + offset)
                if total:
                    clone.position_m = min(total, clone.position_m)
            elif isinstance(clone, PointLoad):
                clone.position_m = max(0.0, clone.position_m + offset)
                if total:
                    clone.position_m = min(total, clone.position_m)
            elif isinstance(clone, DistributedLoad):
                length = clone.end_m - clone.start_m
                clone.start_m = max(0.0, clone.start_m + offset)
                clone.end_m = clone.start_m + length
                if total and clone.end_m > total:
                    clone.end_m = total
                    clone.start_m = max(0.0, total - length)
            clones.append(clone)
        return clones

    def _append_project_element(self, element) -> None:
        if isinstance(element, TrussSection):
            self._project.sections.append(element)
        elif isinstance(element, Support):
            self._project.supports.append(element)
        elif isinstance(element, PointLoad):
            self._project.point_loads.append(element)
        elif isinstance(element, DistributedLoad):
            self._project.distributed_loads.append(element)

    @staticmethod
    def _element_start_m(element) -> float:
        if isinstance(element, TrussSection):
            return element.position_m
        if isinstance(element, Support):
            return element.position_m
        if isinstance(element, PointLoad):
            return element.position_m
        if isinstance(element, DistributedLoad):
            return element.start_m
        return 0.0

    def _undo_placeholder_removed(self) -> None:
        pass

    # ── Berechnung ────────────────────────────────────────────────────────────

    def _undo(self) -> None:
        if not self._undo_stack:
            self._status.showMessage("Nichts zum Rueckgaengig machen")
            return
        if self._project:
            self._redo_stack.append(copy.deepcopy(self._project))
        self._project = self._undo_stack.pop()
        self._last_result = None
        self._commit_active_subproject_state()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._update_window_title()
        self._status.showMessage("Letzte Aenderung rueckgaengig gemacht")

    def _redo(self) -> None:
        if not self._redo_stack:
            self._status.showMessage("Nichts zum Wiederholen")
            return
        if self._project:
            self._undo_stack.append(copy.deepcopy(self._project))
        self._project = self._redo_stack.pop()
        self._last_result = None
        self._commit_active_subproject_state()
        self._canvas.load_project(self._project)
        self._props.show_project_summary(self._project, self._truss_type)
        self._update_window_title()
        self._status.showMessage("Aenderung wiederholt")

    def _push_undo(self) -> None:
        if not self._project:
            return
        self._undo_stack.append(copy.deepcopy(self._project))
        self._redo_stack.clear()
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _run_calculation(self) -> None:
        if not self._project or not self._truss_type:
            QMessageBox.warning(self, "Berechnung", "Bitte zuerst Traversentyp und Projekt einrichten.")
            return
        if not self._project.sections:
            QMessageBox.warning(self, "Berechnung", "Bitte mindestens einen Traversenabschnitt hinzufügen.")
            return
        if not self._project.supports:
            QMessageBox.warning(self, "Berechnung", "Bitte mindestens ein Auflager setzen.")
            return

        progress = QProgressDialog("Berechnung laeuft ...", None, 0, 0, self)
        progress.setWindowTitle("Simulation")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(360)
        progress.show()
        QApplication.processEvents()

        try:
            result = calculator.calculate(self._project, self._truss_type)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Berechnungsfehler", str(exc))
            return
        finally:
            progress.close()

        self._last_result = result
        self._commit_active_subproject_state()

        if result.warnings:
            QMessageBox.warning(self, "Berechnungshinweise", "\n".join(result.warnings))

        interp = LoadTableInterpolator(self._truss_type)
        ei = interp.effective_ei(self._project.total_length_m)
        sw = self._truss_type.weight_per_meter_kg if self._truss_type.has_weight else None

        self._canvas.show_results(result, ei or 1.0, sw)

        total = result.total_load_kg + result.self_weight_kg
        self._status.showMessage(
            f"Berechnung abgeschlossen – "
            f"Gesamtlast: {total:.1f} kg, "
            f"Max. Durchbiegung: {result.deflection.max_deflection_mm:.1f} mm"
        )

    def _clear_results(self) -> None:
        self._last_result = None
        self._commit_active_subproject_state()
        self._canvas.clear_results()

    def _fit_view(self) -> None:
        self._canvas.fit_view()

    # ── Einheiten ─────────────────────────────────────────────────────────────

    def _on_unit_changed(self, idx: int) -> None:
        unit = self._unit_combo.currentData()
        if self._project_bundle:
            self._project_bundle.unit_system = unit
            for project in self._project_bundle.subprojects:
                project.unit_system = unit
        if self._project:
            self._project.unit_system = unit
        self._props.set_unit_system(unit)
        if self._project:
            self._canvas.load_project(self._project)
            if self._last_result and self._truss_type:
                interp = LoadTableInterpolator(self._truss_type)
                ei = interp.effective_ei(self._project.total_length_m)
                sw = self._truss_type.weight_per_meter_kg if self._truss_type.has_weight else None
                self._canvas.show_results(self._last_result, ei or 1.0, sw)
            self._props.show_project_summary(self._project, self._truss_type)

    # ── PDF-Import & Traversenverwaltung ──────────────────────────────────────

    def _import_pdf(self) -> None:
        from trusscalc.ui.dialogs.pdf_import_dialog import PdfImportDialog
        from trusscalc.database.db_manager import save_truss_type, save_truss_pdf
        dlg = PdfImportDialog(parent=self)
        if dlg.exec():
            truss = dlg.get_truss_type()
            pdf_bytes = dlg.get_pdf_bytes()
            tid = save_truss_type(truss)
            if pdf_bytes:
                save_truss_pdf(tid, pdf_bytes, dlg.get_pdf_filename())
            self._library.refresh()
            self._status.showMessage(f"Traversentyp '{truss.name}' importiert")

    def _import_pdf_ai(self) -> None:
        """KI-basierter PDF-Import via PaddleOCR PP-Structure (~2 Minuten)."""
        from trusscalc.pdf import pdf_ocr
        check_progress = QProgressDialog("KI-Import wird vorbereitet ...", None, 0, 0, self)
        check_progress.setWindowTitle("PDF Import (KI)")
        check_progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        check_progress.setCancelButton(None)
        check_progress.setMinimumDuration(0)
        check_progress.setMinimumWidth(380)
        check_progress.show()
        QApplication.processEvents()
        if not pdf_ocr.is_available():
            check_progress.close()
            QMessageBox.warning(
                self, "PaddleOCR nicht verfügbar",
                "Für den KI-PDF-Import wird PaddleOCR benötigt. "
                "Bitte installieren mit:\n\n"
                "pip install paddlepaddle paddleocr \"paddlex[ocr]\""
            )
            return
        check_progress.close()

        path, _ = QFileDialog.getOpenFileName(
            self, "PDF-Datenblatt mit KI auslesen", "",
            "PDF-Dateien (*.pdf)",
        )
        if not path:
            return

        # Progress-Dialog (busy mode = unbestimmt)
        from PyQt6.QtCore import QThread, pyqtSignal
        from trusscalc.pdf.pdf_ocr import PaddleOCRPdfParser, OcrParseResult

        progress = QProgressDialog(
            "Initialisiere KI-Modelle …", None, 0, 0, self
        )
        progress.setWindowTitle("PDF mit KI auslesen")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(380)
        progress.show()
        self._library._btn_pdf_ai.setEnabled(False)

        class _OcrWorker(QThread):
            progress_signal = pyqtSignal(str)
            done_signal = pyqtSignal(object)
            error_signal = pyqtSignal(str)

            def __init__(self, parser, pdf_path):
                super().__init__()
                self.parser = parser
                self.pdf_path = pdf_path

            def run(self):
                try:
                    result = self.parser.parse(
                        self.pdf_path,
                        progress_cb=lambda m: self.progress_signal.emit(m),
                    )
                    self.done_signal.emit(result)
                except Exception as exc:
                    self.error_signal.emit(str(exc))

        parser = PaddleOCRPdfParser()
        worker = _OcrWorker(parser, path)
        worker.progress_signal.connect(progress.setLabelText)

        def _on_done(result: OcrParseResult) -> None:
            progress.close()
            self._library._btn_pdf_ai.setEnabled(True)
            self._open_import_dialog_with_ocr(path, result)

        def _on_error(msg: str) -> None:
            progress.close()
            self._library._btn_pdf_ai.setEnabled(True)
            QMessageBox.critical(self, "KI-Parser-Fehler", msg)

        worker.done_signal.connect(_on_done)
        worker.error_signal.connect(_on_error)
        # Referenz halten, damit Worker nicht vom GC entsorgt wird
        self._ocr_worker = worker
        worker.start()

    def _open_import_dialog_with_ocr(self, path: str, ocr_result) -> None:
        from trusscalc.ui.dialogs.pdf_import_dialog import PdfImportDialog
        from trusscalc.database.db_manager import save_truss_type, save_truss_pdf
        dlg = PdfImportDialog(pdf_path=path, ocr_result=ocr_result, parent=self)
        if dlg.exec():
            truss = dlg.get_truss_type()
            pdf_bytes = dlg.get_pdf_bytes()
            tid = save_truss_type(truss)
            if pdf_bytes:
                save_truss_pdf(tid, pdf_bytes, dlg.get_pdf_filename())
            self._library.refresh()
            self._status.showMessage(
                f"Traversentyp '{truss.name}' via KI importiert"
            )

    def _import_default_library(self) -> None:
        """Importiert die mit dem Programm ausgelieferten Default-Traversentypen.
        Wird beim ersten Programmstart automatisch ausgeführt; via Menü kann
        der User die Defaults später nachladen (z. B. nach manuellem Löschen)."""
        from trusscalc.database.db_manager import (
            list_truss_types, _resources_path,
        )
        import json as _json

        json_path = _resources_path() / "default_truss_types.json"
        if not json_path.exists():
            QMessageBox.warning(
                self, "Default-Bibliothek",
                f"Die Datei {json_path} wurde nicht gefunden.",
            )
            return

        try:
            payload = _json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Fehler", f"JSON konnte nicht gelesen werden:\n{exc}")
            return

        defaults = payload.get("truss_types", [])
        if not defaults:
            QMessageBox.information(self, "Default-Bibliothek",
                                     "Keine Default-Einträge in der JSON-Datei.")
            return

        existing = {t.name for t in list_truss_types()}
        new = [t for t in defaults if t.get("name") not in existing]
        skipped = len(defaults) - len(new)

        if not new:
            QMessageBox.information(
                self, "Default-Bibliothek",
                f"Alle {len(defaults)} Default-Traversentypen sind bereits in "
                "der Datenbank vorhanden.",
            )
            return

        msg = (f"{len(new)} Default-Traversentypen werden neu importiert"
               + (f" (überspringe {skipped} bereits vorhandene)" if skipped else "")
               + ".\n\nFortfahren?")
        reply = QMessageBox.question(
            self, "Default-Bibliothek importieren", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from trusscalc.database.db_manager import save_truss_type
        from trusscalc.core.models import (
            TrussType, TrussSource, LoadTableEntry, LoadType,
        )
        n_added = 0
        for t_data in new:
            try:
                entries = [
                    LoadTableEntry(
                        span_m=float(e["span_m"]),
                        load_type=LoadType(e["load_type"]),
                        max_load_kg=float(e["max_load_kg"]),
                        deflection_mm=float(e["deflection_mm"]),
                    )
                    for e in t_data.get("load_table", [])
                ]
                truss = TrussType(
                    name=t_data["name"],
                    manufacturer=t_data.get("manufacturer"),
                    model_code=t_data.get("model_code"),
                    material=t_data.get("material"),
                    width_mm=t_data.get("width_mm"),
                    height_mm=t_data.get("height_mm"),
                    weight_per_meter_kg=t_data.get("weight_per_meter_kg"),
                    source=TrussSource.DATASHEET,
                    load_table=entries,
                )
                save_truss_type(truss)
                n_added += 1
            except Exception:
                continue
        self._library.refresh()
        QMessageBox.information(
            self, "Default-Bibliothek",
            f"{n_added} Traversentyp(en) hinzugefügt.",
        )

    def _add_manual_truss(self) -> None:
        from trusscalc.ui.dialogs.manual_truss_dialog import ManualTrussDialog
        from trusscalc.database.db_manager import save_truss_type, save_truss_pdf
        dlg = ManualTrussDialog(parent=self)
        if dlg.exec():
            truss = dlg.get_truss_type()
            tid = save_truss_type(truss)
            if dlg.get_pdf_bytes():
                save_truss_pdf(tid, dlg.get_pdf_bytes(), dlg.get_pdf_filename())
            self._library.refresh()

    # ── PDF-Report ────────────────────────────────────────────────────────────

    def _generate_pdf(self) -> None:
        if not self._project_bundle:
            QMessageBox.information(self, "PDF-Report", "Kein Projekt vorhanden.")
            return
        self._commit_active_subproject_state()

        chapters = []
        missing = []
        for idx, project in enumerate(self._project_bundle.subprojects):
            truss_type = self._subproject_truss_types[idx]
            if truss_type is None and project.truss_type_id:
                from trusscalc.database.db_manager import load_truss_type
                truss_type = load_truss_type(project.truss_type_id)
                self._subproject_truss_types[idx] = truss_type
            result = self._subproject_results[idx]
            if result is None and truss_type and project.sections and project.supports:
                try:
                    result = calculator.calculate(project, truss_type)
                    self._subproject_results[idx] = result
                except Exception:
                    result = None
            if truss_type and result:
                chapters.append((idx, project, truss_type, result))
            else:
                missing.append(project.name or f"Sub-Projekt {idx + 1}")

        if missing:
            if chapters:
                reply = QMessageBox.question(
                    self,
                    "PDF-Report",
                    "Nicht alle Sub-Projekte sind berechnet:\n"
                    + "\n".join(f"- {name}" for name in missing)
                    + "\n\nNur berechnete Sub-Projekte exportieren?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            else:
                QMessageBox.information(
                    self,
                    "PDF-Report",
                    "Bitte zuerst mindestens ein Sub-Projekt berechnen.",
                )
                return

        if not chapters:
            QMessageBox.information(self, "PDF-Report",
                                    "Bitte zuerst eine Berechnung durchführen.")
            return

        # Metadaten-Dialog (Sprache, Projektname, Sub-Name, E-Mail)
        from trusscalc.ui.dialogs.report_metadata_dialog import ReportMetadataDialog
        default_name = self._default_report_project_name()
        dlg = ReportMetadataDialog(default_project_name=default_name,
                                    default_sub_name="", parent=self)
        if not dlg.exec():
            return
        metadata = dlg.get_metadata()

        # Ziel-Dateiname vorschlagen
        suggested = metadata.project_name or "Report"
        if len(chapters) == 1 and metadata.sub_project_name:
            suggested += f" – {metadata.sub_project_name}"
        path, _ = QFileDialog.getSaveFileName(
            self, "PDF-Report speichern", f"{suggested}.pdf", "PDF (*.pdf)")
        if not path:
            return
        progress = QProgressDialog("PDF-Report wird erstellt ...", None, 0, 0, self)
        progress.setWindowTitle("PDF-Report")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(380)
        progress.show()
        QApplication.processEvents()
        from trusscalc.database.db_manager import load_truss_pdf
        report_chapters = []
        for _idx, project, truss_type, result in chapters:
            report_chapters.append({
                "project": copy.deepcopy(project),
                "truss_type": copy.deepcopy(truss_type),
                "result": copy.deepcopy(result),
                "datasheet_pdf_bytes": load_truss_pdf(truss_type.id),
            })

        class _PdfWorker(QThread):
            done_signal = pyqtSignal(str)
            error_signal = pyqtSignal(str)

            def __init__(self, pdf_path, chapter_data, report_metadata):
                super().__init__()
                self.pdf_path = pdf_path
                self.chapter_data = chapter_data
                self.report_metadata = report_metadata

            def run(self):
                try:
                    from trusscalc.pdf.pdf_generator import generate_project_report
                    generate_project_report(
                        path=self.pdf_path,
                        chapters=self.chapter_data,
                        metadata=self.report_metadata,
                    )
                    self.done_signal.emit(self.pdf_path)
                except Exception as exc:
                    self.error_signal.emit(str(exc))

        worker = _PdfWorker(
            path,
            report_chapters,
            metadata,
        )

        def _on_done(saved_path: str) -> None:
            progress.close()
            self._pdf_worker = None
            self._status.showMessage(f"PDF-Report gespeichert: {saved_path}")

        def _on_error(msg: str) -> None:
            progress.close()
            self._pdf_worker = None
            QMessageBox.critical(self, "PDF-Fehler", msg)

        worker.done_signal.connect(_on_done)
        worker.error_signal.connect(_on_error)
        worker.finished.connect(worker.deleteLater)
        self._pdf_worker = worker
        worker.start()

    # ── Design ────────────────────────────────────────────────────────────────

    def _default_report_project_name(self) -> str:
        if self._project_bundle and self._project_bundle.name:
            name = self._project_bundle.name.strip()
        elif self._project and self._project.name:
            name = self._project.name.strip()
        else:
            return "Projekt"
        name = name.replace("Projekt \u2013 ", "").replace("Projekt - ", "").replace("Projekt-", "")
        for prefix in ("Projekt â€“ ", "Projekt - ", "Projekt-"):
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
        return name or "Projekt"

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1E1E1E; color: #D4D4D4; }
            QMenuBar { background: #2D2D2D; color: #D4D4D4; padding: 2px; }
            QMenuBar::item { background: transparent; padding: 4px 10px; }
            QMenuBar::item:selected { background: #3A3A3A; }
            QMenuBar::item:pressed { background: #094771; }
            QMenu {
                background-color: #252525;
                color: #E4E4E4;
                border: 1px solid #555;
                padding: 4px 0;
            }
            QMenu::item {
                background-color: transparent;
                padding: 6px 28px 6px 22px;
                margin: 1px 4px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #094771;
                color: #FFFFFF;
            }
            QMenu::item:disabled { color: #777777; }
            QMenu::separator {
                height: 1px;
                background: #444;
                margin: 4px 8px;
            }
            QMenu::icon { padding-left: 6px; }
            QToolBar { background: #2D2D2D; border: none; spacing: 4px; }
            QToolButton { background: #2D2D2D; color: #D4D4D4; border: 1px solid #444;
                          padding: 3px 6px; border-radius: 3px; }
            QToolButton:checked { background: #094771; color: white; }
            QToolButton:hover { background: #3A3A3A; }
            QPushButton { background: #2D2D2D; color: #D4D4D4; border: 1px solid #555;
                          padding: 4px 10px; border-radius: 3px; }
            QPushButton:hover { background: #3A3A3A; }
            QPushButton:pressed { background: #094771; }
            QLineEdit, QDoubleSpinBox, QComboBox { background: #2D2D2D; color: #D4D4D4;
                border: 1px solid #555; padding: 2px 4px; border-radius: 2px; }
            QGroupBox { border: 1px solid #444; border-radius: 4px;
                        margin-top: 8px; color: #AAAAAA; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QTreeWidget { background: #252525; color: #D4D4D4; border: none; }
            QTreeWidget::item:selected { background: #094771; }
            QTableWidget { background: #252525; color: #D4D4D4; gridline-color: #444; }
            QHeaderView::section { background: #2D2D2D; color: #AAAAAA; border: none; padding: 4px; }
            QScrollBar:vertical { background: #2D2D2D; width: 10px; }
            QScrollBar::handle:vertical { background: #555; border-radius: 4px; }
            QStatusBar { background: #2D2D2D; color: #AAAAAA; }
            QSplitter::handle { background: #3A3A3A; }
            QDialog { background: #252525; color: #D4D4D4; }
        """)

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _action(self, label: str, slot, shortcut: str = "") -> QAction:
        act = QAction(label, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        return act

    def keyPressEvent(self, event) -> None:
        if self._focus_accepts_text():
            super().keyPressEvent(event)
            return
        key = event.key()
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self._copy_selected()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self._paste_copy()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_M:
            self._mirror_selected()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_Escape:
            if self._canvas.is_copy_mode_active():
                self._canvas.cancel_copy_mode()
                self._status.showMessage("Kopieren abgebrochen")
            else:
                self._set_tool(CanvasTool.SELECT)
            event.accept()
            return
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_Delete:
            self._delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_accepts_text(self) -> bool:
        widget = QApplication.focusWidget()
        return isinstance(
            widget,
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox),
        )
