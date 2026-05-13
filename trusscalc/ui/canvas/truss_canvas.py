"""
2D-Canvas für die Traversen-Visualisierung.
LTSpice-inspiriert: Raster, Pan/Zoom, Werkzeug-basierte Platzierung.
"""
import uuid
import copy
from typing import Optional

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QWheelEvent, QMouseEvent, QPainter

from trusscalc.core.models import (
    TrussSection, Support, PointLoad, DistributedLoad,
    CalculationResult, Project, UnitSystem,
)
from trusscalc.ui.canvas.canvas_items import (
    TrussSegmentItem, SupportItem, PointLoadItem, DistributedLoadItem,
    DeflectionCurveItem, DimensionItem, PX_PER_M, TRUSS_HEIGHT,
    COLOR_DIM_TOTAL, COLOR_DIM_SUPPORT,
    DIM_Y_SUPPORT, DIM_Y_TOTAL,
)
from trusscalc.ui.canvas.canvas_tools import CanvasTool
from trusscalc.core import color_rules

GRID_SIZE = 20      # Rastergröße in Pixel
GRID_COLOR = QColor("#2A2A2A")
BG_COLOR = QColor("#1E1E1E")     # Dunkler LTSpice-Hintergrund


class TrussCanvas(QGraphicsView):
    """Hauptcanvas für die Traversenvisualisierung."""

    element_selected = pyqtSignal(object)   # Selektiertes Element (Support/Load/Section)
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
        self._current_tool = CanvasTool.SELECT
        self._dist_load_start: Optional[float] = None
        self._panning = False
        self._pan_last_pos = None
        self._copy_mode = False
        self._copy_templates: list = []
        self._copy_anchor_m = 0.0
        self._copy_preview_items: list[QGraphicsItem] = []

        # Canvas-Items (Position_id → Item)
        self._section_items: dict[str, TrussSegmentItem] = {}
        self._support_items: dict[str, SupportItem] = {}
        self._load_items: dict[str, PointLoadItem | DistributedLoadItem] = {}
        self._deflection_item: Optional[DeflectionCurveItem] = None
        self._dim_items: list[DimensionItem] = []

    def _setup_view(self) -> None:
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(BG_COLOR))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scene().setSceneRect(-500, -350, 3000, 700)

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
        self.cancel_copy_mode()
        self._project = project
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
        self._dim_items.clear()

        if not self._project:
            return

        for section in self._project.sections:
            self._add_section_item(section)

        for support in self._project.supports:
            self._add_support_item(support)

        for pl in self._project.point_loads:
            self._add_point_load_item(pl)

        for dl in self._project.distributed_loads:
            self._add_dist_load_item(dl)

        self._draw_dimensions()

    # ── Element hinzufügen ────────────────────────────────────────────────────

    def _add_section_item(self, section: TrussSection) -> TrussSegmentItem:
        item = TrussSegmentItem(section)
        item.setPos(section.position_m * PX_PER_M, 0)
        self.scene().addItem(item)
        self._section_items[section.id] = item
        return item

    def _add_support_item(self, support: Support) -> SupportItem:
        item = SupportItem(support)
        item.setPos(support.position_m * PX_PER_M, TRUSS_HEIGHT // 2)
        self.scene().addItem(item)
        self._support_items[support.id] = item
        return item

    def _add_point_load_item(self, load: PointLoad) -> PointLoadItem:
        item = PointLoadItem(load)
        item.setPos(load.position_m * PX_PER_M, 0)
        self.scene().addItem(item)
        self._load_items[load.id] = item
        return item

    def _add_dist_load_item(self, load: DistributedLoad) -> DistributedLoadItem:
        item = DistributedLoadItem(load)
        item.setPos(load.start_m * PX_PER_M, 0)
        self.scene().addItem(item)
        self._load_items[load.id] = item
        return item

    def _draw_dimensions(self) -> None:
        for item in self._dim_items:
            self.scene().removeItem(item)
        self._dim_items.clear()
        if not self._project:
            return

        total = self._project.total_length_m

        # Gesamtlänge: grau, ganz oben
        if total > 0:
            item = DimensionItem(0, total * PX_PER_M,
                                 f"Gesamt: {total*100:.0f} cm",
                                 DIM_Y_TOTAL, color=COLOR_DIM_TOTAL)
            self.scene().addItem(item)
            self._dim_items.append(item)

        # Auflager-Abstände: blau, über den Lasten
        all_positions = sorted([s.position_m for s in self._project.supports])
        if all_positions:
            # Alle Segmente zwischen Auflagern (inkl. Enden wenn kein Auflager dort)
            segment_points = sorted({0.0, total} | set(all_positions))
            for i in range(len(segment_points) - 1):
                x1 = segment_points[i]
                x2 = segment_points[i + 1]
                if x2 - x1 < 1e-6:
                    continue
                item = DimensionItem(
                    x1 * PX_PER_M, x2 * PX_PER_M,
                    f"{(x2 - x1) * 100:.0f} cm",
                    DIM_Y_SUPPORT, color=COLOR_DIM_SUPPORT,
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

    def clear_results(self) -> None:
        if self._deflection_item:
            self.scene().removeItem(self._deflection_item)
            self._deflection_item = None
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
        pos_m = scene_pos.x() / PX_PER_M

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
            super().mousePressEvent(event)
            items = self.scene().selectedItems()
            if items:
                element = self._element_from_item(items[0])
                if element is not None:
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
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
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
            self._update_copy_preview(max(0.0, scene_pos.x() / PX_PER_M))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self.copy_requested.emit()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            self.paste_requested.emit()
            event.accept()
            return
        if mods == Qt.KeyboardModifier.NoModifier and key == Qt.Key.Key_M:
            self.mirror_requested.emit()
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
        self._add_section_item(section)
        self._draw_dimensions()

    def add_support_to_scene(self, support: Support) -> None:
        self._add_support_item(support)
        self._draw_dimensions()

    def add_point_load_to_scene(self, load: PointLoad) -> None:
        self._add_point_load_item(load)

    def add_dist_load_to_scene(self, load: DistributedLoad) -> None:
        self._add_dist_load_item(load)

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
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._copy_preview_items.clear()

    def _preview_item_for(self, element):
        if isinstance(element, TrussSection):
            item = TrussSegmentItem(element)
            item.setPos(element.position_m * PX_PER_M, 0)
            return item
        if isinstance(element, Support):
            item = SupportItem(element)
            item.setPos(element.position_m * PX_PER_M, TRUSS_HEIGHT // 2)
            return item
        if isinstance(element, PointLoad):
            item = PointLoadItem(element)
            item.setPos(element.position_m * PX_PER_M, 0)
            return item
        if isinstance(element, DistributedLoad):
            item = DistributedLoadItem(element)
            item.setPos(element.start_m * PX_PER_M, 0)
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
                elements.append(element)
        return elements

    def fit_view(self) -> None:
        if self._project and self._project.total_length_m > 0:
            rect = QRectF(-50, DIM_Y_TOTAL - 30,
                          self._project.total_length_m * PX_PER_M + 100,
                          abs(DIM_Y_TOTAL) + 200)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _element_item_at(self, view_pos):
        for item in self.items(view_pos):
            if isinstance(item, (SupportItem, PointLoadItem,
                                 DistributedLoadItem, TrussSegmentItem)):
                return item
        return None

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
