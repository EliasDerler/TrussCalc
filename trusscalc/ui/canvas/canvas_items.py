"""QGraphicsItem-Subklassen für alle Canvas-Elemente."""
import math
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsLineItem, QGraphicsEllipseItem,
    QGraphicsPolygonItem, QGraphicsTextItem,
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPen, QBrush, QColor, QPolygonF, QPainter, QFont, QPainterPath,
)

# Farb-Konstanten
COLOR_TRUSS = QColor("#C0C0C0")         # Hellgrau: Traverse
COLOR_SUPPORT_DEFAULT = QColor("#FFFFFF")
COLOR_SUPPORT_BLUE = QColor("#4488FF")
COLOR_SUPPORT_GREEN = QColor("#44BB44")
COLOR_SUPPORT_YELLOW = QColor("#FFCC00")
COLOR_SUPPORT_RED = QColor("#FF4444")
COLOR_LOAD_POINT = QColor("#FF8800")        # Orange: Punktlast
COLOR_LOAD_DIST = QColor("#CC66FF")         # Violett: Streckenlast (klar abgesetzt)
COLOR_DEFLECTION = QColor("#00AAFF")
COLOR_DEFLECTION_YELLOW = QColor("#FFCC00")
COLOR_DEFLECTION_RED = QColor("#FF4444")
COLOR_DIM_TEXT = QColor("#AAAAAA")
COLOR_SELECTED = QColor("#FFFF00")

PX_PER_M = 80.0    # Pixel pro Meter (Basis-Skalierung)
TRUSS_HEIGHT = 18  # Höhe der Traverse-Darstellung in Pixel
SUPPORT_SIZE = 22  # Größe des Auflager-Dreiecks
LOAD_ARROW_LEN = 42       # Punktlast-Pfeillänge
DIST_ARROW_LEN = 22       # Streckenlast: deutlich kürzer, näher an der Traverse
DIM_Y_SUPPORT = -75       # Y-Position der Auflager-Bemaßung (über den Lasten)
DIM_Y_TOTAL = DIM_Y_SUPPORT - 26  # Gesamtlänge-Bemaßung darüber


class TrussSegmentItem(QGraphicsItem):
    """Darstellung eines Traversenabschnitts als doppelte Linie (Fachwerk-Style)."""

    def __init__(self, section, parent=None):
        super().__init__(parent)
        self.section = section
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)

    def boundingRect(self) -> QRectF:
        w = self.section.length_m * PX_PER_M
        return QRectF(0, -TRUSS_HEIGHT, w, TRUSS_HEIGHT * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(COLOR_SELECTED if self.isSelected() else COLOR_TRUSS, 2)
        painter.setPen(pen)
        w = self.section.length_m * PX_PER_M
        h = TRUSS_HEIGHT // 2
        # Ober- und Untergurt
        painter.drawLine(QPointF(0, -h), QPointF(w, -h))
        painter.drawLine(QPointF(0, h), QPointF(w, h))
        # Diagonalstreben
        n_struts = max(2, int(self.section.length_m * 2))
        step = w / n_struts
        for i in range(n_struts):
            x = i * step
            if i % 2 == 0:
                painter.drawLine(QPointF(x, -h), QPointF(x + step, h))
            else:
                painter.drawLine(QPointF(x, h), QPointF(x + step, -h))
        # Endplatten
        pen2 = QPen(COLOR_TRUSS, 3)
        painter.setPen(pen2)
        painter.drawLine(QPointF(0, -h), QPointF(0, h))
        painter.drawLine(QPointF(w, -h), QPointF(w, h))

    def x_pos(self) -> float:
        return self.section.position_m * PX_PER_M


class SupportItem(QGraphicsItem):
    """Auflager-Dreieck (ähnlich statisches Auflager-Symbol)."""

    def __init__(self, support, parent=None):
        super().__init__(parent)
        self.support = support
        self.color = QColor(COLOR_SUPPORT_DEFAULT)
        self.reaction_text = ""
        self.lift_height_mm: float = 0.0
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        s = SUPPORT_SIZE
        # Genug Raum für Reaktionskraft-Label unten und ggf. Lift-Höhe deutlich oben
        return QRectF(-s - 30, -130, s * 2 + 60, s + 150)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        s = SUPPORT_SIZE
        pen = QPen(COLOR_SELECTED if self.isSelected() else QColor("#888888"), 2)
        painter.setPen(pen)
        painter.setBrush(QBrush(self.color))
        # Dreieck nach unten
        triangle = QPolygonF([
            QPointF(0, 0),
            QPointF(-s, s),
            QPointF(s, s),
        ])
        painter.drawPolygon(triangle)
        # Bodenplatte
        painter.setPen(QPen(QColor("#888888"), 2))
        painter.drawLine(QPointF(-s - 4, s), QPointF(s + 4, s))
        # Schraffur unter Platte
        pen_thin = QPen(QColor("#888888"), 1)
        painter.setPen(pen_thin)
        for i in range(-s - 4, s + 8, 6):
            painter.drawLine(QPointF(i, s), QPointF(i - 8, s + 8))

        # Reaktionskraft-Text
        if self.reaction_text:
            painter.setPen(QPen(COLOR_DIM_TEXT))
            font = QFont("Monospace", 8)
            painter.setFont(font)
            painter.drawText(QRectF(-30, s + 4, 60, 14), Qt.AlignmentFlag.AlignHCenter,
                             self.reaction_text)

        # Lift-off-Höhe deutlich oberhalb der Traverse (über dem Kurvenscheitel),
        # mit dünner Führungslinie zum Auflager
        if self.lift_height_mm > 0.5:
            text = f"↑ {self.lift_height_mm:.1f} mm"
            font_lift = QFont("Monospace", 9, QFont.Weight.Bold)
            painter.setFont(font_lift)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            label_y_center = -110.0
            bg = QRectF(-tw / 2 - 4,
                        label_y_center - th / 2 - 1,
                        tw + 8, th + 2)

            # Führungslinie vom oberen Auflager-Rand zur Label-Unterkante
            pen_lead = QPen(COLOR_SUPPORT_BLUE, 0.8, Qt.PenStyle.DotLine)
            painter.setPen(pen_lead)
            painter.drawLine(QPointF(0, 0), QPointF(0, bg.bottom()))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(30, 30, 30, 235)))
            painter.drawRect(bg)
            painter.setPen(QPen(COLOR_SUPPORT_BLUE))
            painter.drawText(bg, Qt.AlignmentFlag.AlignCenter, text)

    def set_color(self, color_name: str) -> None:
        mapping = {
            "blue": COLOR_SUPPORT_BLUE,
            "green": COLOR_SUPPORT_GREEN,
            "yellow": COLOR_SUPPORT_YELLOW,
            "red": COLOR_SUPPORT_RED,
            "white": COLOR_SUPPORT_DEFAULT,
        }
        self.color = mapping.get(color_name, COLOR_SUPPORT_DEFAULT)
        self.update()


class PointLoadItem(QGraphicsItem):
    """Punktlast-Pfeil (von oben nach unten)."""

    def __init__(self, load, parent=None):
        super().__init__(parent)
        self.load = load
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(-40, -LOAD_ARROW_LEN - 36, 80, LOAD_ARROW_LEN + 36)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(COLOR_SELECTED if self.isSelected() else COLOR_LOAD_POINT, 2)
        painter.setPen(pen)
        painter.setBrush(QBrush(COLOR_LOAD_POINT))
        # Pfeilschaft
        painter.drawLine(QPointF(0, -LOAD_ARROW_LEN), QPointF(0, -TRUSS_HEIGHT // 2 - 2))
        # Pfeilspitze
        tip = QPointF(0, -TRUSS_HEIGHT // 2 - 2)
        arrowhead = QPolygonF([
            tip,
            QPointF(-6, tip.y() - 12),
            QPointF(6, tip.y() - 12),
        ])
        painter.drawPolygon(arrowhead)

        # Zweizeilige Beschriftung: Lastwert (fett, Orange) + Position (dezent, grau)
        text_value = f"{self.load.load_kg:.0f} kg"
        text_pos = f"@ {self.load.position_m * 100:.0f} cm"
        font_main = QFont("Monospace", 8, QFont.Weight.Bold)
        font_sub = QFont("Monospace", 7)

        painter.setFont(font_main)
        fm_main = painter.fontMetrics()
        tw_main = fm_main.horizontalAdvance(text_value)
        th_main = fm_main.height()

        painter.setFont(font_sub)
        fm_sub = painter.fontMetrics()
        tw_sub = fm_sub.horizontalAdvance(text_pos)
        th_sub = fm_sub.height()

        tw = max(tw_main, tw_sub)
        total_h = th_main + th_sub
        bg = QRectF(-tw / 2 - 3, -LOAD_ARROW_LEN - total_h - 2,
                    tw + 6, total_h + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 30, 220)))
        painter.drawRect(bg)

        painter.setFont(font_main)
        painter.setPen(QPen(COLOR_LOAD_POINT))
        main_rect = QRectF(bg.x(), bg.y() + 1, bg.width(), th_main)
        painter.drawText(main_rect, Qt.AlignmentFlag.AlignCenter, text_value)

        painter.setFont(font_sub)
        painter.setPen(QPen(COLOR_DIM_TEXT))
        sub_rect = QRectF(bg.x(), bg.y() + 1 + th_main, bg.width(), th_sub)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, text_pos)


class DistributedLoadItem(QGraphicsItem):
    """Streckenlast-Darstellung (mehrere Pfeile + Balken)."""

    def __init__(self, load, parent=None):
        super().__init__(parent)
        self.load = load
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def boundingRect(self) -> QRectF:
        w = (self.load.end_m - self.load.start_m) * PX_PER_M
        return QRectF(0, -DIST_ARROW_LEN - 36, w, DIST_ARROW_LEN + 36)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        w = (self.load.end_m - self.load.start_m) * PX_PER_M
        pen = QPen(COLOR_SELECTED if self.isSelected() else COLOR_LOAD_DIST, 1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(COLOR_LOAD_DIST))
        arrow_y_top = -DIST_ARROW_LEN
        arrow_y_bot = -TRUSS_HEIGHT // 2 - 2
        # Horizontale Linie oben (Bracket)
        painter.drawLine(QPointF(0, arrow_y_top), QPointF(w, arrow_y_top))
        # Einzelne Pfeile (kürzere Spitzen, da Pfeile insgesamt kürzer)
        n = max(2, int(w / 20))
        for i in range(n + 1):
            x = i * w / n
            painter.drawLine(QPointF(x, arrow_y_top), QPointF(x, arrow_y_bot))
            arrowhead = QPolygonF([
                QPointF(x, arrow_y_bot),
                QPointF(x - 3, arrow_y_bot - 6),
                QPointF(x + 3, arrow_y_bot - 6),
            ])
            painter.drawPolygon(arrowhead)
        # Zweizeilig: Lastwert + Bereich
        text_value = f"{self.load.load_kg_per_m:.1f} kg/m"
        text_pos = (f"{self.load.start_m * 100:.0f} – "
                    f"{self.load.end_m * 100:.0f} cm")
        font_main = QFont("Monospace", 8, QFont.Weight.Bold)
        font_sub = QFont("Monospace", 7)

        painter.setFont(font_main)
        fm_main = painter.fontMetrics()
        tw_main = fm_main.horizontalAdvance(text_value)
        th_main = fm_main.height()

        painter.setFont(font_sub)
        fm_sub = painter.fontMetrics()
        tw_sub = fm_sub.horizontalAdvance(text_pos)
        th_sub = fm_sub.height()

        tw = max(tw_main, tw_sub)
        total_h = th_main + th_sub
        bg = QRectF(w / 2 - tw / 2 - 3, arrow_y_top - total_h - 2,
                    tw + 6, total_h + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 30, 220)))
        painter.drawRect(bg)

        painter.setFont(font_main)
        painter.setPen(QPen(COLOR_LOAD_DIST))
        main_rect = QRectF(bg.x(), bg.y() + 1, bg.width(), th_main)
        painter.drawText(main_rect, Qt.AlignmentFlag.AlignCenter, text_value)

        painter.setFont(font_sub)
        painter.setPen(QPen(COLOR_DIM_TEXT))
        sub_rect = QRectF(bg.x(), bg.y() + 1 + th_main, bg.width(), th_sub)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, text_pos)


class DeflectionCurveItem(QGraphicsItem):
    """Durchbiegungskurve als Pfad unter der Traverse."""

    MAX_VISIBLE_PX = 90.0   # max. Amplitude der Kurve auf dem Canvas (px)
    MIN_VISIBLE_PX = 14.0   # bei sehr kleiner Durchbiegung mind. so hoch

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = QPainterPath()
        self._color = COLOR_DEFLECTION
        # Liste von Beschriftungen: jede ist (anchor: QPointF, value_text, pos_text)
        self._labels: list[tuple[QPointF, str, str]] = []

    def set_result(self, positions_m: list[float], deflections_mm: list[float],
                   color_name: str, max_text: str,
                   max_position_m: float | None = None) -> None:
        self._color = {
            "green": COLOR_DEFLECTION,
            "yellow": COLOR_DEFLECTION_YELLOW,
            "red": COLOR_DEFLECTION_RED,
        }.get(color_name, COLOR_DEFLECTION)
        self._labels = []

        self._path = QPainterPath()
        if not positions_m:
            return

        # Dynamische Skalierung: max. Amplitude (signed) in px begrenzen
        max_abs = max((abs(d) for d in deflections_mm), default=0.0)
        if max_abs <= 0:
            return
        visual_scale = min(5.0, self.MAX_VISIBLE_PX / max_abs)
        if max_abs * visual_scale < self.MIN_VISIBLE_PX:
            visual_scale = self.MIN_VISIBLE_PX / max_abs

        # Konvention (AnaStruct): deflections_mm > 0 → abwärts (Traverse sackt
        # nach unten), deflections_mm < 0 → aufwärts. Auf dem Canvas wächst y
        # nach unten, daher passt: y = y_off + d · scale (signed).
        y_off = TRUSS_HEIGHT // 2 + 4
        px_vals = [(p * PX_PER_M, y_off + d * visual_scale)
                   for p, d in zip(positions_m, deflections_mm)]
        self._path.moveTo(px_vals[0][0], y_off)
        for px, py in px_vals:
            self._path.lineTo(px, py)
        self._path.lineTo(px_vals[-1][0], y_off)

        # Lokale Maxima (egal ob abwärts oder aufwärts)
        peak_indices = self._local_max_indices(deflections_mm,
                                               threshold=max_abs * 0.25)

        for idx in peak_indices:
            d_signed = deflections_mm[idx]
            d_abs = abs(d_signed)
            if d_abs <= 0:
                continue
            # Label-Anker: jenseits der Kurve – unten bei abwärts, oben bei aufwärts
            curve_y = px_vals[idx][1]
            if d_signed > 0:  # abwärts → Label unter der Kurve
                anchor_y = min(curve_y + 16, y_off + self.MAX_VISIBLE_PX + 16)
            else:  # aufwärts → Label über der Kurve
                anchor_y = max(curve_y - 16, y_off - self.MAX_VISIBLE_PX - 16)
            anchor = QPointF(px_vals[idx][0], anchor_y)
            arrow = "↓" if d_signed > 0 else "↑"
            value_text = f"{arrow}{d_abs:.1f} mm"
            pos_text = f"@ {positions_m[idx] * 100:.0f} cm"
            self._labels.append((anchor, value_text, pos_text))

        self.prepareGeometryChange()
        self.update()

    @staticmethod
    def _local_max_indices(values: list[float], threshold: float) -> list[int]:
        """Indizes der signifikanten lokalen Maxima (in |values|), die
        über ``threshold`` liegen. Cluster eng beieinander liegender Peaks
        werden zusammengefasst."""
        n = len(values)
        if n < 3:
            return [int(max(range(n), key=lambda i: abs(values[i])))] if n else []
        abs_vals = [abs(v) for v in values]

        candidates: list[int] = []
        i = 1
        while i < n - 1:
            if abs_vals[i] >= threshold and \
                    abs_vals[i] >= abs_vals[i - 1] and \
                    abs_vals[i] >= abs_vals[i + 1]:
                # Plateau überspringen (Index in der Mitte des Plateaus wählen)
                j = i
                while j + 1 < n - 1 and abs_vals[j + 1] == abs_vals[i]:
                    j += 1
                candidates.append((i + j) // 2)
                i = j + 1
            else:
                i += 1

        # Cluster zusammenführen, falls zwei "Peaks" sehr nahe beieinander
        if not candidates:
            return [int(max(range(n), key=lambda k: abs_vals[k]))]
        cluster_dist = max(1, n // 30)  # mind. ~3% Abstand
        merged: list[int] = [candidates[0]]
        for c in candidates[1:]:
            if c - merged[-1] < cluster_dist:
                # Höheren behalten
                if abs_vals[c] > abs_vals[merged[-1]]:
                    merged[-1] = c
            else:
                merged.append(c)
        return merged

    def boundingRect(self) -> QRectF:
        if self._path.isEmpty():
            return QRectF()
        # Genug Raum für Labels in beiden Richtungen (Lift-off möglich)
        rect = self._path.boundingRect().adjusted(-30, -40, 30, 40)
        for anchor, _, _ in self._labels:
            rect = rect.united(QRectF(anchor.x() - 60, anchor.y() - 20, 120, 40))
        return rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._path.isEmpty():
            return
        pen = QPen(self._color, 2)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(self._color.red(), self._color.green(),
                                       self._color.blue(), 60)))
        painter.drawPath(self._path)

        font_main = QFont("Monospace", 9, QFont.Weight.Bold)
        font_sub = QFont("Monospace", 8)
        for anchor, value_text, pos_text in self._labels:
            painter.setFont(font_main)
            fm_main = painter.fontMetrics()
            tw_main = fm_main.horizontalAdvance(value_text)
            th_main = fm_main.height()

            tw_sub = th_sub = 0
            if pos_text:
                painter.setFont(font_sub)
                fm_sub = painter.fontMetrics()
                tw_sub = fm_sub.horizontalAdvance(pos_text)
                th_sub = fm_sub.height()

            tw = max(tw_main, tw_sub)
            total_h = th_main + (th_sub if pos_text else 0) + 2
            bg = QRectF(anchor.x() - tw / 2 - 4,
                        anchor.y() - total_h / 2 - 1,
                        tw + 8, total_h + 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(30, 30, 30, 230)))
            painter.drawRect(bg)

            painter.setFont(font_main)
            painter.setPen(QPen(self._color))
            main_rect = QRectF(bg.x(), bg.y() + 1, bg.width(), th_main)
            painter.drawText(main_rect, Qt.AlignmentFlag.AlignCenter, value_text)

            if pos_text:
                painter.setFont(font_sub)
                painter.setPen(QPen(COLOR_DIM_TEXT))
                sub_rect = QRectF(bg.x(), bg.y() + 1 + th_main, bg.width(), th_sub)
                painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, pos_text)


COLOR_DIM_TOTAL = QColor("#666666")      # Grau: Gesamtlänge
COLOR_DIM_SUPPORT = QColor("#4488FF")    # Blau: Auflager-Abstände
COLOR_DIM_LOAD = QColor("#FF8844")       # Orange: Last-Positionen


class DimensionItem(QGraphicsItem):
    """Bemaßungslinie zwischen zwei Positionen mit konfigurierbarer Farbe."""

    def __init__(self, x1: float, x2: float, label: str, y_offset: float = 0,
                 color: QColor = None, parent=None):
        super().__init__(parent)
        self._x1 = x1
        self._x2 = x2
        self._label = label
        self._y = y_offset
        self._color = color or COLOR_DIM_TEXT

    def boundingRect(self) -> QRectF:
        return QRectF(self._x1, self._y - 22, self._x2 - self._x1, 24)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen_dash = QPen(self._color, 0.8, Qt.PenStyle.DashLine)
        pen_solid = QPen(self._color, 1.2)

        # Hilfslinie links und rechts (vertikal)
        painter.setPen(pen_dash)
        painter.drawLine(QPointF(self._x1, self._y - 16), QPointF(self._x1, self._y))
        painter.drawLine(QPointF(self._x2, self._y - 16), QPointF(self._x2, self._y))

        # Horizontale Maßlinie
        painter.setPen(pen_solid)
        painter.drawLine(QPointF(self._x1, self._y - 8), QPointF(self._x2, self._y - 8))

        # Pfeilspitzen
        a = 5
        painter.drawLine(QPointF(self._x1, self._y - 8), QPointF(self._x1 + a, self._y - 8 - a))
        painter.drawLine(QPointF(self._x1, self._y - 8), QPointF(self._x1 + a, self._y - 8 + a))
        painter.drawLine(QPointF(self._x2, self._y - 8), QPointF(self._x2 - a, self._y - 8 - a))
        painter.drawLine(QPointF(self._x2, self._y - 8), QPointF(self._x2 - a, self._y - 8 + a))

        # Beschriftung mit weißem Hintergrund-Rechteck für Lesbarkeit
        mid = (self._x1 + self._x2) / 2
        font = QFont("Monospace", 8)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(self._label)
        th = fm.height()
        bg_rect = QRectF(mid - tw / 2 - 2, self._y - 8 - th / 2 - 1, tw + 4, th + 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(30, 30, 30, 200)))
        painter.drawRect(bg_rect)
        painter.setPen(pen_solid)
        painter.drawText(QRectF(mid - tw / 2 - 2, self._y - 8 - th / 2, tw + 4, th + 2),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         self._label)
