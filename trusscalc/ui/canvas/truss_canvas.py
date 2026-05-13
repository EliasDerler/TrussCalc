"""
2D-Canvas für die Traversen-Visualisierung.
LTSpice-inspiriert: Raster, Pan/Zoom, Werkzeug-basierte Platzierung.
"""
import uuid
import copy
from typing import Optional

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsTextItem,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QWheelEvent, QMouseEvent, QPainter, QFont

from trusscalc.core.models import (
    TrussSystem, TrussSection, Support, PointLoad, DistributedLoad,
    CalculationResult, Project, UnitSystem,
)
from trusscalc.ui.canvas.canvas_items import (
    TrussSegmentItem, SupportItem, PointLoadItem, DistributedLoadItem,
    DeflectionCurveItem, DimensionItem, PX_PER_M, TRUSS_HEIGHT,
    COLOR_DIM_TOTAL, COLOR_DIM_SUPPORT, COLOR_DIM_TEXT,
    DIM_Y_SUPPORT, DIM_Y_TOTAL,
)
from trusscalc.ui.canvas.canvas_tools import CanvasTool
from trusscalc.core import color_rules

GRID_SIZE = 20      # Rastergröße in Pixel
GRID_COLOR = QColor("#2A2A2A")
BG_COLOR = QColor("#1E1E1E")     # Dunkler LTSpice-Hintergrund
SYSTEM_ROW_GAP = 260.0


class TrussCanvas(QGraphicsView):
    """Hauptcanvas für die Traversenvisualisierung."""

    element_selected = pyqtSignal(object)   # Selektiertes Element (Support/Load/Section)
    system_selected = pyqtSignal(str)
    element_added = pyqtSignal(object)
    element_deleted = pyqtSignal(object)
    element_context_requested = pyqtSignal(object)
    copy_place_requested = pyqtSignal(float)
    copy_cancel_requested = pyqtSignal()
    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    mirror_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    request_support_dialog = pyqtSignal(float)          # Position in m
    request_point_load_dialog = pyqtSignal(float)
    request_dist_load_dialog = pyqtSignal(float, float) # start_m, end_m
    request_section_dialog = pyqtSignal(float)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        scene = QGraphicsScene()
        super().__init__(scene, parent)
        self._setup_view()
        self._project: Optional[Project] = None
        self._active_system_id: Optional[str] = None
        self._current_tool = CanvasTool.SELECT
        self._dist_load_start: Optional[float] = None
        self._panning = False
        self._pan_last_pos = None
        self._copy_mode = False
        self._copy_templates: list = []
        self._copy_anchor_m = 0.0
        self._copy_preview_items: list[QGraphicsItem] = []
        self._comparison_mode = False
        self._system_drag_id: Optional[str] = None
        self._system_drag_last_scene: Optional[QPointF] = None

        # Canvas-Items (Position_id → Item)
        self._section_items: dict[str, TrussSegmentItem] = {}
        self._support_items: dict[str, SupportItem] = {}
        self._load_items: dict[str, PointLoadItem | DistributedLoadItem] = {}
        self._deflection_item: Optional[DeflectionCurveItem] = None
        self._deflection_items: dict[str, DeflectionCurveItem] = {}
        self._dim_items: list[DimensionItem] = []
        self._element_system_ids: dict[str, str] = {}

    def _setup_view(self) -> None:
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scene().setSceneRect(-500, -350, 3000, 700)
        self.setStyleSheet("")

    # ── Werkzeug-API ──────────────────────────────────────────────────────────

    def set_tool(self, tool: CanvasTool) -> None:
        self._current_tool = tool
        if tool == CanvasTool.SELECT:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        self._dist_load_start = None

    # ── Projekt laden ─────────────────────────────────────────────────────────

    def load_project(self, project: Project) -> None:
        self.finish_copy_placement()
        self._project = project
        if self._project and self._project.active_system:
            self._active_system_id = self._project.active_system.id
        self._rebuild_scene()

    def set_active_system_id(self, system_id: Optional[str]) -> None:
        self._active_system_id = system_id
        if self._project and self._project.active_system_id != system_id:
            self._project.active_system_id = system_id
        if self._project and not self._comparison_mode:
            self._rebuild_scene()

    def set_comparison_mode(self, enabled: bool) -> None:
        self._comparison_mode = enabled
        self.setStyleSheet(
            "QGraphicsView { border: 2px solid #00A6A6; }" if enabled else ""
        )
        self._rebuild_scene()

    def _force_text(self, kg: float) -> str:
        if self._project and self._project.unit_system == UnitSystem.N_M:
            return f"{kg * 9.80665 / 1000:.2f} kN"
        return f"{kg:.1f} kg"

    def _rebuild_scene(self) -> None:
        self.scene().clear()
        self._section_items.clear()
        self._support_items.clear()
        self._load_items.clear()
        self._deflection_item = None
        self._deflection_items.clear()
        self._dim_items.clear()
        self._element_system_ids.clear()

        if not self._project:
            return

        systems = self._visible_systems()
        for idx, system in enumerate([s for s in systems if s is not None]):
            y = self._system_y(system)
            x = self._system_x(system)
            if self._comparison_mode and len(systems) > 1:
                self._draw_system_label(system, x, y)
            for section in system.sections:
                self._add_section_item(section, system)

            for support in system.supports:
                self._add_support_item(support, system)

            for pl in system.point_loads:
                self._add_point_load_item(pl, system)

            for dl in system.distributed_loads:
                self._add_dist_load_item(dl, system)

        self._draw_dimensions()
        self._update_scene_rect()

    # ── Element hinzufügen ────────────────────────────────────────────────────

    def _system_y(self, system: TrussSystem) -> float:
        return float(system.canvas_y_m) * SYSTEM_ROW_GAP

    def _system_x(self, system: TrussSystem) -> float:
        return float(system.canvas_x_m) * PX_PER_M

    def _visible_systems(self) -> list[TrussSystem]:
        if not self._project:
            return []
        systems = [s for s in self._project.systems if s is not None]
        if self._comparison_mode:
            ids = set(getattr(self._project, "compare_system_ids", []) or [])
            return [s for s in systems if not ids or s.id in ids]
        plan_id = getattr(self._project, "plan_system_id", None)
        active = next((s for s in systems if s.id == plan_id), None) or self._project.active_system
        return [active] if active else systems[:1]

    def _system_at_scene_y(self, scene_y: float) -> Optional[TrussSystem]:
        systems = self._visible_systems()
        if not systems:
            return self._project.active_system if self._project else None
        return min(
            systems,
            key=lambda system: abs(scene_y - self._system_y(system)),
        )

    def _pos_m_for_scene(self, scene_pos: QPointF, system: Optional[TrussSystem]) -> float:
        x_offset = self._system_x(system) if system else 0.0
        return (scene_pos.x() - x_offset) / PX_PER_M

    def _draw_system_label(self, system: TrussSystem, x: float, y: float) -> None:
        label = QGraphicsTextItem(system.name or "System")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        label.setFont(font)
        label.setDefaultTextColor(COLOR_DIM_TEXT)
        label.setPos(x, y + DIM_Y_TOTAL - 82)
        label.setData(0, system.id)
        self.scene().addItem(label)

    def _remember_system(self, element_id: str, system: TrussSystem) -> None:
        if element_id:
            self._element_system_ids[element_id] = system.id

    def _add_section_item(self, section: TrussSection, system: TrussSystem | None = None) -> TrussSegmentItem:
        item = TrussSegmentItem(section)
        y = self._system_y(system) if system else 0.0
        x = self._system_x(system) if system else 0.0
        item.setPos(x + section.position_m * PX_PER_M, y)
        self.scene().addItem(item)
        self._section_items[section.id] = item
        if system:
            self._remember_system(section.id, system)
        return item

    def _add_support_item(self, support: Support, system: TrussSystem | None = None) -> SupportItem:
        item = SupportItem(support)
        y = self._system_y(system) if system else 0.0
        x = self._system_x(system) if system else 0.0
        item.setPos(x + support.position_m * PX_PER_M, y + TRUSS_HEIGHT // 2)
        self.scene().addItem(item)
        self._support_items[support.id] = item
        if system:
            self._remember_system(support.id, system)
        return item

    def _add_point_load_item(self, load: PointLoad, system: TrussSystem | None = None) -> PointLoadItem:
        item = PointLoadItem(load)
        y = self._system_y(system) if system else 0.0
        x = self._system_x(system) if system else 0.0
        item.setPos(x + load.position_m * PX_PER_M, y)
        self.scene().addItem(item)
        self._load_items[load.id] = item
        if system:
            self._remember_system(load.id, system)
        return item

    def _add_dist_load_item(self, load: DistributedLoad, system: TrussSystem | None = None) -> DistributedLoadItem:
        item = DistributedLoadItem(load)
        y = self._system_y(system) if system else 0.0
        x = self._system_x(system) if system else 0.0
        item.setPos(x + load.start_m * PX_PER_M, y)
        self.scene().addItem(item)
        self._load_items[load.id] = item
        if system:
            self._remember_system(load.id, system)
        return item

    def _draw_dimensions(self) -> None:
        for item in self._dim_items:
            self.scene().removeItem(item)
        self._dim_items.clear()
        if not self._project:
            return
        for system in self._visible_systems():
            total = system.total_length_m
            y = self._system_y(system)
            x_offset = self._system_x(system)

            if total > 0:
                item = DimensionItem(x_offset, x_offset + total * PX_PER_M,
                                     f"Gesamt: {total*100:.0f} cm",
                                     y + DIM_Y_TOTAL, color=COLOR_DIM_TOTAL)
                self.scene().addItem(item)
                self._dim_items.append(item)

            all_positions = sorted([s.position_m for s in system.supports])
            if all_positions:
                segment_points = sorted({0.0, total} | set(all_positions))
                for i in range(len(segment_points) - 1):
                    x1 = segment_points[i]
                    x2 = segment_points[i + 1]
                    if x2 - x1 < 1e-6:
                        continue
                    item = DimensionItem(
                        x_offset + x1 * PX_PER_M, x_offset + x2 * PX_PER_M,
                        f"{(x2 - x1) * 100:.0f} cm",
                        y + DIM_Y_SUPPORT, color=COLOR_DIM_SUPPORT,
                    )
                    self.scene().addItem(item)
                    self._dim_items.append(item)

    # ── Berechnungsergebnisse anzeigen ────────────────────────────────────────

    def show_results(self, result: CalculationResult, ei_n_m2: float,
                     self_weight_kg_per_m: Optional[float]) -> None:
        if not self._project:
            return

        # Deflectionskurve
        if self._deflection_item:
            self.scene().removeItem(self._deflection_item)

        defl_color = color_rules.classify_deflection(result.deflection)
        max_text = (f"↓{result.deflection.max_deflection_mm:.1f} mm"
                    if result.deflection.max_deflection_mm > 0 else "")
        max_pos = (result.deflection.max_deflection_position_m
                   if result.deflection.max_deflection_mm > 0 else None)
        self._deflection_item = DeflectionCurveItem()
        self._deflection_item.set_result(
            result.deflection.positions_m,
            result.deflection.deflections_mm,
            defl_color.color,
            max_text,
            max_position_m=max_pos,
        )
        self.scene().addItem(self._deflection_item)

        # Auflagerfarben
        support_colors = color_rules.classify_supports(
            result.support_results,
            result.deflection,
            self._project.sections,
            self._project.point_loads,
            self._project.distributed_loads,
            ei_n_m2,
            self_weight_kg_per_m,
            self._project.total_length_m,
        )
        for sc in support_colors:
            item = self._support_items.get(sc.support_id)
            if item:
                item.set_color(sc.color)
                item.setToolTip(sc.tooltip)

        # Reaktionskraft-Text und Lift-Höhe an Auflagern
        for sr in result.support_results:
            item = self._support_items.get(sr.support.id)
            if item:
                item.reaction_text = self._force_text(sr.reaction_kg)
                item.lift_height_mm = (
                    sr.lift_height_mm if not sr.is_active else 0.0
                )
                item.update()

    def show_system_results(self, result_specs: dict[str, tuple]) -> None:
        if not self._project:
            return
        self.clear_results()
        for system in self._visible_systems():
            spec = result_specs.get(system.id)
            if not spec:
                continue
            result, ei_n_m2, self_weight_kg_per_m = spec
            defl_color = color_rules.classify_deflection(result.deflection)
            max_text = (f"↓{result.deflection.max_deflection_mm:.1f} mm"
                        if result.deflection.max_deflection_mm > 0 else "")
            max_pos = (result.deflection.max_deflection_position_m
                       if result.deflection.max_deflection_mm > 0 else None)
            deflection_item = DeflectionCurveItem()
            deflection_item.set_result(
                result.deflection.positions_m,
                result.deflection.deflections_mm,
                defl_color.color,
                max_text,
                max_position_m=max_pos,
            )
            deflection_item.setPos(self._system_x(system), self._system_y(system))
            self.scene().addItem(deflection_item)
            self._deflection_items[system.id] = deflection_item

            support_colors = color_rules.classify_supports(
                result.support_results,
                result.deflection,
                system.sections,
                system.point_loads,
                system.distributed_loads,
                ei_n_m2,
                self_weight_kg_per_m,
                system.total_length_m,
            )
            for sc in support_colors:
                item = self._support_items.get(sc.support_id)
                if item:
                    item.set_color(sc.color)
                    item.setToolTip(sc.tooltip)
            for sr in result.support_results:
                item = self._support_items.get(sr.support.id)
                if item:
                    item.reaction_text = self._force_text(sr.reaction_kg)
                    item.lift_height_mm = (
                        sr.lift_height_mm if not sr.is_active else 0.0
                    )
                    item.update()

    def clear_results(self) -> None:
        if self._deflection_item:
            self.scene().removeItem(self._deflection_item)
            self._deflection_item = None
        for item in self._deflection_items.values():
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._deflection_items.clear()
        for item in self._support_items.values():
            item.set_color("white")
            item.reaction_text = ""
            item.lift_height_mm = 0.0
            item.update()

    # ── Maussteuerung ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())
        clicked_system = self._system_label_at(event.pos()) or self._system_at_scene_y(scene_pos.y())
        if clicked_system:
            self._active_system_id = clicked_system.id
            self.system_selected.emit(clicked_system.id)
        pos_m = self._pos_m_for_scene(scene_pos, clicked_system)

        if self._copy_mode:
            if event.button() == Qt.MouseButton.RightButton:
                self.cancel_copy_mode()
                self.copy_cancel_requested.emit()
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self.copy_place_requested.emit(max(0.0, pos_m))
                event.accept()
                return

        if event.button() == Qt.MouseButton.RightButton:
            item = self._element_item_at(event.pos())
            if item:
                item.setSelected(True)
                element = self._element_from_item(item)
                if element is not None:
                    self.element_selected.emit(element)
                    self.element_context_requested.emit(element)
                    event.accept()
                    return
            self.set_tool(CanvasTool.SELECT)
            return

        if self._current_tool == CanvasTool.SELECT:
            if (
                self._comparison_mode
                and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and clicked_system
                and self._element_item_at(event.pos()) is None
                and self._is_system_drag_hit(event.pos(), scene_pos, clicked_system)
            ):
                self._system_drag_id = clicked_system.id
                self._system_drag_last_scene = scene_pos
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
            super().mousePressEvent(event)
            items = self.scene().selectedItems()
            if items:
                element = self._element_from_item(items[0])
                if element is not None:
                    system_id = self._element_system_ids.get(getattr(element, "id", ""))
                    if system_id:
                        self._active_system_id = system_id
                        self.system_selected.emit(system_id)
                    self.element_selected.emit(element)
            else:
                self.element_selected.emit(None)
            return

        if self._current_tool == CanvasTool.ADD_SUPPORT:
            self.request_support_dialog.emit(max(0.0, pos_m))
        elif self._current_tool == CanvasTool.ADD_POINT_LOAD:
            self.request_point_load_dialog.emit(max(0.0, pos_m))
        elif self._current_tool == CanvasTool.ADD_DIST_LOAD:
            if self._dist_load_start is None:
                self._dist_load_start = max(0.0, pos_m)
                self.status_message.emit(
                    f"Startpunkt gesetzt ({self._dist_load_start*100:.0f} cm) – "
                    "jetzt Endpunkt klicken"
                )
            else:
                end = max(0.0, pos_m)
                if abs(end - self._dist_load_start) > 0.01:
                    start = min(self._dist_load_start, end)
                    end = max(self._dist_load_start, end)
                    self.request_dist_load_dialog.emit(start, end)
                self._dist_load_start = None
        elif self._current_tool == CanvasTool.ADD_SECTION:
            # Position wird im MainWindow automatisch bestimmt
            self.request_section_dialog.emit(0.0)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._system_drag_id and event.button() == Qt.MouseButton.LeftButton:
            self._system_drag_id = None
            self._system_drag_last_scene = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._system_drag_id
            and self._system_drag_last_scene is not None
            and self._project
            and event.buttons() & Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._system_drag_last_scene
            self._system_drag_last_scene = scene_pos
            system = next((s for s in self._project.systems if s.id == self._system_drag_id), None)
            if system:
                old_x = system.canvas_x_m
                old_y = system.canvas_y_m
                system.canvas_x_m += delta.x() / PX_PER_M
                system.canvas_y_m += delta.y() / SYSTEM_ROW_GAP
                if self._systems_overlap(system):
                    system.canvas_x_m = old_x
                    system.canvas_y_m = old_y
                self._rebuild_scene()
            event.accept()
            return
        if self._system_drag_id:
            self._system_drag_id = None
            self._system_drag_last_scene = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._panning and self._pan_last_pos is not None:
            delta = event.pos() - self._pan_last_pos
            self._pan_last_pos = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        if self._copy_mode:
            scene_pos = self.mapToScene(event.pos())
            system = self._system_at_scene_y(scene_pos.y())
            self._update_copy_preview(max(0.0, self._pos_m_for_scene(scene_pos, system)))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_Escape:
            if self._copy_mode:
                self.cancel_copy_mode()
                self.copy_cancel_requested.emit()
                event.accept()
                return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self.copy_requested.emit()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self.paste_requested.emit()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_M:
            self.mirror_requested.emit()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_Space:
            self.fit_view(all_systems=False)
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Space:
            self.fit_view(all_systems=True)
            event.accept()
            return
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_Delete:
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Raster zeichnen ───────────────────────────────────────────────────────

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        pen = QPen(GRID_COLOR, 0.5)
        painter.setPen(pen)
        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)
        lines_h = []
        lines_v = []
        y = float(top)
        while y < rect.bottom():
            lines_h.append((rect.left(), y, rect.right(), y))
            y += GRID_SIZE
        x = float(left)
        while x < rect.right():
            lines_v.append((x, rect.top(), x, rect.bottom()))
            x += GRID_SIZE
        for x1, y1, x2, y2 in lines_h:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        for x1, y1, x2, y2 in lines_v:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    # ── Öffentliche Hilfsmethoden ─────────────────────────────────────────────

    def add_section_to_scene(self, section: TrussSection) -> None:
        system = self._system_at_scene_y(self._system_y(self._project.active_system)) if self._project and self._project.active_system else None
        self._add_section_item(section, system)
        self._draw_dimensions()

    def add_support_to_scene(self, support: Support) -> None:
        system = self._project.active_system if self._project else None
        self._add_support_item(support, system)
        self._draw_dimensions()

    def add_point_load_to_scene(self, load: PointLoad) -> None:
        system = self._project.active_system if self._project else None
        self._add_point_load_item(load, system)

    def add_dist_load_to_scene(self, load: DistributedLoad) -> None:
        system = self._project.active_system if self._project else None
        self._add_dist_load_item(load, system)

    def remove_selected(self) -> None:
        for item in self.scene().selectedItems():
            self.scene().removeItem(item)
            if isinstance(item, SupportItem):
                self.element_deleted.emit(item.support)
            elif isinstance(item, PointLoadItem):
                self.element_deleted.emit(item.load)
            elif isinstance(item, DistributedLoadItem):
                self.element_deleted.emit(item.load)
            elif isinstance(item, TrussSegmentItem):
                self.element_deleted.emit(item.section)
        self._draw_dimensions()

    def begin_copy_mode(self, elements: list) -> None:
        self.cancel_copy_mode()
        self._copy_templates = [copy.deepcopy(e) for e in elements]
        if not self._copy_templates:
            return
        self._copy_anchor_m = min(self._element_start_m(e) for e in self._copy_templates)
        self._copy_mode = True
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._update_copy_preview(self._copy_anchor_m)

    def is_copy_mode_active(self) -> bool:
        return self._copy_mode

    def cancel_copy_mode(self) -> None:
        self._copy_mode = False
        self._copy_templates = []
        self._clear_copy_preview()
        if self._current_tool == CanvasTool.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def finish_copy_placement(self) -> None:
        self._copy_mode = False
        self._clear_copy_preview()
        if self._current_tool == CanvasTool.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _update_copy_preview(self, anchor_m: float) -> None:
        self._clear_copy_preview()
        if not self._copy_templates:
            return
        for template in self._copy_templates:
            clone = copy.deepcopy(template)
            self._move_clone_to_anchor(clone, anchor_m)
            item = self._preview_item_for(clone)
            if item is None:
                continue
            item.setOpacity(0.45)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.scene().addItem(item)
            self._copy_preview_items.append(item)

    def _clear_copy_preview(self) -> None:
        for item in self._copy_preview_items:
            try:
                if item.scene() is self.scene():
                    self.scene().removeItem(item)
            except RuntimeError:
                pass
        self._copy_preview_items.clear()

    def _preview_item_for(self, element):
        y = 0.0
        x = 0.0
        if self._project and self._active_system_id:
            system = next((s for s in self._project.systems if s.id == self._active_system_id), None)
            if system:
                y = self._system_y(system)
                x = self._system_x(system)
        if isinstance(element, TrussSection):
            item = TrussSegmentItem(element)
            item.setPos(x + element.position_m * PX_PER_M, y)
            return item
        if isinstance(element, Support):
            item = SupportItem(element)
            item.setPos(x + element.position_m * PX_PER_M, y + TRUSS_HEIGHT // 2)
            return item
        if isinstance(element, PointLoad):
            item = PointLoadItem(element)
            item.setPos(x + element.position_m * PX_PER_M, y)
            return item
        if isinstance(element, DistributedLoad):
            item = DistributedLoadItem(element)
            item.setPos(x + element.start_m * PX_PER_M, y)
            return item
        return None

    def _move_clone_to_anchor(self, element, anchor_m: float) -> None:
        offset = anchor_m - self._copy_anchor_m
        if isinstance(element, TrussSection):
            element.position_m = max(0.0, element.position_m + offset)
        elif isinstance(element, Support):
            element.position_m = max(0.0, element.position_m + offset)
        elif isinstance(element, PointLoad):
            element.position_m = max(0.0, element.position_m + offset)
        elif isinstance(element, DistributedLoad):
            length = element.end_m - element.start_m
            element.start_m = max(0.0, element.start_m + offset)
            element.end_m = element.start_m + length

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

    def selected_elements(self) -> list:
        elements = []
        for item in self.scene().selectedItems():
            element = self._element_from_item(item)
            if element is not None:
                system_id = self._element_system_ids.get(getattr(element, "id", ""))
                if self._active_system_id and system_id and system_id != self._active_system_id:
                    continue
                elements.append(element)
        return elements

    def _update_scene_rect(self) -> None:
        systems = self._visible_systems()
        if not systems:
            self.scene().setSceneRect(-500, -350, 3000, 700)
            return
        left = min(self._system_x(s) for s in systems) - 260
        right = max(self._system_x(s) + max(s.total_length_m, 1.0) * PX_PER_M for s in systems) + 420
        top = min(self._system_y(s) + DIM_Y_TOTAL - 140 for s in systems)
        bottom = max(self._system_y(s) + TRUSS_HEIGHT + 240 for s in systems)
        self.scene().setSceneRect(QRectF(left, top, max(1200, right - left), max(700, bottom - top)))

    def fit_view(self, all_systems: bool = False) -> None:
        if self._project and self._project.systems:
            if all_systems:
                systems = self._visible_systems()
            else:
                active = self._project.active_system
                systems = [active] if active else self._visible_systems()[:1]
            if not systems:
                return
            left = min(self._system_x(s) for s in systems)
            right = max(self._system_x(s) + max(s.total_length_m, 1.0) * PX_PER_M for s in systems)
            top = min(self._system_y(s) + DIM_Y_TOTAL - 100 for s in systems)
            bottom = max(self._system_y(s) + TRUSS_HEIGHT + 170 for s in systems)
            rect = QRectF(left - 80, top, max(320, right - left + 160), max(240, bottom - top))
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _element_item_at(self, view_pos):
        for item in self.items(view_pos):
            if isinstance(item, (SupportItem, PointLoadItem,
                                 DistributedLoadItem, TrussSegmentItem)):
                return item
        return None

    def _is_system_drag_hit(self, view_pos, scene_pos: QPointF, system: TrussSystem) -> bool:
        for item in self.items(view_pos):
            if isinstance(item, QGraphicsTextItem) and item.data(0) == system.id:
                return True
        label_top = self._system_y(system) + DIM_Y_TOTAL - 95
        label_bottom = self._system_y(system) + DIM_Y_TOTAL - 35
        return label_top <= scene_pos.y() <= label_bottom

    def _system_label_at(self, view_pos) -> Optional[TrussSystem]:
        if not self._project:
            return None
        for item in self.items(view_pos):
            if isinstance(item, QGraphicsTextItem):
                system_id = item.data(0)
                if system_id:
                    return next(
                        (system for system in self._project.systems if system.id == system_id),
                        None,
                    )
        return None

    def _system_rect(self, system: TrussSystem) -> QRectF:
        return QRectF(
            self._system_x(system) - 40,
            self._system_y(system) + DIM_Y_TOTAL - 120,
            max(system.total_length_m, 1.0) * PX_PER_M + 80,
            TRUSS_HEIGHT + abs(DIM_Y_TOTAL) + 190,
        )

    def _systems_overlap(self, moved: TrussSystem) -> bool:
        moved_rect = self._system_rect(moved)
        for other in self._visible_systems():
            if other.id == moved.id:
                continue
            if moved_rect.intersects(self._system_rect(other)):
                return True
        return False

    def _element_from_item(self, item):
        if isinstance(item, SupportItem):
            return item.support
        if isinstance(item, PointLoadItem):
            return item.load
        if isinstance(item, DistributedLoadItem):
            return item.load
        if isinstance(item, TrussSegmentItem):
            return item.section
        return None
