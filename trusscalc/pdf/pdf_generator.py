"""PDF-Report-Generator im NoiseGate-Branding (Vorlage Design2).

Erzeugt einen Report mit dunkelblauem Header, Kacheln für Auflagerwerte,
nummerierten Sektionen, Hinweisbox und Signaturen. Sprache DE/EN umschaltbar.
"""
from __future__ import annotations

import datetime
import os
import tempfile
from collections import Counter
from dataclasses import replace
from io import BytesIO
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
    Project, TrussType, CalculationResult, TowerAssembly, TowerInput, TowerResult,
)
from trusscalc.core.tower_assembly import cantilever_deflections_mm
from trusscalc.pdf.i18n import tr
from trusscalc.version import APP_VERSION

PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm


def _truss_report_name(truss_type: TrussType | None) -> str:
    if truss_type is None:
        return "Kein Traversentyp"
    return truss_type.name or truss_type.display_name

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

SOFTWARE_VERSION = f"TrussCalc v{APP_VERSION}"
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
    include_partlist: bool = True,
    include_notice_signature: bool = True,
    numbered_footer: bool = True,
) -> None:
    """Erzeugt den PDF-Report. ``metadata`` ist ein ReportMetadata-Dataclass."""
    path = str(path)
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

    if include_partlist:
        # 4) Stückliste
        story.append(_section_header(4, tr(lang, "section_partlist"),
                                      tr(lang, "section_partlist_sub"), styles))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_partlist_table(project, truss_type, lang, styles))
        story.append(Spacer(1, 0.6 * cm))

    if include_notice_signature:
        # Wichtiger Hinweis
        story.append(_notice_box(lang, styles))
        story.append(Spacer(1, 0.5 * cm))

        # Signaturen
        story.append(_signature_block(lang, styles))

    # Footer-Drawer benötigt Daten → Closure
    if numbered_footer:
        footer = _make_footer_drawer(metadata, lang)
        doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(
            *a, footer_drawer=footer, **kw))
    else:
        doc.build(story)

    # Datenblatt anhängen
    if datasheet_pdf_bytes:
        _append_datasheet(path, datasheet_pdf_bytes)


def generate_tower_report(
    path: str,
    project: Project,
    truss_type: TrussType | None,
    tower_input: TowerInput,
    result: TowerResult,
    metadata=None,
    tower_assembly: TowerAssembly | None = None,
    include_notice_signature: bool = True,
    show_tower_height_in_header: bool = True,
    numbered_footer: bool = True,
) -> None:
    """Erzeugt ein Tower-Kapitel für die Projekt-PDF-Ausgabe."""
    if metadata is None:
        from trusscalc.ui.dialogs.report_metadata_dialog import ReportMetadata
        metadata = ReportMetadata(
            language="de",
            project_name=project.name or "Tower",
            sub_project_name="",
            creator_email="info@noisegate.at",
        )
    styles = _styles(metadata.language)
    doc = BaseDocTemplate(
        str(path), pagesize=A4,
        leftMargin=0, rightMargin=0,
        topMargin=0, bottomMargin=0,
        title=metadata.project_name,
        author=metadata.creator_email or "TrussCalc",
    )
    frame_first = Frame(
        MARGIN, 1.2 * cm,
        PAGE_W - 2 * MARGIN, PAGE_H - 1.2 * cm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="tower_first",
    )
    frame_later = Frame(
        MARGIN, 1.5 * cm,
        PAGE_W - 2 * MARGIN, PAGE_H - 3.0 * cm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="tower_later",
    )
    doc.addPageTemplates([
        PageTemplate(id="tower_first", frames=frame_first),
        PageTemplate(id="tower_later", frames=frame_later),
    ])

    status_text = {
        "green": "OK",
        "yellow": "Prüfen",
        "red": "Kritisch",
    }.get(result.status, result.status)
    status_color = {
        "green": STATUS_OK,
        "yellow": STATUS_WARN,
        "red": STATUS_OVER,
    }.get(result.status, TEXT_MUTED)
    truss_name = _truss_report_name(truss_type) if truss_type else "Kein Traversentyp"
    title = metadata.project_name or project.name or "Tower"
    subtitle = metadata.sub_project_name or project.name or "Tower"

    story = [
        _HeaderBand(
            title, subtitle, truss_type, project, metadata.language,
            tower_height_m=tower_input.height_m if show_tower_height_in_header else None,
        ),
        Spacer(1, 0.45 * cm),
        _section_header(1, "Tower-Vorbemessung", "Einzeltower in einer Kraftrichtung", styles),
        Spacer(1, 0.2 * cm),
        _tower_summary_table(tower_input, result, truss_name, status_text, status_color, styles),
        Spacer(1, 0.55 * cm),
        _section_header(2, "2D-Visualisierung", "Kräfte, Bemaßungen und Kopfversatz", styles),
        Spacer(1, 0.2 * cm),
        _tower_schema_card(tower_input, result, tower_assembly, truss_type),
        NextPageTemplate("tower_later"),
        PageBreak(),
        _section_header(3, "Eingaben", "Geometrie, Lasten, Fundament und Anschluss", styles),
        Spacer(1, 0.2 * cm),
        _tower_input_table(tower_input, truss_name, styles, tower_assembly),
        Spacer(1, 0.55 * cm),
        _section_header(4, "Ergebnisse", "Standsicherheit, Ballastbedarf und Anschlusskräfte", styles),
        Spacer(1, 0.2 * cm),
        _tower_result_table(tower_input, result, styles),
        Spacer(1, 0.35 * cm),
        _tower_notice_box(result, styles),
    ]
    if include_notice_signature:
        story.extend([Spacer(1, 0.5 * cm), _signature_block(metadata.language, styles)])

    if numbered_footer:
        footer = _make_footer_drawer(metadata, metadata.language)
        doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(
            *a, footer_drawer=footer, **kw))
    else:
        doc.build(story)


def generate_project_report(path: str, chapters: list[dict], metadata=None) -> None:
    """Erzeugt ein Gesamt-PDF aus mehreren Sub-Projekt-Reports.

    ``generate_report`` bleibt die Einzelreport-Schnittstelle. Diese Funktion
    baut je Sub-Projekt einen normalen Report und führt die Kapitel anschließend
    in der gewünschten Reihenfolge zusammen.
    """
    if not chapters:
        raise ValueError("Keine berechneten Sub-Projekte für den PDF-Report vorhanden.")

    if metadata is None:
        from trusscalc.ui.dialogs.report_metadata_dialog import ReportMetadata
        first_project = chapters[0]["project"]
        metadata = ReportMetadata(
            language="de",
            project_name=first_project.name or "Projekt",
            sub_project_name="",
            creator_email="info@noisegate.at",
        )

    path = str(path)
    target_tmp = path + ".tmp"
    try:
        import pymupdf

        with tempfile.TemporaryDirectory(prefix="trusscalc_pdf_") as tmp_dir:
            chapter_paths = []
            multi = len(chapters) > 1
            for idx, chapter in enumerate(chapters, start=1):
                project = chapter["project"]
                sub_name = (
                    f"{chapter.get('sub_project_name')} / {chapter.get('system_name')}"
                    if chapter.get("sub_project_name") and chapter.get("system_name")
                    else project.name or f"Sub-Projekt {idx}"
                )
                if chapter.get("view_mode") == "compare":
                    sub_name = f"{sub_name}\nVergleich"
                if not multi and metadata.sub_project_name:
                    sub_name = metadata.sub_project_name
                chapter_meta = replace(
                    metadata,
                    sub_project_name=sub_name,
                )
                chapter_path = os.path.join(tmp_dir, f"chapter_{idx:03d}.pdf")
                if chapter.get("kind") == "tower":
                    generate_tower_report(
                        path=chapter_path,
                        project=project,
                        truss_type=chapter.get("truss_type"),
                        tower_input=chapter["tower_input"],
                        result=chapter["result"],
                        metadata=chapter_meta,
                        tower_assembly=chapter.get("tower_assembly"),
                        include_notice_signature=not multi,
                        show_tower_height_in_header=True,
                        numbered_footer=not multi,
                    )
                else:
                    generate_report(
                        path=chapter_path,
                        project=project,
                        truss_type=chapter["truss_type"],
                        result=chapter["result"],
                        datasheet_pdf_bytes=None,
                        metadata=chapter_meta,
                        include_partlist=not multi,
                        include_notice_signature=not multi,
                        numbered_footer=not multi,
                    )
                chapter_paths.append(chapter_path)
            if multi:
                closing_path = os.path.join(tmp_dir, "closing.pdf")
                _build_project_closing_pdf(closing_path, chapters, metadata, numbered_footer=False)
                chapter_paths.append(closing_path)

            merged = pymupdf.open()
            try:
                for chapter_path in chapter_paths:
                    chapter_doc = pymupdf.open(chapter_path)
                    try:
                        merged.insert_pdf(chapter_doc)
                    finally:
                        chapter_doc.close()
                if multi:
                    _draw_global_footer_on_pdf(merged, metadata, metadata.language)
                appended_datasheets = set()
                for chapter in chapters:
                    datasheet_bytes = chapter.get("datasheet_pdf_bytes")
                    if not datasheet_bytes:
                        continue
                    key = (
                        getattr(chapter.get("truss_type"), "id", None),
                        len(datasheet_bytes),
                    )
                    if key in appended_datasheets:
                        continue
                    appended_datasheets.add(key)
                    datasheet_doc = pymupdf.open(stream=datasheet_bytes, filetype="pdf")
                    try:
                        merged.insert_pdf(datasheet_doc)
                    finally:
                        datasheet_doc.close()
                merged.save(target_tmp)
            finally:
                merged.close()
        os.replace(target_tmp, path)
    except Exception:
        if os.path.exists(target_tmp):
            try:
                os.remove(target_tmp)
            except OSError:
                pass
        raise


def _draw_global_footer_on_pdf(pdf_doc, metadata, lang: str) -> None:
    """Zeichnet eine globale Fußzeile auf ein bereits zusammengeführtes PDF."""
    try:
        import pymupdf
    except Exception:
        return
    total_pages = pdf_doc.page_count
    if total_pages <= 0:
        return
    company = tr(lang, "company_address")
    email = metadata.creator_email or ""
    color = (0x6C / 255.0, 0x77 / 255.0, 0x85 / 255.0)
    font = "helv"
    size = 8
    for idx, page in enumerate(pdf_doc, start=1):
        rect = page.rect
        right_x = rect.width - MARGIN
        base_y = rect.height - 1.0 * cm
        page_y = base_y - 11
        page_str = tr(lang, "page_of", p=idx, total=total_pages)
        page_w = pymupdf.get_text_length(page_str, fontname=font, fontsize=size)
        page.insert_text((MARGIN, base_y), company, fontsize=size, fontname=font, color=color)
        page.insert_text(
            (right_x - page_w, page_y),
            page_str,
            fontsize=size,
            fontname=font,
            color=color,
        )
        if email:
            email_w = pymupdf.get_text_length(email, fontname=font, fontsize=size)
            page.insert_text(
                (right_x - email_w, base_y),
                email,
                fontsize=size,
                fontname=font,
                color=color,
            )


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
                 project: Project, lang: str, tower_height_m: float | None = None) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.truss_type = truss_type
        self.project = project
        self.lang = lang
        self.tower_height_m = tower_height_m

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
            for idx, line in enumerate(str(self.subtitle).splitlines()):
                c.drawString(inner_x, title_bottom - (0.75 + 0.45 * idx) * cm, line)

        # Trennlinie
        sep_y = 2.7 * cm
        c.setStrokeColor(HexColor("#1F3A53"))
        c.setLineWidth(0.5)
        c.line(inner_x, sep_y, PAGE_W - MARGIN, sep_y)

        # 3 Spalten Metadaten unten (Software ist in die Fußzeile gewandert,
        # damit TRAVERSENTYP genug Platz für lange Namen hat)
        length_label = tr(self.lang, "total_length")
        length_value = f"{self.project.total_length_m * 100:.0f} cm"
        if self.tower_height_m is not None:
            length_label = "Gesamthöhe" if self.lang == "de" else "Total height"
            length_value = f"{self.tower_height_m * 100:.0f} cm"
        cols = [
            (tr(self.lang, "date"),
             datetime.datetime.now().strftime("%d.%m.%Y, %H:%M"),
             0.24),  # Anteil der Innenbreite
            (tr(self.lang, "software"), SOFTWARE_VERSION, 0.24),
            (tr(self.lang, "truss_type"), _truss_report_name(self.truss_type), 0.34),
            (length_label, length_value, 0.18),
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
        rows.append([_truss_report_name(truss_type), f"{length * 100:.0f} cm",
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

def _combined_partlist_table(chapters: list[dict], lang: str, styles: dict) -> Table:
    include_system = any(chapter.get("system_name") for chapter in chapters)
    head = [
        tr(lang, "col_subproject"),
        tr(lang, "col_length"),
        tr(lang, "col_truss_type"),
        tr(lang, "col_pieces"),
    ]
    if include_system:
        head.insert(1, tr(lang, "col_system"))
    rows = [head]
    for idx, chapter in enumerate(chapters, start=1):
        if chapter.get("kind") == "tower":
            sub_name = chapter.get("sub_project_name") or f"Tower {idx}"
            truss_type = chapter.get("truss_type")
            row = [
                sub_name,
                f"{chapter.get('tower_input').height_m * 100:.0f} cm",
                _truss_report_name(truss_type) if truss_type else "Tower-Traverse",
                "1",
            ]
            if include_system:
                row.insert(1, "")
            rows.append(row)
            continue
        project = chapter["project"]
        truss_type = chapter["truss_type"]
        sub_name = chapter.get("sub_project_name") or project.name or f"Sub-Projekt {idx}"
        system_name = chapter.get("system_name") or ""
        lengths = Counter(round(s.length_m, 2) for s in project.sections)
        for length, count in sorted(lengths.items()):
            row = [
                sub_name,
                f"{length * 100:.0f} cm",
                _truss_report_name(truss_type),
                str(count),
            ]
            if include_system:
                row.insert(1, system_name)
            rows.append(row)
        for support_idx, support in enumerate(
            sorted(project.supports, key=lambda s: s.position_m), start=1
        ):
            force = (
                f"{support.max_force_kg:.0f} kg"
                if support.has_max_force else tr(lang, "partlist_unlimited")
            )
            row = [
                sub_name,
                f"{support.position_m * 100:.0f} cm, "
                f"{tr(lang, 'partlist_max_force', force=force)}",
                tr(lang, "partlist_support", n=support_idx),
                "1",
            ]
            if include_system:
                row.insert(1, system_name)
            rows.append(row)

    inner_w = PAGE_W - 2 * MARGIN
    col_w = (
        [inner_w * 0.20, inner_w * 0.18, inner_w * 0.24, inner_w * 0.26, inner_w * 0.12]
        if include_system else
        [inner_w * 0.30, inner_w * 0.28, inner_w * 0.28, inner_w * 0.14]
    )
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", ((3 if include_system else 2), 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, CARD_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_idx in range(1, len(rows)):
        if row_idx % 2 == 0:
            style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), TABLE_ROW_ALT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _tower_summary_table(data: TowerInput, result: TowerResult, truss_name: str,
                         status_text: str, status_color, styles: dict) -> Table:
    uses_connector = data.foundation.type == "concrete_socket"
    connector_title = "Schraubenauslastung" if uses_connector else "Bodenplatte"
    connector_value = (
        f"{result.bolt_utilization * 100:.0f} %"
        if uses_connector
        else "fix verbunden"
    )
    connector_value_style = (
        styles["card_value"] if uses_connector else ParagraphStyle(
            "tc_tower_connector_small",
            parent=styles["card_value"],
            fontSize=12,
            leading=14,
        )
    )
    connector_detail = (
        f"T {result.bolt_tension_kn:.2f} kN / V {result.bolt_shear_kn:.2f} kN"
        if uses_connector
        else "ohne Schrauben-Näherung"
    )
    rows = [[
        Paragraph("<b>Status</b>", styles["body_muted"]),
        Paragraph("<b>Kippauslastung</b>", styles["body_muted"]),
        Paragraph(f"<b>{connector_title}</b>", styles["body_muted"]),
        Paragraph("<b>Ballastbedarf</b>", styles["body_muted"]),
    ], [
        Paragraph(status_text, ParagraphStyle(
            "tc_tower_status", fontName="Helvetica-Bold", fontSize=18,
            leading=22, textColor=status_color,
        )),
        Paragraph(f"{result.tipping_utilization * 100:.0f} %", styles["card_value"]),
        Paragraph(connector_value, connector_value_style),
        Paragraph(_kg_or_inf(result.required_ballast_kg), styles["card_value"]),
    ], [
        Paragraph(truss_name, styles["body_muted"]),
        Paragraph(f"MEd {result.design_moment_knm:.2f} kNm", styles["body_muted"]),
        Paragraph(connector_detail, styles["body_muted"]),
        Paragraph(f"Fh,max {result.max_horizontal_force_kn:.2f} kN", styles["body_muted"]),
    ]]
    inner_w = PAGE_W - 2 * MARGIN
    tbl = Table(rows, colWidths=[inner_w * 0.23] * 4)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, CARD_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, CARD_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def _tower_input_table(
    data: TowerInput,
    truss_name: str,
    styles: dict,
    assembly: TowerAssembly | None = None,
) -> Table:
    f = data.foundation
    c = data.connector
    uses_connector = f.type == "concrete_socket"
    foundation_type = "Beton-Sockel" if f.type == "concrete_socket" else "Stahl-Bodenplatte"
    rows = [
        ["Traversentyp", truss_name],
        ["Tower-Höhe", f"{data.height_m:.2f} m"],
        [
            "Horizontalkraft [Fh] / Angriffshöhe [hF]",
            f"{data.horizontal_force_kn:.2f} kN @ {data.force_height_m:.2f} m, Richtung {'links' if data.horizontal_force_direction < 0 else 'rechts'}",
        ],
        ["Zuladung / Exzentrizität", f"{data.payload_kg:.1f} kg @ {data.payload_eccentricity_m:.2f} m"],
        ["Sicherheitsfaktor", f"{data.gamma:.2f}"],
        ["Fundament", foundation_type],
        ["Fundament B x T / Gewicht", f"{f.width_m:.2f} x {f.depth_m:.2f} m / {f.weight_kg:.1f} kg"],
        ["Ballast / Abstand", f"{f.ballast_kg:.1f} kg / {f.ballast_offset_m:.2f} m"],
    ]
    if uses_connector:
        rows.extend([
            ["Spiel / Einstecktiefe", f"{f.clearance_mm:.1f} mm / {f.insertion_depth_m:.2f} m"],
            ["Schrauben", f"{c.bolt_count} Stk., Hebelarm {c.bolt_lever_arm_m:.2f} m"],
            ["Zulässig je Schraube", f"Zug {c.allowable_tension_kn:.2f} kN, Quer {c.allowable_shear_kn:.2f} kN"],
        ])
    else:
        rows.append(["Anschluss", "Bodenplatte fix verbunden"])
    if assembly and assembly.cantilevers:
        for idx, cantilever in enumerate(assembly.cantilevers, start=1):
            side = "links" if cantilever.side == "left" else "rechts"
            rows.append([
                f"Auskragung {idx}",
                f"{side}, {cantilever.length_m:.2f} m @ Oberkante {cantilever.height_m:.2f} m",
            ])
    if assembly and assembly.point_loads:
        for idx, load in enumerate(assembly.point_loads, start=1):
            if load.direction == "horizontal":
                side = "rechts" if load.x_m > 0 else "links"
                detail = f"Fh {load.value:.2f} kN @ {load.height_m:.2f} m, Seite {side}"
            else:
                detail = f"{load.value:.1f} kg @ H {load.height_m:.2f} m, X {load.x_m:.2f} m"
            rows.append([f"Punktlast {idx}", detail])
    return _key_value_table(rows, styles)


def _tower_result_table(data: TowerInput, result: TowerResult, styles: dict) -> Table:
    uses_connector = data.foundation.type == "concrete_socket"
    rows = [
        ["Bemessungsmoment", f"{result.design_moment_knm:.2f} kNm"],
        ["Standmoment", f"{result.resisting_moment_knm:.2f} kNm"],
        ["Kippauslastung", f"{result.tipping_utilization * 100:.0f} %"],
        ["Max. Horizontalkraft Fh,max", f"{result.max_horizontal_force_kn:.2f} kN"],
        ["Zusätzlicher Ballastbedarf", _kg_or_inf(result.required_ballast_kg)],
        ["Kantenkraft Fk", f"{result.edge_force_kn * 1000.0:.0f} N"],
        ["Basis-Druckkraft", f"{result.base_compression_kg * 9.80665 / 1000.0:.2f} kN"],
        ["Tower-Eigengewicht", f"{result.tower_self_weight_kg:.1f} kg"],
    ]
    if uses_connector:
        rows.extend([
            ["Schraubenzug je belasteter Schraube", f"{result.bolt_tension_kn:.2f} kN"],
            ["Schraubenquerkraft je Schraube", f"{result.bolt_shear_kn:.2f} kN"],
            ["Schraubenauslastung", f"{result.bolt_utilization * 100:.0f} %"],
            ["Kopfversatz durch Spiel", f"{result.top_offset_mm:.1f} mm"],
        ])
    else:
        rows.append(["Anschluss", "Bodenplatte fix verbunden"])
    rows.extend([
        ["Biegung Tower", f"{result.bending_deflection_mm:.1f} mm"],
        ["Biegung Auskragung", f"{result.cantilever_deflection_mm:.1f} mm"],
        ["Gesamt-Kopfversatz", f"{result.total_top_displacement_mm:.1f} mm"],
    ])
    return _key_value_table(rows, styles)


def _tower_schema_card(
    data: TowerInput,
    result: TowerResult,
    assembly: TowerAssembly | None = None,
    truss_type: TrussType | None = None,
) -> Flowable:
    return _TowerSchemaFlowable(data, result, assembly, truss_type)


class _TowerSchemaFlowable(Flowable):
    def __init__(
        self,
        data: TowerInput,
        result: TowerResult,
        assembly: TowerAssembly | None = None,
        truss_type: TrussType | None = None,
    ) -> None:
        super().__init__()
        self.data = data
        self.result = result
        self.assembly = assembly
        self.truss_type = truss_type

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        self.height = 10.0 * cm
        return self.width, self.height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        c.setFillColor(CARD_BG)
        c.roundRect(0, 0, w, h, CARD_RADIUS, fill=1, stroke=0)
        c.setStrokeColor(CARD_BORDER)
        c.roundRect(0, 0, w, h, CARD_RADIUS, fill=0, stroke=1)
        if self._draw_ui_canvas_image(c, w, h):
            return

        data = self.data
        result = self.result
        status_color = {
            "green": STATUS_OK,
            "yellow": STATUS_WARN,
            "red": STATUS_OVER,
        }.get(result.status, TEXT_MUTED)

        pad = 0.55 * cm
        label_rects: list[tuple[float, float, float, float]] = []
        cx = w * 0.43
        base_y = 1.15 * cm
        top_y = h - 1.25 * cm
        tower_h = max(top_y - base_y, 1)
        foundation_w = max(2.4 * cm, min(5.2 * cm, data.foundation.width_m / 2.0 * 5.2 * cm))

        c.setFillColor(HexColor("#585858"))
        c.rect(cx - foundation_w / 2, 0.55 * cm, foundation_w, 0.62 * cm, fill=1, stroke=0)
        label_rects.append((cx - foundation_w / 2 - 3, 0.55 * cm - 3, foundation_w + 6, 0.62 * cm + 6))
        chord = 0.18 * cm
        label_rects.append((cx - chord - 5, base_y - 5, chord * 2 + 10, tower_h + 10))
        label_rects.append((0.55 * cm - 2, h - 1.08 * cm - 2, 4.2 * cm, 0.62 * cm))
        c.setStrokeColor(TEXT_DARK)
        c.setLineWidth(2.2)
        c.line(cx - chord, base_y, cx - chord, top_y)
        c.line(cx + chord, base_y, cx + chord, top_y)
        c.setStrokeColor(TEXT_MUTED)
        c.setLineWidth(0.7)
        y = base_y + 0.4 * cm
        flip = False
        while y < top_y - 0.2 * cm:
            if flip:
                c.line(cx + chord, y, cx - chord, y + 0.32 * cm)
            else:
                c.line(cx - chord, y, cx + chord, y + 0.32 * cm)
            c.line(cx - chord, y, cx + chord, y)
            y += 0.55 * cm
            flip = not flip

        max_left = max((arm.length_m for arm in self.assembly.cantilevers if arm.side == "left"), default=0.0) if self.assembly else 0.0
        max_right = max((arm.length_m for arm in self.assembly.cantilevers if arm.side != "left"), default=0.0) if self.assembly else 0.0
        right_force_lane_x = w - 3.05 * cm
        right_dimension_x = w - 1.45 * cm
        hforce_dimension_x = w - 2.45 * cm
        drawing_right = right_force_lane_x - 0.75 * cm
        left_capacity = max(cx - 1.15 * cm, 0.8 * cm)
        right_capacity = max(drawing_right - cx, 0.8 * cm)
        x_scale = 0.9 * cm
        if max_left > 0:
            x_scale = min(x_scale, left_capacity / max_left)
        if max_right > 0:
            x_scale = min(x_scale, right_capacity / max_right)
        if self.assembly:
            cantilever_draw_specs = []
            for cantilever in self.assembly.cantilevers:
                arm_top_y = self._y_for_height(cantilever.height_m, data.height_m, top_y, base_y)
                arm_y = arm_top_y - 0.16 * cm
                arm_len = max(0.35 * cm, cantilever.length_m * x_scale)
                if cantilever.side == "left":
                    x1, x2 = cx - chord, cx - chord - arm_len
                else:
                    x1, x2 = cx + chord, cx + chord + arm_len
                self._draw_horizontal_truss(c, x1, x2, arm_y)
                label_rects.append((min(x1, x2) - 3, arm_y - 0.19 * cm, abs(x2 - x1) + 6, 0.38 * cm))
                cantilever_draw_specs.append((cantilever, x1, x2, arm_y))
            self._draw_cantilever_deflections(c, cantilever_draw_specs, x_scale, status_color, label_rects)

        payload_x = cx + max(-2.4 * cm, min(2.4 * cm, data.payload_eccentricity_m * x_scale))

        force_y = self._y_for_height(data.force_height_m, data.height_m, top_y, base_y)
        force_color = TEAL if result.status == "green" else status_color
        horizontal_loads = [
            load for load in (self.assembly.point_loads if self.assembly else [])
            if load.direction == "horizontal" and load.value > 0
        ]
        if horizontal_loads:
            for load in horizontal_loads:
                load_y = self._y_for_height(load.height_m, data.height_m, top_y, base_y)
                if load.x_m > 0:
                    self._arrow(c, cx + 2.0 * cm, load_y, cx + 0.62 * cm, load_y, force_color)
                    self._placed_label(
                        c, f"Fh {load.value:.2f} kN", right_force_lane_x, load_y + 0.18 * cm,
                        force_color, label_rects, min_y=base_y + 1.0 * cm, max_y=top_y - 0.15 * cm,
                        leader_to=(cx + 1.1 * cm, load_y),
                    )
                else:
                    self._arrow(c, cx - 2.0 * cm, load_y, cx - 0.62 * cm, load_y, force_color)
                    self._placed_label(
                        c, f"Fh {load.value:.2f} kN", pad, load_y + 0.18 * cm,
                        force_color, label_rects, min_y=base_y + 1.0 * cm, max_y=top_y - 0.15 * cm,
                        leader_to=(cx - 1.1 * cm, load_y),
                    )
        elif data.horizontal_force_kn > 0:
            if data.horizontal_force_direction < 0:
                self._arrow(c, cx + 2.0 * cm, force_y, cx + 0.62 * cm, force_y, force_color)
                self._placed_label(c, f"Fh {data.horizontal_force_kn:.2f} kN",
                                   right_force_lane_x, force_y + 0.18 * cm, force_color, label_rects)
            else:
                self._arrow(c, cx - 2.0 * cm, force_y, cx - 0.62 * cm, force_y, force_color)
                self._placed_label(c, f"Fh {data.horizontal_force_kn:.2f} kN",
                                   pad, force_y + 0.18 * cm, force_color, label_rects)
        vertical_loads = [
            load for load in (self.assembly.point_loads if self.assembly else [])
            if load.direction == "vertical" and load.value > 0
        ]
        if vertical_loads:
            for load in vertical_loads:
                load_y = self._y_for_height(load.height_m, data.height_m, top_y, base_y)
                load_x = cx + max(-2.8 * cm, min(2.8 * cm, load.x_m * x_scale))
                self._arrow(c, load_x, load_y + 0.78 * cm, load_x, load_y + 0.22 * cm,
                            HexColor("#B8872B"))
                load_label = f"{load.value:.0f} kg"
                if abs(load.x_m) > 0.01:
                    load_label += f" / e {load.x_m:.2f} m"
                label_x = pad if load.x_m <= 0 else min(right_force_lane_x, load_x + 0.18 * cm)
                self._placed_label(
                    c, load_label, label_x, load_y + 0.88 * cm, HexColor("#B8872B"),
                    label_rects, min_y=base_y + 1.0 * cm, max_y=top_y + 0.75 * cm,
                    leader_to=(load_x, load_y + 0.78 * cm),
                )
        elif data.payload_kg > 0:
            self._arrow(c, payload_x, top_y + 0.95 * cm, payload_x, top_y + 0.38 * cm,
                        HexColor("#B8872B"))
            self._placed_label(c, f"{data.payload_kg:.0f} kg", payload_x + 0.08 * cm,
                               top_y + 0.95 * cm, HexColor("#B8872B"), label_rects)
        direction = -1 if getattr(result, "moment_direction", 1) < 0 else 1
        edge_x = cx - foundation_w / 2 - 0.62 * cm if direction > 0 else cx + foundation_w / 2 + 1.18 * cm
        fk_dx = -1.08 * cm if direction > 0 else 0.08 * cm
        self._arrow(c, edge_x, base_y + 0.18 * cm,
                    edge_x, base_y + 0.78 * cm, status_color)
        self._placed_label(
            c, f"Fk {result.edge_force_kn * 1000.0:.0f} N",
            edge_x + fk_dx, base_y + 0.88 * cm, status_color, label_rects,
            min_y=base_y + 0.35 * cm, max_y=base_y + 1.8 * cm,
        )
        rz_x = cx + foundation_w / 2 + 0.56 * cm
        self._arrow(c, rz_x, base_y + 1.32 * cm,
                    rz_x, base_y + 0.78 * cm, status_color)
        self._placed_label(
            c, f"Rz {result.base_compression_kg * 9.80665 / 1000.0:.2f} kN",
            right_force_lane_x, base_y + 1.42 * cm, status_color, label_rects,
            min_y=base_y + 0.6 * cm, max_y=base_y + 2.15 * cm,
        )

        if data.foundation.type == "concrete_socket":
            c.setStrokeColor(status_color)
            c.setLineWidth(1.5)
            c.line(cx - 0.45 * cm, base_y + 0.05 * cm, cx - 0.82 * cm, base_y + 0.62 * cm)
            c.line(cx + 0.45 * cm, base_y + 0.05 * cm, cx + 0.82 * cm, base_y + 0.62 * cm)
            c.setFillColor(status_color)
            c.setFont("Helvetica", 8)
            c.drawString(cx + 0.95 * cm, base_y + 0.48 * cm, f"T {result.bolt_tension_kn:.2f} kN")

        self._dimension(c, right_dimension_x, top_y, right_dimension_x, base_y, "", vertical=True)
        self._placed_label(c, f"H {data.height_m:.2f} m", right_dimension_x + 0.12 * cm,
                           (top_y + base_y) / 2, TEXT_MUTED, label_rects)
        self._dimension(c, cx - foundation_w / 2, 0.22 * cm,
                        cx + foundation_w / 2, 0.22 * cm,
                        f"B {data.foundation.width_m:.2f} m", vertical=False)
        if data.horizontal_force_kn > 0:
            self._dimension(c, hforce_dimension_x, force_y, hforce_dimension_x, base_y, "", vertical=True)
            self._placed_label(c, f"hF {data.force_height_m:.2f} m", hforce_dimension_x + 0.12 * cm,
                               (force_y + base_y) / 2, TEXT_MUTED, label_rects)

        c.setFillColor(TEXT_DARK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.55 * cm, h - 0.65 * cm, f"MEd {result.design_moment_knm:.2f} kNm")
        c.drawString(0.55 * cm, h - 1.05 * cm, f"Kopfversatz {result.total_top_displacement_mm:.1f} mm")

        bend = direction * min(1.0 * cm, max(0.15 * cm, result.total_top_displacement_mm / 50.0 * cm))
        if result.total_top_displacement_mm > 0:
            c.setStrokeColor(status_color)
            c.setLineWidth(1.4)
            c.setDash(4, 3)
            path = c.beginPath()
            path.moveTo(cx, base_y)
            path.curveTo(cx + bend * 0.2, base_y + tower_h * 0.35,
                         cx + bend * 0.8, top_y - tower_h * 0.35,
                         cx + bend, top_y)
            c.drawPath(path, stroke=1, fill=0)
            c.setDash()

    def _draw_ui_canvas_image(self, c, w: float, h: float) -> bool:
        if self.assembly is None:
            return False
        try:
            from trusscalc.ui.panels.tower_panel import render_tower_schema_png_bytes
            pixel_w = 820
            pixel_h = max(480, int(pixel_w * h / max(w, 1)))
            png_bytes = render_tower_schema_png_bytes(
                self.assembly,
                self.result,
                self.truss_type,
                width_px=pixel_w,
                height_px=pixel_h,
                render_scale=2,
            )
        except Exception:
            return False
        inset = 0.14 * cm
        c.drawImage(
            ImageReader(BytesIO(png_bytes)),
            inset,
            inset,
            width=w - 2 * inset,
            height=h - 2 * inset,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        return True

    def _y_for_height(self, value: float, height_m: float, top_y: float, base_y: float) -> float:
        if height_m <= 0:
            return base_y
        ratio = max(0.0, min(1.0, value / height_m))
        return base_y + ratio * (top_y - base_y)

    def _arrow(self, c, x1, y1, x2, y2, color, label=None, label_dx=0, label_dy=0.1 * cm):
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(1.4)
        c.line(x1, y1, x2, y2)
        dx = x2 - x1
        dy = y2 - y1
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        size = 0.12 * cm
        p1 = (x2, y2)
        p2 = (x2 - ux * size - uy * size * 0.55, y2 - uy * size + ux * size * 0.55)
        p3 = (x2 - ux * size + uy * size * 0.55, y2 - uy * size - ux * size * 0.55)
        head = c.beginPath()
        head.moveTo(p1[0], p1[1])
        head.lineTo(p2[0], p2[1])
        head.lineTo(p3[0], p3[1])
        head.close()
        c.drawPath(head, stroke=0, fill=1)
        if label:
            c.setFont("Helvetica", 8)
            c.drawString(min(x1, x2) + label_dx, max(y1, y2) + label_dy, label)

    def _placed_label(
        self,
        c,
        text: str,
        x: float,
        y: float,
        color,
        occupied: list[tuple[float, float, float, float]],
        min_y: float | None = None,
        max_y: float | None = None,
        leader_to: tuple[float, float] | None = None,
        font_size: float = 7.5,
    ) -> tuple[float, float, float, float]:
        c.setFont("Helvetica", font_size)
        width = c.stringWidth(text, "Helvetica", font_size)
        height = font_size + 2
        max_x = max(0.55 * cm, self.width - width - 0.55 * cm)
        x = min(max(x, 0.55 * cm), max_x)
        min_y = 0.4 * cm if min_y is None else min_y
        max_y = self.height - 0.35 * cm if max_y is None else max_y
        y = min(max(y, min_y), max_y)

        step = height + 2
        candidates = [y]
        for idx in range(1, 18):
            candidates.extend([y - step * idx, y + step * idx])
        best_y = y
        for candidate in candidates:
            if candidate < min_y or candidate > max_y:
                continue
            rect = (x - 2, candidate - 2, width + 4, height + 4)
            if not any(_rects_intersect(rect, other) for other in occupied):
                best_y = candidate
                break

        rect = (x - 2, best_y - 2, width + 4, height + 4)
        occupied.append(rect)
        if leader_to:
            c.setStrokeColor(color)
            c.setLineWidth(0.35)
            c.line(leader_to[0], leader_to[1], x, best_y + 2)
        c.setFillColor(color)
        c.setFont("Helvetica", font_size)
        c.drawString(x, best_y, text)
        return rect

    def _draw_horizontal_truss(self, c, x1, x2, y):
        left, right = min(x1, x2), max(x1, x2)
        half = 0.16 * cm
        c.setStrokeColor(TEXT_DARK)
        c.setLineWidth(2.0)
        c.line(left, y - half, right, y - half)
        c.line(left, y + half, right, y + half)
        c.setStrokeColor(TEXT_MUTED)
        c.setLineWidth(0.55)
        step = 0.48 * cm
        x = left
        flip = False
        while x + step <= right:
            if flip:
                c.line(x, y + half, x + step, y - half)
            else:
                c.line(x, y - half, x + step, y + half)
            c.line(x, y - half, x, y + half)
            x += step
            flip = not flip
        c.line(right, y - half, right, y + half)

    def _draw_cantilever_deflections(self, c, specs, x_scale, color, occupied):
        if not self.assembly or not specs:
            return
        deflections = cantilever_deflections_mm(self.assembly, self.truss_type, self.data.gamma)
        if not deflections:
            return
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(1.1)
        c.setDash(4, 3)
        for cantilever, x1, x2, y in specs:
            value_mm = deflections.get(cantilever.id or "", 0.0)
            if value_mm <= 0.05:
                continue
            sag = min(0.75 * cm, max(0.09 * cm, value_mm / 20.0 * cm))
            mid_x = (x1 + x2) / 2.0
            path = c.beginPath()
            path.moveTo(x1, y)
            path.curveTo(mid_x, y - sag * 0.15, mid_x, y - sag * 0.75, x2, y - sag)
            c.drawPath(path, stroke=1, fill=0)
            c.setDash()
            c.setFont("Helvetica", 7.5)
            label_x = min(x1, x2) + 0.12 * cm if cantilever.side == "left" else max(x1, x2) - 0.92 * cm
            label_y = y - sag - 0.34 * cm
            self._placed_label(
                c, f"u {value_mm:.1f} mm", label_x, label_y, color, occupied,
                min_y=0.75 * cm, max_y=self.height - 0.45 * cm,
                leader_to=(x2, y - sag),
            )
            c.setDash(4, 3)
        c.setDash()

    def _dimension(self, c, x1, y1, x2, y2, label, vertical: bool):
        c.setStrokeColor(TEXT_LIGHT)
        c.setLineWidth(0.5)
        c.setDash(1, 2)
        c.line(x1, y1, x2, y2)
        c.setDash()
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 7.5)
        if vertical:
            c.drawString(x1 + 0.12 * cm, (y1 + y2) / 2, label)
        else:
            c.drawCentredString((x1 + x2) / 2, y1 + 0.08 * cm, label)


def _rects_intersect(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _key_value_table(rows: list[list[str]], styles: dict) -> Table:
    table_rows = [
        [Paragraph(str(k), styles["body_muted"]), Paragraph(str(v), styles["body"])]
        for k, v in rows
    ]
    inner_w = PAGE_W - 2 * MARGIN
    tbl = Table(table_rows, colWidths=[inner_w * 0.42, inner_w * 0.58])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, CARD_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _tower_notice_box(result: TowerResult, styles: dict) -> Flowable:
    warnings = " ".join(result.warnings)
    return _NoticeBox(
        title="Wichtiger Tower-Hinweis",
        text=(
            "Diese Tower-Berechnung ist eine Vorbemessung und kein "
            "prüffähiger Standsicherheitsnachweis. Herstellerangaben, "
            "Verbindungsmittel, Untergrund, dynamische Lasten und lokale "
            f"Vorschriften sind separat zu prüfen. {warnings}"
        ),
    )


def _kg_or_inf(value: float) -> str:
    if value == float("inf"):
        return "nicht bestimmbar"
    return f"{value:.1f} kg"


def _build_project_closing_pdf(
    path: str,
    chapters: list[dict],
    metadata,
    numbered_footer: bool = True,
) -> None:
    lang = metadata.language
    styles = _styles(lang)
    doc = BaseDocTemplate(
        path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=metadata.project_name,
        author=metadata.creator_email or "TrussCalc",
    )
    frame = Frame(
        MARGIN, 1.5 * cm,
        PAGE_W - 2 * MARGIN, PAGE_H - 3.0 * cm,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="closing",
    )
    doc.addPageTemplates([PageTemplate(id="closing", frames=frame)])

    story = [
        _section_header(
            4,
            tr(lang, "section_combined_partlist"),
            tr(lang, "section_combined_partlist_sub"),
            styles,
        ),
        Spacer(1, 0.25 * cm),
        _combined_partlist_table(chapters, lang, styles),
        Spacer(1, 0.6 * cm),
        _notice_box(lang, styles),
        Spacer(1, 0.5 * cm),
        _signature_block(lang, styles),
    ]
    if numbered_footer:
        footer = _make_footer_drawer(metadata, lang)
        doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(
            *a, footer_drawer=footer, **kw))
    else:
        doc.build(story)


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
