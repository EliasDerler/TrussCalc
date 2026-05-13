"""PDF-Report-Generator im NoiseGate-Branding (Vorlage Design2).

Erzeugt einen Report mit dunkelblauem Header, Kacheln für Auflagerwerte,
nummerierten Sektionen, Hinweisbox und Signaturen. Sprache DE/EN umschaltbar.
"""
from __future__ import annotations

import datetime
from collections import Counter
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, BaseDocTemplate, PageTemplate, Frame,
    NextPageTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, KeepTogether,
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.graphics.shapes import (
    Drawing, Line, Rect, String, Polygon, PolyLine,
)
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas as _canvas

from trusscalc.core.models import (
    Project, TrussType, CalculationResult,
)
from trusscalc.pdf.i18n import tr

PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm

# ── Farbpalette (NoiseGate-Branding) ───────────────────────────────────────
NAVY = HexColor("#0B1328")          # dunkler Header-Hintergrund
NAVY_LIGHT = HexColor("#10283A")    # leichte Aufhellung
TEAL = HexColor("#086D73")          # Akzent / Highlight
TEAL_DARK = HexColor("#087D72")     # dunkleres Teal (Badges)
TEAL_LIGHT = HexColor("#E6F5F1")    # heller Hintergrund für „save"-Karten

TEXT_DARK = HexColor("#1A2530")     # Haupt-Text
TEXT_MUTED = HexColor("#6C7785")    # Hilfstext
TEXT_LIGHT = HexColor("#9AA5B1")    # Sub-Beschriftungen

CARD_BG = HexColor("#F7F8FA")
CARD_BORDER = HexColor("#E2E7EB")
TABLE_HEAD_BG = HexColor("#F4F6F8")
TABLE_ROW_ALT = HexColor("#FAFBFC")
BG_PAGE = HexColor("#FFFFFF")

STATUS_OK = HexColor("#1FB386")
STATUS_WARN = HexColor("#F0A500")
STATUS_OVER = HexColor("#E74C3C")
STATUS_LIFT = HexColor("#4488FF")

NOTICE_BG = HexColor("#FEF8E1")
NOTICE_BORDER = HexColor("#F0A500")

SOFTWARE_VERSION = "TrussCalc v2.4.1"
CARD_RADIUS = 6


_LOGO_CACHE: dict = {"reader": None, "loaded": False}


def _get_logo_image_reader():
    """Lazy-loaded ImageReader des NoiseGate-Logos.

    Die Original-PDF ist schwarz – für die Anzeige auf dem dunklen Header
    werden die schwarzen Pixel invertiert (= weiß), während die Transparenz
    erhalten bleibt."""
    if _LOGO_CACHE["loaded"]:
        return _LOGO_CACHE["reader"]
    _LOGO_CACHE["loaded"] = True
    try:
        import pymupdf
        from PIL import Image, ImageOps, ImageChops
        from io import BytesIO
        from trusscalc.database.db_manager import _resources_path
        logo_path = _resources_path() / "logo_noisegate.pdf"
        if not logo_path.exists():
            return None
        d = pymupdf.open(str(logo_path))
        pix = d[0].get_pixmap(dpi=150, alpha=True)
        img_bytes = pix.tobytes("png")
        d.close()
        # Schwarz → Weiß invertieren, Alpha erhalten
        from PIL import Image as _PILImage
        _PILImage.MAX_IMAGE_PIXELS = None  # Logo-PDFs sind unkritisch
        img = Image.open(BytesIO(img_bytes)).convert("RGBA")
        r, g, b, a = img.split()
        gray = Image.merge("RGB", (r, g, b)).convert("L")
        ink_alpha = gray.point(lambda v: 0 if v < 16 else v)
        alpha = ImageChops.multiply(ink_alpha, a)
        result = Image.new("RGBA", img.size, (255, 255, 255, 0))
        result.putalpha(alpha)
        buf = BytesIO()
        result.save(buf, format="PNG")
        buf.seek(0)
        _LOGO_CACHE["reader"] = ImageReader(buf)
    except Exception:
        _LOGO_CACHE["reader"] = None
    return _LOGO_CACHE["reader"]


def _spaced(text: str) -> str:
    """Letter-spaced uppercase labels matching the Design2 reference."""
    return " ".join(text.upper())


# ── Hauptfunktion ──────────────────────────────────────────────────────────

def generate_report(
    path: str,
    project: Project,
    truss_type: TrussType,
    result: CalculationResult,
    datasheet_pdf_bytes: Optional[bytes] = None,
    metadata=None,
) -> None:
    """Erzeugt den PDF-Report. ``metadata`` ist ein ReportMetadata-Dataclass."""
    if metadata is None:
        from trusscalc.ui.dialogs.report_metadata_dialog import ReportMetadata
        metadata = ReportMetadata(
            language="de",
            project_name=project.name or "Projekt",
            sub_project_name="",
            creator_email="info@noisegate.at",
        )

    lang = metadata.language
    styles = _styles(lang)

    # BaseDocTemplate mit zwei Frames – damit das Header-Band auf Seite 1
    # bündig bis zum oberen Seitenrand reicht (kein Frame-Padding).
    doc = BaseDocTemplate(
        path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=0, bottomMargin=1.5 * cm,
        title=metadata.project_name,
        author=metadata.creator_email or "TrussCalc",
    )
    frame_first = Frame(
        MARGIN, 1.5 * cm,
        PAGE_W - 2 * MARGIN, PAGE_H - 1.5 * cm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="first",
    )
    frame_later = Frame(
        MARGIN, 1.5 * cm,
        PAGE_W - 2 * MARGIN, PAGE_H - 1.5 * cm - 1.5 * cm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="later",
    )
    doc.addPageTemplates([
        PageTemplate(id="first", frames=frame_first),
        PageTemplate(id="later", frames=frame_later),
    ])

    story: list = []

    # Header-Band (nur Seite 1)
    story.append(_HeaderBand(
        title=metadata.project_name,
        subtitle=metadata.sub_project_name,
        truss_type=truss_type,
        project=project,
        lang=lang,
    ))
    story.append(Spacer(1, 0.85 * cm))

    # Kacheln-Reihe
    story.append(_build_card_row(result, project, lang))
    story.append(Spacer(1, 0.6 * cm))

    # 1) Statisches System
    story.append(_section_header(1, tr(lang, "section_static"),
                                  tr(lang, "section_static_sub"), styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_schema_card(project, result, truss_type))
    # Ab Seite 2 anderes Template (mit Top-Margin, ohne Header-Band)
    story.append(NextPageTemplate("later"))
    story.append(PageBreak())

    # 2) Auflagerkräfte
    story.append(_section_header(2, tr(lang, "section_reactions"),
                                  tr(lang, "section_reactions_sub"), styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_reactions_table(result, lang, styles))
    story.append(Spacer(1, 0.5 * cm))

    # 3) Durchbiegungsanalyse
    story.append(_section_header(3, tr(lang, "section_deflection"),
                                  tr(lang, "section_deflection_sub"), styles))
    story.append(Spacer(1, 0.2 * cm))
    fields = _detect_fields(project, result)
    story.append(_deflection_summary_card(result, len(fields), lang, styles))
    story.append(Spacer(1, 0.3 * cm))
    if fields:
        story.append(_field_cards(fields, result, lang, styles))
        story.append(Spacer(1, 0.5 * cm))

    # 4) Stückliste
    story.append(_section_header(4, tr(lang, "section_partlist"),
                                  tr(lang, "section_partlist_sub"), styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_partlist_table(project, truss_type, lang, styles))
    story.append(Spacer(1, 0.6 * cm))

    # Wichtiger Hinweis
    story.append(_notice_box(lang, styles))
    story.append(Spacer(1, 0.5 * cm))

    # Signaturen
    story.append(_signature_block(lang, styles))

    # Footer-Drawer benötigt Daten → Closure
    footer = _make_footer_drawer(metadata, lang)

    doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(
        *a, footer_drawer=footer, **kw))

    # Datenblatt anhängen
    if datasheet_pdf_bytes:
        _append_datasheet(path, datasheet_pdf_bytes)


# ── Styles ─────────────────────────────────────────────────────────────────

def _styles(lang: str) -> dict:
    return {
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=9.5, leading=12,
            textColor=TEXT_DARK,
        ),
        "body_muted": ParagraphStyle(
            "body_muted", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=TEXT_MUTED,
        ),
        "section_title": ParagraphStyle(
            "section_title", fontName="Helvetica-Bold", fontSize=13,
            leading=16, textColor=TEXT_DARK,
        ),
        "section_sub": ParagraphStyle(
            "section_sub", fontName="Helvetica", fontSize=8.5,
            leading=11, textColor=TEXT_MUTED, alignment=TA_RIGHT,
        ),
        "card_label": ParagraphStyle(
            "card_label", fontName="Helvetica-Bold", fontSize=7.5,
            leading=10, textColor=TEXT_MUTED,
        ),
        "card_label_white": ParagraphStyle(
            "card_label_white", fontName="Helvetica-Bold", fontSize=7.5,
            leading=10, textColor=colors.white,
        ),
        "card_value": ParagraphStyle(
            "card_value", fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=TEXT_DARK,
        ),
        "card_value_white": ParagraphStyle(
            "card_value_white", fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=colors.white,
        ),
        "card_unit": ParagraphStyle(
            "card_unit", fontName="Helvetica", fontSize=10,
            leading=14, textColor=TEXT_MUTED,
        ),
        "card_unit_white": ParagraphStyle(
            "card_unit_white", fontName="Helvetica", fontSize=10,
            leading=14, textColor=HexColor("#C8E0DA"),
        ),
        "card_sub": ParagraphStyle(
            "card_sub", fontName="Helvetica", fontSize=8.5,
            leading=11, textColor=TEXT_MUTED,
        ),
        "card_sub_white": ParagraphStyle(
            "card_sub_white", fontName="Helvetica", fontSize=8.5,
            leading=11, textColor=HexColor("#C8E0DA"),
        ),
        "notice_title": ParagraphStyle(
            "notice_title", fontName="Helvetica-Bold", fontSize=9.5,
            leading=12, textColor=HexColor("#7A5A00"),
        ),
        "notice_text": ParagraphStyle(
            "notice_text", fontName="Helvetica", fontSize=8.5,
            leading=12, textColor=HexColor("#7A5A00"),
        ),
        "sig_label": ParagraphStyle(
            "sig_label", fontName="Helvetica-Bold", fontSize=7.5,
            leading=10, textColor=TEXT_MUTED,
        ),
        "sig_hint": ParagraphStyle(
            "sig_hint", fontName="Helvetica", fontSize=8,
            leading=11, textColor=TEXT_MUTED,
        ),
    }


# ── Header-Band (Page 1, dunkler Bereich) ──────────────────────────────────

class _HeaderBand(Flowable):
    """Dunkler Header-Bereich oben auf Seite 1 mit Titel + Metadaten."""
    HEIGHT = 8.75 * cm

    def __init__(self, title: str, subtitle: str, truss_type: TrussType,
                 project: Project, lang: str) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.truss_type = truss_type
        self.project = project
        self.lang = lang

    def wrap(self, avail_w: float, avail_h: float):
        # Layoutgröße = Frame-Breite, gezeichnet wird über translate aber bis
        # zum Seitenrand (Bleed über die Margins hinaus).
        self.width = avail_w
        self.height = self.HEIGHT
        return self.width, self.height

    def draw(self):
        c = self.canv
        # Hintergrund über volle Seitenbreite (auch in den Margin-Bereich)
        c.saveState()
        c.translate(-MARGIN, 0)
        steps = 32
        for i in range(steps):
            t = i / max(steps - 1, 1)
            r = int(11 + (16 - 11) * t)
            g = int(19 + (40 - 19) * t)
            b = int(40 + (58 - 40) * t)
            c.setFillColor(colors.Color(r / 255, g / 255, b / 255))
            y = self.HEIGHT * i / steps
            c.rect(0, y, PAGE_W, self.HEIGHT / steps + 1, fill=1, stroke=0)
        c.setFillColor(HexColor("#0A1024"))
        c.rect(0, 0, PAGE_W, 1.45 * cm, fill=1, stroke=0)

        inner_x = MARGIN
        inner_w = PAGE_W - 2 * MARGIN
        top_y = self.HEIGHT - 1.55 * cm

        # Kleiner Header-Label oben links
        c.setFillColor(HexColor("#5FF0E6"))
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(inner_x, top_y, _spaced(tr(self.lang, "report_title_header")))

        # NoiseGate-Logo oben rechts (falls verfügbar) oder Wortmarken-Fallback
        logo = _get_logo_image_reader()
        if logo is not None:
            try:
                iw, ih = logo.getSize()
                target_h = 1.05 * cm  # Höhe des Logos
                target_w = iw * target_h / ih if ih > 0 else 3.0 * cm
                # Begrenzen falls zu breit
                max_w = 4.8 * cm
                if target_w > max_w:
                    target_w = max_w
                    target_h = ih * target_w / iw if iw > 0 else 1.0 * cm
                c.drawImage(
                    logo,
                    PAGE_W - MARGIN - target_w,
                    top_y - target_h + 0.20 * cm,
                    width=target_w, height=target_h,
                    mask="auto", preserveAspectRatio=True,
                )
            except Exception:
                c.setFillColor(colors.white)
                c.setFont("Helvetica-Bold", 12)
                c.drawRightString(PAGE_W - MARGIN, top_y - 1, "NoiseGate")
        else:
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 12)
            c.drawRightString(PAGE_W - MARGIN, top_y - 1, "NoiseGate")

        # Haupt-Titel
        title_y = top_y - 1.45 * cm
        c.setFillColor(colors.white)
        title_font = "Helvetica-Bold"
        title_size = 30
        c.setFont(title_font, title_size)
        # Titel evtl. zweizeilig wenn lang
        title_text = self.title or self.project.name or "Projekt"
        max_title_w = inner_w * 0.62
        if c.stringWidth(title_text, title_font, title_size) > max_title_w:
            # umbrechen am letzten Leerzeichen
            words = title_text.split(" ")
            line1, line2 = title_text, ""
            for i in range(len(words), 0, -1):
                candidate = " ".join(words[:i])
                if c.stringWidth(candidate, title_font, title_size) <= max_title_w:
                    line1 = candidate
                    line2 = " ".join(words[i:])
                    break
            c.drawString(inner_x, title_y, line1)
            c.drawString(inner_x, title_y - 0.88 * cm, line2)
            title_bottom = title_y - 0.88 * cm
        else:
            c.drawString(inner_x, title_y, title_text)
            title_bottom = title_y

        # Untertitel
        if self.subtitle:
            c.setFillColor(HexColor("#9DBAC8"))
            c.setFont("Helvetica", 11.5)
            c.drawString(inner_x, title_bottom - 0.75 * cm, self.subtitle)

        # Trennlinie
        sep_y = 2.7 * cm
        c.setStrokeColor(HexColor("#1F3A53"))
        c.setLineWidth(0.5)
        c.line(inner_x, sep_y, PAGE_W - MARGIN, sep_y)

        # 3 Spalten Metadaten unten (Software ist in die Fußzeile gewandert,
        # damit TRAVERSENTYP genug Platz für lange Namen hat)
        cols = [
            (tr(self.lang, "date"),
             datetime.datetime.now().strftime("%d.%m.%Y, %H:%M"),
             0.24),  # Anteil der Innenbreite
            (tr(self.lang, "software"), SOFTWARE_VERSION, 0.24),
            (tr(self.lang, "truss_type"), self.truss_type.display_name, 0.34),
            (tr(self.lang, "total_length"),
             f"{self.project.total_length_m * 100:.0f} cm", 0.18),
        ]
        cur_x = inner_x
        for label, value, frac in cols:
            col_w = inner_w * frac
            c.setFillColor(HexColor("#9DBAC8"))
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(cur_x, 1.85 * cm, _spaced(label))
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(cur_x, 1.1 * cm,
                         _truncate(value, c, "Helvetica-Bold", 10,
                                    col_w - 0.3 * cm))
            cur_x += col_w

        c.restoreState()


def _truncate(text: str, c, font: str, size: int, max_w: float) -> str:
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


# ── Karten-Reihe (Auflager + max Durchbiegung) ─────────────────────────────

def _build_card_row(result: CalculationResult, project: Project,
                     lang: str) -> Table:
    n_supports = len(result.support_results)
    # Höchstbelastetes Auflager bestimmen – nur markieren, wenn es sich
    # signifikant (> 1 %) von den anderen aktiven Auflagern abhebt.
    active = [sr for sr in result.support_results if sr.is_active]
    main_idx = -1
    if active and len(active) >= 2:
        max_r = max(s.reaction_kg for s in active)
        # Wie viele Auflager liegen "fast gleich" hoch?
        near_max = [s for s in active
                    if max_r > 0 and s.reaction_kg >= max_r * 0.99]
        if len(near_max) == 1:
            # Eindeutig höchstes Auflager → markieren
            main_sr = near_max[0]
            for i, sr in enumerate(result.support_results):
                if sr is main_sr:
                    main_idx = i
                    break

    # Label pro Auflager (links / mitte / rechts oder nummeriert)
    if n_supports == 2:
        labels = [tr(lang, "support_left"), tr(lang, "support_right")]
    elif n_supports == 3:
        labels = [tr(lang, "support_left"), tr(lang, "support_middle"),
                  tr(lang, "support_right")]
    else:
        labels = [tr(lang, "support_n", n=i + 1) for i in range(n_supports)]

    cards = []
    for i, sr in enumerate(result.support_results):
        is_main = (i == main_idx)
        sub = f"@ {sr.support.position_m * 100:.0f} cm"
        if is_main:
            sub += f" · {tr(lang, 'main_load')}"
        cards.append(_make_card(
            label=labels[i] if i < len(labels) else tr(lang, "support_n", n=i + 1),
            value=f"{sr.reaction_kg:.1f}",
            unit="kg",
            subtitle=sub,
            highlight=is_main,
        ))

    # Max-Durchbiegungs-Karte
    d = result.deflection
    pct_text = ""
    if d.allowable_deflection_mm and d.allowable_deflection_mm > 0 and d.max_deflection_mm > 0:
        pct = d.max_deflection_mm / d.allowable_deflection_mm * 100
        pct_text = tr(lang, "tolerance_share", pct=pct)
    cards.append(_make_card(
        label=tr(lang, "max_deflection_card"),
        value=f"{d.max_deflection_mm:.1f}",
        unit="mm",
        subtitle=pct_text,
        highlight=False,
    ))

    # Tabelle mit gleichmäßiger Spaltenbreite
    cols = len(cards)
    inner_w = PAGE_W - 2 * MARGIN
    col_w = inner_w / cols - 6
    tbl = Table([cards], colWidths=[col_w] * cols, rowHeights=[3.2 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


class _Card(Flowable):
    """Einzelne Info-Karte (Label, Wert + Einheit, Subtitle).
    Bei ``highlight=True`` mit Teal-Hintergrund und weißer Schrift."""

    def __init__(self, label: str, value: str, unit: str, subtitle: str,
                 highlight: bool = False, height: float = 3.0 * cm) -> None:
        super().__init__()
        self.label = label
        self.value = value
        self.unit = unit
        self.subtitle = subtitle
        self.highlight = highlight
        self.height = height

    def wrap(self, avail_w: float, avail_h: float):
        self.width = avail_w
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        # Hintergrund + Rahmen
        if self.highlight:
            c.setFillColor(TEAL)
            c.setStrokeColor(TEAL)
            c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=0)
        else:
            c.setFillColor(CARD_BG)
            c.setStrokeColor(CARD_BORDER)
            c.setLineWidth(0.6)
            c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=1)

        pad = 0.35 * cm
        # Label oben
        c.setFillColor(colors.white if self.highlight
                        else HexColor("#9AA5B1"))
        label_size = 7.0
        c.setFont("Helvetica-Bold", label_size)
        label_y = h - pad - 7
        label_text = _spaced(self.label)
        max_label_w = w - 2 * pad
        if c.stringWidth(label_text, "Helvetica-Bold", label_size) <= max_label_w:
            c.drawString(pad, label_y, label_text)
        elif self.label.upper().startswith("MAX"):
            parts = self.label.split()
            if len(parts) > 1:
                c.drawString(pad, label_y, _spaced(parts[0]))
                c.drawString(pad, label_y - 10, _spaced(" ".join(parts[1:])))
            else:
                c.drawString(pad, label_y,
                             _truncate(label_text, c, "Helvetica-Bold", label_size,
                                       max_label_w))
        else:
            while label_size > 5.2 and c.stringWidth(
                label_text, "Helvetica-Bold", label_size
            ) > max_label_w:
                label_size -= 0.2
            c.setFont("Helvetica-Bold", label_size)
            c.drawString(pad, label_y,
                         _truncate(label_text, c, "Helvetica-Bold",
                                   label_size, max_label_w))

        # Wert + Einheit
        value_y = h - pad - 7 - 0.9 * cm
        c.setFillColor(colors.white if self.highlight else TEXT_DARK)
        c.setFont("Helvetica-Bold", 20)
        value_w = c.stringWidth(self.value, "Helvetica-Bold", 20)
        c.drawString(pad, value_y, self.value)
        if self.unit:
            c.setFont("Helvetica", 10)
            c.setFillColor(HexColor("#C8E0DA") if self.highlight else TEXT_MUTED)
            c.drawString(pad + value_w + 3, value_y + 2, self.unit)

        # Subtitle unten
        if self.subtitle:
            c.setFillColor(HexColor("#C8E0DA") if self.highlight else TEXT_MUTED)
            c.setFont("Helvetica", 8.0)
            c.drawString(pad, pad, _truncate(self.subtitle, c, "Helvetica",
                                              8.0, w - 2 * pad))


def _make_card(label: str, value: str, unit: str, subtitle: str,
               highlight: bool = False) -> _Card:
    return _Card(label=label, value=value, unit=unit,
                 subtitle=subtitle, highlight=highlight, height=3.2 * cm)


# ── Sektion-Header (nummeriertes Badge + Titel + Subtitle) ──────────────

def _section_header(num: int, title: str, subtitle: str,
                     styles: dict) -> Table:
    badge = _NumberBadge(num)
    title_p = Paragraph(title, styles["section_title"])
    sub_p = Paragraph(subtitle, styles["section_sub"])
    inner_w = PAGE_W - 2 * MARGIN
    tbl = Table(
        [[badge, title_p, sub_p]],
        colWidths=[1.0 * cm, inner_w * 0.45, inner_w * 0.55 - 1.0 * cm],
        rowHeights=[0.9 * cm],
    )
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


class _NumberBadge(Flowable):
    SIZE = 0.7 * cm

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n

    def wrap(self, *args):
        return self.SIZE, self.SIZE

    def draw(self):
        c = self.canv
        r = self.SIZE / 2
        c.setFillColor(NAVY)
        c.setStrokeColor(NAVY)
        c.circle(r, r, r, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        text = str(self.n)
        tw = c.stringWidth(text, "Helvetica-Bold", 9)
        c.drawString(r - tw / 2, r - 3, text)


# ── 2D-Schema ──────────────────────────────────────────────────────────────

def _schema_card(project: Project, result: CalculationResult,
                 truss_type: TrussType) -> Flowable:
    return _SchemaCard(project, result, truss_type)


class _SchemaCard(Flowable):
    PAD = 0.48 * cm

    def __init__(self, project: Project, result: CalculationResult,
                 truss_type: TrussType) -> None:
        super().__init__()
        self.project = project
        self.result = result
        self.truss_type = truss_type
        self._drawing = None

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self._drawing = _schema_drawing(
            self.project, self.result, self.truss_type,
            drawing_width=max(1, avail_w - 2 * self.PAD),
        )
        self.height = self._drawing.height + 2 * self.PAD
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(colors.white)
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, CARD_RADIUS, fill=1, stroke=1)
        if self._drawing is not None:
            renderPDF.draw(self._drawing, c, self.PAD, self.PAD)


def _schema_drawing(project: Project, result: CalculationResult,
                     truss_type: TrussType, drawing_width: float | None = None) -> Drawing:
    """Saubere 2D-Schemazeichnung im Stil der NoiseGate-Vorlage:
    keine Hintergrundfläche, dünne Linien, Bemaßungen oben, Last- und
    Reaktions-Beschriftungen klar lesbar."""
    inner_w = drawing_width or (PAGE_W - 2 * MARGIN)
    d_w = inner_w
    d_h = 6.2 * cm
    total = project.total_length_m
    if total <= 0:
        return Drawing(d_w, 0.5 * cm)

    margin_x = 1.6 * cm
    scale = (d_w - 2 * margin_x) / total
    # Vertikale Anordnung von oben nach unten:
    #   y_dim_total → y_dim_segs → y_load_label → y_truss → y_support → y_defl_label
    y_dim_total = d_h - 0.6 * cm
    y_dim_segs = d_h - 1.1 * cm
    y_load_top = d_h - 2.5 * cm
    y_truss = d_h - 3.8 * cm
    truss_h = 0.45 * cm

    d = Drawing(d_w, d_h)

    # ── Bemaßung Gesamtlänge (grau, oben) ────────────────────────────────
    x_l = margin_x
    x_r = margin_x + total * scale
    d.add(Line(x_l - 4, y_dim_total, x_r + 4, y_dim_total,
               strokeColor=HexColor("#888888"), strokeWidth=0.5))
    # Pfeilspitzen
    for x in (x_l, x_r):
        d.add(Line(x, y_dim_total, x, y_dim_total - 3,
                   strokeColor=HexColor("#888888"), strokeWidth=0.5))
        d.add(Line(x, y_dim_total, x, y_dim_total + 3,
                   strokeColor=HexColor("#888888"), strokeWidth=0.5))
    d.add(String((x_l + x_r) / 2, y_dim_total + 4,
                 f"Gesamt {total * 100:.0f} cm",
                 fontSize=7.5, fillColor=HexColor("#666666"),
                 textAnchor="middle"))

    # ── Bemaßung Auflagerabstände (teal, darunter) ──────────────────────
    sups = sorted([s.position_m for s in project.supports])
    if sups:
        segments = sorted({0.0, total} | set(sups))
        for i in range(len(segments) - 1):
            x1 = margin_x + segments[i] * scale
            x2 = margin_x + segments[i + 1] * scale
            if x2 - x1 < 8:
                continue
            d.add(Line(x1, y_dim_segs, x2, y_dim_segs,
                       strokeColor=TEAL, strokeWidth=0.5))
            for x in (x1, x2):
                d.add(Line(x, y_dim_segs, x, y_dim_segs - 3,
                           strokeColor=TEAL, strokeWidth=0.5))
                d.add(Line(x, y_dim_segs, x, y_dim_segs + 3,
                           strokeColor=TEAL, strokeWidth=0.5))
            d.add(String((x1 + x2) / 2, y_dim_segs + 4,
                         f"{(segments[i+1] - segments[i]) * 100:.0f} cm",
                         fontSize=7, fillColor=TEAL, textAnchor="middle"))

    # ── Traverse als schlanker Fachwerk-Look ────────────────────────────
    truss_color = HexColor("#7C8794")
    # Ober- und Untergurt
    d.add(Line(margin_x, y_truss, x_r, y_truss,
               strokeColor=truss_color, strokeWidth=0.9))
    d.add(Line(margin_x, y_truss + truss_h, x_r, y_truss + truss_h,
               strokeColor=truss_color, strokeWidth=0.9))
    # Endplatten
    d.add(Line(margin_x, y_truss, margin_x, y_truss + truss_h,
               strokeColor=truss_color, strokeWidth=1.0))
    d.add(Line(x_r, y_truss, x_r, y_truss + truss_h,
               strokeColor=truss_color, strokeWidth=1.0))
    # Diagonalstreben (Zickzack)
    n_diag = max(6, int(total * 1.6))
    step = total * scale / n_diag
    for i in range(n_diag):
        x = margin_x + i * step
        if i % 2 == 0:
            d.add(Line(x, y_truss, x + step, y_truss + truss_h,
                       strokeColor=truss_color, strokeWidth=0.5))
        else:
            d.add(Line(x, y_truss + truss_h, x + step, y_truss,
                       strokeColor=truss_color, strokeWidth=0.5))

    # ── Punktlasten (Orange) ─────────────────────────────────────────────
    load_orange = HexColor("#F08000")
    for pl in project.point_loads:
        px = margin_x + pl.position_m * scale
        arrow_bot = y_truss + truss_h + 1
        arrow_top = arrow_bot + 1.2 * cm
        d.add(Line(px, arrow_bot, px, arrow_top,
                   strokeColor=load_orange, strokeWidth=1.4))
        d.add(Polygon([px, arrow_bot,
                        px - 4, arrow_bot + 8,
                        px + 4, arrow_bot + 8],
                        fillColor=load_orange, strokeColor=load_orange))
        d.add(String(px, arrow_top + 4, f"{pl.load_kg:.0f} kg",
                     fontSize=8, fillColor=load_orange,
                     textAnchor="middle", fontName="Helvetica-Bold"))
        d.add(String(px, arrow_top + 14,
                     f"@ {pl.position_m * 100:.0f} cm",
                     fontSize=6.5, fillColor=HexColor("#9AA5B1"),
                     textAnchor="middle"))

    # ── Streckenlasten (Violett, dezent) ────────────────────────────────
    dl_color = HexColor("#A050E0")
    for dl in project.distributed_loads:
        x1 = margin_x + dl.start_m * scale
        x2 = margin_x + dl.end_m * scale
        arrow_bot = y_truss + truss_h + 1
        arrow_top = arrow_bot + 0.6 * cm
        d.add(Line(x1, arrow_top, x2, arrow_top,
                   strokeColor=dl_color, strokeWidth=0.8))
        # Mehrere kleine Pfeile zwischen den Endpunkten
        n_arrows = max(3, int((x2 - x1) / 18))
        for k in range(n_arrows + 1):
            ax = x1 + (x2 - x1) * k / n_arrows
            d.add(Line(ax, arrow_bot, ax, arrow_top,
                       strokeColor=dl_color, strokeWidth=0.5))
        mid = (x1 + x2) / 2
        d.add(String(mid, arrow_top + 6, f"{dl.load_kg_per_m:.1f} kg/m",
                     fontSize=7.5, fillColor=dl_color,
                     textAnchor="middle", fontName="Helvetica-Bold"))

    # ── Biegelinie unter der Traverse (hellblau/teal) ──────────────────
    defl_color = HexColor("#3BB6A6")
    if result.deflection.positions_m and result.deflection.max_deflection_mm > 0:
        max_d = max(abs(v) for v in result.deflection.deflections_mm)
        v_scale = min(0.9 * cm / max_d, 1.0) if max_d > 0 else 0.0
        pts: list[float] = []
        for pos, dv in zip(result.deflection.positions_m,
                            result.deflection.deflections_mm):
            px = margin_x + pos * scale
            py = y_truss - dv * v_scale
            pts.extend([px, py])
        if pts:
            d.add(PolyLine(pts, strokeColor=defl_color, strokeWidth=1.0))

    # ── Auflager (kleine Dreiecke, Reaktion daneben) ────────────────────
    for sr in result.support_results:
        sx = margin_x + sr.support.position_m * scale
        tri_top = y_truss - 1
        col = HexColor("#FFFFFF")
        edge = HexColor("#6C7785")
        if not sr.is_active:
            col = STATUS_LIFT
            edge = STATUS_LIFT
        elif sr.support.has_max_force:
            if sr.utilization > 1.0:
                col = STATUS_OVER
                edge = STATUS_OVER
            elif sr.utilization > 0.8:
                col = STATUS_WARN
                edge = STATUS_WARN
        d.add(Polygon([sx, tri_top, sx - 7, tri_top - 11, sx + 7, tri_top - 11],
                       fillColor=col, strokeColor=edge, strokeWidth=0.7))
        # Bodenlinie + Schraffur unter Dreieck
        d.add(Line(sx - 9, tri_top - 11, sx + 9, tri_top - 11,
                   strokeColor=edge, strokeWidth=0.6))
        for hk in range(-8, 9, 4):
            d.add(Line(sx + hk, tri_top - 11,
                       sx + hk - 3, tri_top - 14,
                       strokeColor=edge, strokeWidth=0.4))
        # Reaktion darunter
        d.add(String(sx, tri_top - 22, f"{sr.reaction_kg:.1f} kg",
                     fontSize=7.5, fillColor=TEXT_DARK,
                     textAnchor="middle", fontName="Helvetica-Bold"))

    # ── Lokale Maxima der Biegelinie beschriften ───────────────────────
    for x, mm, _ in _deflection_peaks(result):
        px = margin_x + x * scale
        py = y_truss - 0.9 * cm - 6
        d.add(String(px, py, f"↓ {mm:.1f} mm", fontSize=8,
                     fillColor=defl_color, textAnchor="middle",
                     fontName="Helvetica-Bold"))
        d.add(String(px, py - 10, f"@ {x*100:.0f} cm", fontSize=6.5,
                     fillColor=TEXT_MUTED, textAnchor="middle"))

    return d


# ── Reaktions-Tabelle ──────────────────────────────────────────────────────

class _StatusPill(Flowable):
    HEIGHT = 0.38 * cm

    def __init__(self, text: str, color: HexColor) -> None:
        super().__init__()
        self.text = text
        self.color = color

    def wrap(self, avail_w, avail_h):
        self.width = min(avail_w, max(1.55 * cm, len(self.text) * 4.0 + 18))
        return self.width, self.HEIGHT

    def draw(self):
        c = self.canv
        w, h = self.width, self.HEIGHT
        pale = colors.Color(
            min(1, self.color.red + 0.78),
            min(1, self.color.green + 0.78),
            min(1, self.color.blue + 0.78),
        )
        c.setFillColor(pale)
        c.roundRect(0, 0, w, h, h / 2, fill=1, stroke=0)
        c.setFillColor(self.color)
        c.circle(0.22 * cm, h / 2, 2.2, fill=1, stroke=0)
        c.setFillColor(TEAL_DARK if self.color == STATUS_OK else TEXT_DARK)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0.38 * cm, h / 2 - 3, self.text)


def _reactions_table(result: CalculationResult, lang: str,
                       styles: dict) -> Table:
    head = [
        tr(lang, "col_position"), tr(lang, "col_reaction_kg"),
        tr(lang, "col_reaction_n"), tr(lang, "col_utilization"),
        tr(lang, "col_status"),
    ]
    rows = [head]
    for sr in result.support_results:
        pos = f"{sr.support.position_m * 100:.0f} cm"
        reaction_kg = f"{sr.reaction_kg:.1f} kg"
        reaction_n = f"{sr.reaction_kg * 9.81:.0f} N"
        if sr.support.has_max_force and sr.support.max_force_kg:
            util_pct = sr.utilization * 100
            util_str = f"{util_pct:.0f} %"
        else:
            util_str = "—"
        # Status
        if not sr.is_active:
            status = ("●", STATUS_LIFT, tr(lang, "status_lifted"))
        elif sr.support.has_max_force and sr.utilization > 1.0:
            status = ("●", STATUS_OVER, tr(lang, "status_overload"))
        elif sr.support.has_max_force and sr.utilization > 0.8:
            status = ("●", STATUS_WARN, tr(lang, "status_warning"))
        else:
            status = ("●", STATUS_OK, tr(lang, "status_ok"))
        rows.append([pos, reaction_kg, reaction_n, util_str,
                     _StatusPill(status[2], status[1])])

    inner_w = PAGE_W - 2 * MARGIN
    col_w = [inner_w * 0.18, inner_w * 0.20, inner_w * 0.20,
             inner_w * 0.20, inner_w * 0.22]
    tbl = Table(rows, colWidths=col_w, rowHeights=[0.7 * cm] + [0.6 * cm] * (len(rows) - 1))
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, CARD_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ])
    # Alternierende Zeilen
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.add("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT)
        style.add("LINEBELOW", (0, i), (-1, i), 0.3,
                   HexColor("#EEF1F3"))
    tbl.setStyle(style)
    return tbl


# ── Durchbiegungs-Sektion ──────────────────────────────────────────────────

def _deflection_peaks(result: CalculationResult) -> list[tuple[float, float, int]]:
    """Findet lokale Maxima (x_m, |defl_mm|, idx) in der Durchbiegungskurve."""
    defl = result.deflection.deflections_mm
    pos = result.deflection.positions_m
    if not defl or not pos:
        return []
    abs_d = [abs(v) for v in defl]
    max_d = max(abs_d) if abs_d else 0.0
    if max_d <= 0:
        return []
    threshold = max_d * 0.25
    peaks: list[tuple[float, float, int]] = []
    n = len(defl)
    i = 1
    while i < n - 1:
        if abs_d[i] >= threshold and abs_d[i] >= abs_d[i - 1] and abs_d[i] >= abs_d[i + 1]:
            j = i
            while j + 1 < n - 1 and abs_d[j + 1] == abs_d[i]:
                j += 1
            mid = (i + j) // 2
            peaks.append((pos[mid], abs_d[mid], mid))
            i = j + 1
        else:
            i += 1
    if not peaks:
        idx = max(range(n), key=lambda k: abs_d[k])
        return [(pos[idx], abs_d[idx], idx)]
    # Clustern (nahe Punkte vereinen)
    cluster_dist = max(1, n // 30)
    merged: list[tuple[float, float, int]] = [peaks[0]]
    for c in peaks[1:]:
        if c[2] - merged[-1][2] < cluster_dist:
            if c[1] > merged[-1][1]:
                merged[-1] = c
        else:
            merged.append(c)
    return merged


def _detect_fields(project: Project,
                     result: CalculationResult) -> list[tuple[float, float, float, float]]:
    """Pro Sub-Feld (zwischen Auflagern) den lokalen Max ermitteln.
    Liefert (sub_a, sub_b, peak_x, peak_defl_mm)."""
    sups = sorted([s.position_m for s in project.supports])
    if len(sups) < 2:
        return []
    fields_out: list[tuple[float, float, float, float]] = []
    pos = result.deflection.positions_m
    defl = result.deflection.deflections_mm
    for i in range(len(sups) - 1):
        a, b = sups[i], sups[i + 1]
        # max in [a, b]
        best_x = (a + b) / 2
        best_d = 0.0
        for p, d in zip(pos, defl):
            if a <= p <= b and abs(d) > abs(best_d):
                best_d = d
                best_x = p
        fields_out.append((a, b, best_x, abs(best_d)))
    return fields_out


def _deflection_summary_card(result: CalculationResult, n_fields: int,
                              lang: str, styles: dict) -> Flowable:
    d = result.deflection
    plural = "n" if (lang == "de" and n_fields != 1) else (
        "s" if (lang == "en" and n_fields != 1) else "")
    detected_text = tr(lang, "detected_n_deflections", n=n_fields, plural=plural)

    util_pct = None
    if d.allowable_deflection_mm and d.allowable_deflection_mm > 0:
        util_pct = d.max_deflection_mm / d.allowable_deflection_mm * 100

    if util_pct is None:
        assessment_text = tr(lang, "assessment_safe")
        assessment_color = STATUS_OK
    elif util_pct > 100:
        assessment_text = tr(lang, "assessment_over")
        assessment_color = STATUS_OVER
    elif util_pct > 80:
        assessment_text = tr(lang, "assessment_warn")
        assessment_color = STATUS_WARN
    else:
        assessment_text = tr(lang, "assessment_safe")
        assessment_color = STATUS_OK

    return _DeflectionSummaryFlowable(
        max_mm=d.max_deflection_mm,
        allowable_mm=d.allowable_deflection_mm,
        util_pct=util_pct,
        detected_text=detected_text,
        assessment_text=assessment_text,
        assessment_color=assessment_color,
        lang=lang,
    )


class _DeflectionSummaryFlowable(Flowable):
    HEIGHT = 4.0 * cm

    def __init__(self, max_mm, allowable_mm, util_pct, detected_text,
                 assessment_text, assessment_color, lang):
        super().__init__()
        self.max_mm = max_mm
        self.allowable_mm = allowable_mm
        self.util_pct = util_pct
        self.detected_text = detected_text
        self.assessment_text = assessment_text
        self.assessment_color = assessment_color
        self.lang = lang

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        return self.width, self.HEIGHT

    def draw(self):
        c = self.canv
        w, h = self.width, self.HEIGHT
        # Hintergrund wie Design2: tiefer Teal-Block mit klarer Zweiteilung.
        c.setFillColor(TEAL)
        c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=0)
        # Linke Spalte: große Zahl
        left_w = w * 0.35
        c.setFillColor(HexColor("#77E6DD"))
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(0.5 * cm, h - 0.75 * cm,
                     _spaced(tr(self.lang, "max_deflection")))
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 38)
        val_str = f"{self.max_mm:.1f}"
        c.drawString(0.5 * cm, h - 2.5 * cm, val_str)
        c.setFont("Helvetica", 12)
        c.setFillColor(HexColor("#C8E0DA"))
        vw = c.stringWidth(val_str, "Helvetica-Bold", 38)
        c.drawString(0.5 * cm + vw + 4, h - 2.5 * cm + 5, "mm")

        c.setStrokeColor(HexColor("#29969A"))
        c.setLineWidth(0.5)
        c.line(left_w, 0.55 * cm, left_w, h - 0.55 * cm)

        # Rechte Spalte: Detail
        right_x = left_w + 0.5 * cm
        right_w = w - right_x - 0.5 * cm
        # Erklärungs-Zeile
        c.setFillColor(HexColor("#C8E0DA"))
        c.setFont("Helvetica", 9.5)
        for line in _wrap_text(c, self.detected_text, "Helvetica", 9.5,
                                right_w):
            c.drawString(right_x, h - 0.7 * cm, line)
            break
        # Tabellen-artige Zeilen
        line_y = h - 1.6 * cm
        row_h = 0.6 * cm

        def draw_row(label, value, value_color=colors.white):
            nonlocal line_y
            c.setFillColor(HexColor("#9DBAC8"))
            c.setFont("Helvetica", 9.5)
            c.drawString(right_x, line_y, label)
            c.setFillColor(value_color)
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(right_x + right_w, line_y, value)
            c.setStrokeColor(HexColor("#1F3A53"))
            c.setLineWidth(0.4)
            c.line(right_x, line_y - 4, right_x + right_w, line_y - 4)
            line_y -= row_h

        if self.allowable_mm:
            draw_row(tr(self.lang, "datasheet_limit"),
                     f"{self.allowable_mm:.2f} mm")
        if self.util_pct is not None:
            draw_row(tr(self.lang, "utilization"), f"{self.util_pct:.1f} %")
        # Bewertung mit farbigem Punkt
        c.setFillColor(HexColor("#9DBAC8"))
        c.setFont("Helvetica", 9.5)
        c.drawString(right_x, line_y, tr(self.lang, "assessment"))
        # Bullet + Text
        bullet_x = right_x + right_w - c.stringWidth(self.assessment_text,
                                                       "Helvetica-Bold", 10) - 14
        c.setFillColor(self.assessment_color)
        c.circle(bullet_x, line_y + 3, 3.5, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(bullet_x + 6, line_y, self.assessment_text)


def _wrap_text(c, text, font, size, max_w):
    """Einfacher Word-Wrap."""
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if c.stringWidth(candidate, font, size) <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _field_cards(fields: list, result: CalculationResult, lang: str,
                  styles: dict) -> Table:
    if not fields:
        return Spacer(1, 0)
    n = len(fields)
    # Labels: 1 Feld → "FELD 1", 2 → links/rechts, 3 → links/mitte/rechts
    if n == 1:
        labels = [tr(lang, "field_label", i=1)]
    elif n == 2:
        labels = [tr(lang, "field_label_left", i=1),
                  tr(lang, "field_label_right", i=2)]
    elif n == 3:
        labels = [tr(lang, "field_label_left", i=1),
                  tr(lang, "field_label_middle", i=2),
                  tr(lang, "field_label_right", i=3)]
    else:
        labels = [tr(lang, "field_label", i=i + 1) for i in range(n)]

    allow = result.deflection.allowable_deflection_mm

    cards: list[Flowable] = []
    for i, (a, b, peak_x, peak_d) in enumerate(fields):
        util_pct = (peak_d / allow * 100) if (allow and allow > 0) else None
        cards.append(_FieldCard(
            badge=f"#{i + 1}",
            label=labels[i] if i < len(labels) else f"FELD {i+1}",
            value=f"{peak_d:.1f}",
            unit="mm",
            position_label=tr(lang, "position_at"),
            position_value=f"{peak_x * 100:.0f} cm",
            util_label=tr(lang, "utilization"),
            util_value=(f"{util_pct:.1f} %" if util_pct is not None else "—"),
            util_color=(_util_color(util_pct) if util_pct is not None else TEXT_MUTED),
        ))

    inner_w = PAGE_W - 2 * MARGIN
    if n == 1:
        rows = [[cards[0]]]
        col_widths = [inner_w]
    else:
        col_w = inner_w / 2 - 6
        rows = []
        for i in range(0, len(cards), 2):
            row = cards[i:i + 2]
            if len(row) == 1:
                row.append(Spacer(1, 0))
            rows.append(row)
        col_widths = [col_w, col_w]
    tbl = Table(rows, colWidths=col_widths,
                rowHeights=[3.2 * cm] * len(rows))
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _util_color(pct: float) -> HexColor:
    if pct > 100:
        return STATUS_OVER
    if pct > 80:
        return STATUS_WARN
    return STATUS_OK


class _FieldCard(Flowable):
    def __init__(self, badge, label, value, unit, position_label,
                 position_value, util_label, util_value, util_color):
        super().__init__()
        self.badge = badge
        self.label = label
        self.value = value
        self.unit = unit
        self.position_label = position_label
        self.position_value = position_value
        self.util_label = util_label
        self.util_value = util_value
        self.util_color = util_color

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self.height = 3.0 * cm
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        # Linker Akzentbalken
        c.setFillColor(TEAL_DARK)
        c.rect(0, 0, 0.12 * cm, h, fill=1, stroke=0)
        # Hauptbereich
        c.setFillColor(CARD_BG)
        c.setStrokeColor(CARD_BORDER)
        c.setLineWidth(0.6)
        c.roundRect(0.12 * cm, 0, w - 0.12 * cm, h, 4, fill=1, stroke=1)

        pad = 0.35 * cm
        # Badge + Label
        badge_text = self.badge
        c.setFillColor(TEAL_DARK)
        bw = c.stringWidth(badge_text, "Helvetica-Bold", 8) + 6
        c.roundRect(pad, h - pad - 12, bw, 12, 3, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(pad + 3, h - pad - 9, badge_text)

        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(pad + bw + 6, h - pad - 9, self.label)

        # Wert
        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(pad, h - pad - 1.0 * cm - 8, self.value)
        vw = c.stringWidth(self.value, "Helvetica-Bold", 20)
        c.setFont("Helvetica", 9)
        c.setFillColor(TEXT_MUTED)
        c.drawString(pad + vw + 3, h - pad - 1.0 * cm - 5, self.unit)

        # Footer: Stelle links, Auslastung rechts
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(pad, pad, f"{self.position_label} ")
        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(pad + c.stringWidth(f"{self.position_label} ",
                                          "Helvetica", 8), pad,
                     self.position_value)
        c.setFillColor(self.util_color)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(w - pad, pad, f"{self.util_label} {self.util_value}")


# ── Stückliste ─────────────────────────────────────────────────────────────

def _partlist_table(project: Project, truss_type: TrussType, lang: str,
                     styles: dict) -> Table:
    head = [tr(lang, "col_truss_type"), tr(lang, "col_length"),
            tr(lang, "col_pieces")]
    rows = [head]
    lengths = Counter(round(s.length_m, 2) for s in project.sections)
    for length, count in sorted(lengths.items()):
        rows.append([truss_type.display_name, f"{length * 100:.0f} cm",
                     str(count)])
    for idx, support in enumerate(
        sorted(project.supports, key=lambda s: s.position_m), start=1
    ):
        force = (
            f"{support.max_force_kg:.0f} kg"
            if support.has_max_force else tr(lang, "partlist_unlimited")
        )
        max_force = tr(lang, "partlist_max_force", force=force)
        rows.append([
            tr(lang, "partlist_support", n=idx),
            f"{support.position_m * 100:.0f} cm, {max_force}",
            "1",
        ])

    inner_w = PAGE_W - 2 * MARGIN
    col_w = [inner_w * 0.55, inner_w * 0.25, inner_w * 0.20]
    tbl = Table(rows, colWidths=col_w,
                 rowHeights=[0.7 * cm] + [0.6 * cm] * (len(rows) - 1))
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, CARD_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return tbl


# ── Hinweis-Box ────────────────────────────────────────────────────────────

def _notice_box(lang: str, styles: dict) -> Flowable:
    return _NoticeBox(
        title=tr(lang, "important_notice"),
        text=tr(lang, "important_notice_text"),
    )


class _NoticeBox(Flowable):
    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title = title
        self.text = text

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self.height = 2.6 * cm
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        # Hintergrund + linke gelbe Leiste
        c.setFillColor(NOTICE_BG)
        c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=0)
        c.setFillColor(NOTICE_BORDER)
        c.rect(0, 0, 0.15 * cm, h, fill=1, stroke=0)

        pad = 0.45 * cm
        # Titel mit Icon ⚠
        c.setFillColor(HexColor("#7A5A00"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(pad, h - 0.55 * cm, f"⚠  {self.title}")
        # Text
        c.setFillColor(HexColor("#6E5000"))
        c.setFont("Helvetica", 8.5)
        max_w = w - 2 * pad
        lines = _wrap_text(c, self.text, "Helvetica", 8.5, max_w)
        y = h - 1.0 * cm
        for line in lines[:6]:
            c.drawString(pad, y, line)
            y -= 11


# ── Signatur-Block ─────────────────────────────────────────────────────────

def _signature_block(lang: str, styles: dict) -> Table:
    inner_w = PAGE_W - 2 * MARGIN
    col_w = inner_w / 2 - 0.3 * cm

    def cell(label_key: str) -> Flowable:
        return _SignatureCell(
            label=tr(lang, label_key),
            hint=tr(lang, "sig_line"),
        )

    tbl = Table([[cell("signed_by"), cell("approved_by")]],
                 colWidths=[col_w, col_w], rowHeights=[2.0 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


class _SignatureCell(Flowable):
    def __init__(self, label: str, hint: str) -> None:
        super().__init__()
        self.label = label
        self.hint = hint

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self.height = 2.0 * cm
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        c.setFillColor(CARD_BG)
        c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=0)
        pad_x = 0.45 * cm
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(pad_x, h - 0.55 * cm, _spaced(self.label))
        # Linie für Unterschrift
        c.setStrokeColor(HexColor("#C5CCD2"))
        c.setLineWidth(0.6)
        line_y = h - 1.3 * cm
        c.line(pad_x, line_y, w - pad_x, line_y)
        # Hint
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawString(pad_x, line_y - 0.35 * cm, self.hint)


# ── Fußzeile & seitennummerierender Canvas ────────────────────────────────

def _make_footer_drawer(metadata, lang: str):
    company = tr(lang, "company_address")
    email = metadata.creator_email or ""

    def drawer(canvas, current_page: int, total_pages: int) -> None:
        canvas.saveState()
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(MARGIN, 1.0 * cm, company)
        # Rechte Spalte: Zeile 1 Seite X von Y, Zeile 2 E-Mail
        page_str = tr(lang, "page_of", p=current_page, total=total_pages)
        canvas.drawRightString(PAGE_W - MARGIN, 1.0 * cm + 11, page_str)
        if email:
            canvas.drawRightString(PAGE_W - MARGIN, 1.0 * cm, email)
        canvas.restoreState()

    return drawer


class _NumberedCanvas(_canvas.Canvas):
    """Zwei-Pass-Canvas: bei save() wird auf jede gespeicherte Seite
    der Footer mit Page X von Y gezeichnet."""

    def __init__(self, *args, footer_drawer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []
        self._footer_drawer = footer_drawer

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved_page_states)
        for i, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            if self._footer_drawer:
                self._footer_drawer(self, i, n)
            super().showPage()
        super().save()


# ── Datenblatt anhängen ────────────────────────────────────────────────────

def _append_datasheet(report_path: str, datasheet_bytes: bytes) -> None:
    """Hängt das Original-Datenblatt-PDF an den generierten Report an."""
    import os
    try:
        import pymupdf
        report_doc = pymupdf.open(report_path)
        ds_doc = pymupdf.open(stream=datasheet_bytes, filetype="pdf")
        report_doc.insert_pdf(ds_doc)
        tmp_path = report_path + ".tmp"
        report_doc.save(tmp_path)
        report_doc.close()
        ds_doc.close()
        os.replace(tmp_path, report_path)
    except Exception as exc:
        print(f"Warnung: Datenblatt konnte nicht angehängt werden: {exc}")
