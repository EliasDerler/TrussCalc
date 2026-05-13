"""KI-basierter PDF-Tabellen-Parser via PaddleOCR PP-Structure.

Optionales Modul: PaddleOCR muss installiert sein. Wenn nicht verfügbar, ist
PaddleOCRPdfParser.is_available() False und der Parser kann nicht genutzt werden.

Initialisierung dauert ~ 50 s (Modelle laden), Inferenz ~ 20-90 s pro Seite.
Wegen der Latenz nur auf User-Anforderung („PDF Import (KI)"-Button) aufrufen.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from trusscalc.core.models import LoadType, LoadTableEntry


@dataclass
class OcrParseResult:
    """Strukturiertes Ergebnis eines KI-PDF-Parsings."""
    entries: list[LoadTableEntry] = field(default_factory=list)
    metadata: dict[str, Optional[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    raw_markdown: str = ""


def is_available() -> bool:
    """True, wenn PaddleOCR installiert und nutzbar ist."""
    import importlib.util
    return (
        importlib.util.find_spec("paddleocr") is not None
        and importlib.util.find_spec("bs4") is not None
    )


class PaddleOCRPdfParser:
    """Lazy-init Wrapper um PP-Structure V3."""

    def __init__(self) -> None:
        self._pipeline = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is None:
            from paddleocr import PPStructureV3
            self._pipeline = PPStructureV3(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

    def parse(self, pdf_path: str,
              progress_cb: Optional[callable] = None) -> OcrParseResult:
        """Analysiert ein PDF-Datenblatt und liefert erkannte Lasttabellen-
        Einträge sowie etwaige Metadaten."""
        if progress_cb:
            progress_cb("Lade KI-Modelle…")
        self._ensure_pipeline()

        result = OcrParseResult()

        import pymupdf
        doc = pymupdf.open(pdf_path)
        n_pages = len(doc)

        all_md: list[str] = []
        all_text: list[str] = []
        all_html_tables: list[str] = []

        for page_num in range(n_pages):
            if progress_cb:
                progress_cb(f"Analysiere Seite {page_num + 1} / {n_pages}…")

            page = doc[page_num]
            try:
                page_text = page.get_text() or ""
                if page_text:
                    all_text.append(page_text)
            except Exception:
                pass
            pix = page.get_pixmap(dpi=200)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                img_path = f.name
                f.write(pix.tobytes("png"))

            try:
                results = self._pipeline.predict(input=img_path)
                items = results if hasattr(results, "__iter__") else [results]
                for res in items:
                    html = getattr(res, "html", None)
                    if isinstance(html, dict):
                        for k, v in html.items():
                            if v and "<table" in str(v):
                                all_html_tables.append(str(v))
                    md = getattr(res, "markdown", None)
                    if isinstance(md, dict):
                        text = md.get("markdown_texts", "")
                        if text:
                            all_md.append(str(text))
            except Exception as exc:
                result.warnings.append(f"Seite {page_num + 1}: {exc}")
            finally:
                try:
                    os.unlink(img_path)
                except OSError:
                    pass

        doc.close()
        result.raw_markdown = "\n\n".join(all_md + all_text)

        # Tabellen parsen
        seen: set[tuple[float, str]] = set()
        for html in all_html_tables:
            for entry in _parse_html_table(html):
                key = (entry.span_m, entry.load_type.value)
                if key in seen:
                    continue
                seen.add(key)
                result.entries.append(entry)

        # Fallback: wenn keine Tabelle erkannt, Markdown-Text-Heuristik probieren
        # (für Datenblätter wie GlobalTruss F34, deren Layout PP-Structure
        # nicht als HTML-Tabelle einliest)
        if not result.entries:
            text_entries = _parse_markdown_text_table(result.raw_markdown)
            if not text_entries:
                text_entries = _parse_plain_text_capacity_table(result.raw_markdown)
            for entry in text_entries:
                key = (entry.span_m, entry.load_type.value)
                if key in seen:
                    continue
                seen.add(key)
                result.entries.append(entry)
            if text_entries:
                result.warnings.append(
                    f"Tabelle nicht als HTML erkannt – {len(text_entries)} "
                    "Einträge per Text-Heuristik extrahiert. Bitte prüfen!"
                )

        # Metadaten aus Markdown ableiten (mit Dateinamen als Fallback)
        result.metadata = _extract_metadata(result.raw_markdown, pdf_path)

        if not result.entries:
            result.warnings.append(
                "Keine Lasttabellen-Einträge automatisch erkannt. "
                "Bitte Daten manuell prüfen oder ergänzen."
            )

        if progress_cb:
            progress_cb(f"Fertig: {len(result.entries)} Einträge erkannt.")
        return result


# ── HTML-Tabellen-Parsing ─────────────────────────────────────────────────────

_LOAD_TYPE_KEYWORDS: list[tuple[re.Pattern, LoadType]] = [
    (re.compile(r"\bUDL\b", re.IGNORECASE), LoadType.UDL),
    (re.compile(r"uniform.*distrib", re.IGNORECASE), LoadType.UDL),
    (re.compile(r"\bCPL\b", re.IGNORECASE), LoadType.CPL),
    (re.compile(r"center.*point", re.IGNORECASE), LoadType.CPL),
    (re.compile(r"\b1\s*/\s*3\b"), LoadType.THIRD),
    (re.compile(r"\b1\s*/\s*4\b"), LoadType.QUARTER),
    (re.compile(r"\b1\s*/\s*5\b"), LoadType.FIFTH),
]


def _classify_load_type(text: str) -> Optional[LoadType]:
    for pattern, lt in _LOAD_TYPE_KEYWORDS:
        if pattern.search(text):
            return lt
    return None


def _to_float(text: str) -> Optional[float]:
    """Parsing für deutsche Komma-Dezimalzahlen oder englische Punkte."""
    s = text.strip().replace(" ", "").replace("\xa0", "")
    if not s:
        return None
    # Beispiel-Eingaben: "1,36" "501,00" "1.36" "501.00" "501,00*" "12,5 cm"
    s = re.sub(r"[a-zA-Z\*\(\)/]", "", s)
    s = s.strip()
    # Wenn mehrere Kommas: nicht parsbar
    if s.count(",") > 1 or s.count(".") > 1:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_html_table(html: str) -> list[LoadTableEntry]:
    """Versucht eine HTML-Tabelle aus einem Datenblatt in
    LoadTableEntry-Objekte zu zerlegen."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    # Imperiale Tabellen überspringen (Maße in ft/lbs/inches)
    full_text = " ".join(
        c.get_text(" ", strip=True).lower()
        for r in rows for c in r.find_all(["td", "th"])
    )
    if re.search(r"\blbs?\b|\blbs/ft\b|\binches?\b|\bin\s*\*?\s*\*", full_text) \
            or re.search(r"\bfeet\b", full_text) \
            or re.search(r"\bft\s*\)", full_text):
        return []

    # 1) Spalten-Map: idx -> LoadType (aus mehreren Header-Zeilen + colspan)
    col_type: dict[int, LoadType] = {}
    for row in rows:
        col = 0
        for cell in row.find_all(["td", "th"]):
            text = cell.get_text(separator=" ", strip=True)
            cs = int(cell.get("colspan", 1) or 1)
            lt = _classify_load_type(text)
            if lt is not None:
                for k in range(cs):
                    col_type.setdefault(col + k, lt)
            col += cs
    if not col_type:
        return []

    # 2) Einheit der Durchbiegungs-Spalten (mm vs cm) erkennen
    col_unit_factor: dict[int, float] = {}  # idx -> Faktor zu mm
    for row in rows:
        col = 0
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        text_all = " ".join(c.get_text(" ", strip=True).lower() for c in cells)
        # Suche Zeile mit "mm" oder "cm" als Einheits-Header
        if re.search(r"\b(mm|cm)\b", text_all) and not re.search(
            r"\d{2,}", text_all
        ):
            for cell in cells:
                t = cell.get_text(" ", strip=True).lower()
                cs = int(cell.get("colspan", 1) or 1)
                for k in range(cs):
                    if "mm" in t:
                        col_unit_factor[col + k] = 1.0
                    elif "cm" in t:
                        col_unit_factor[col + k] = 10.0
                col += cs
            break

    # 3) Lasttypen-Spalten paarweise (Last, Durchbiegung) zuordnen.
    #    Konvention: erste Spalte des Lasttyps = Last, zweite = Durchbiegung.
    type_cols: dict[LoadType, list[int]] = {}
    for idx, lt in sorted(col_type.items()):
        type_cols.setdefault(lt, []).append(idx)

    # 4) Datenzeilen extrahieren
    entries: list[LoadTableEntry] = []
    for row in rows:
        cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
        if not cells:
            continue
        first = _to_float(cells[0])
        if first is None or first < 1.0 or first > 80.0:
            continue
        # Aussortieren: imperialer Bereich (Span > 19 ft → Span * 0.3048 m)
        # Wenn Wert > 19 m, aber < 80 m, wahrscheinlich noch metrisch (z.B. 24 m).
        # Wenn Spaltenbeschriftung "ft" enthält, dies als imperial überspringen.
        # Vereinfachung: > 30 m verdächtig → überspringen.
        if first > 30.0:
            continue
        span_m = first
        for lt, cols in type_cols.items():
            if len(cols) < 2:
                continue
            load_idx, defl_idx = cols[0], cols[1]
            if max(load_idx, defl_idx) >= len(cells):
                continue
            load = _to_float(cells[load_idx])
            defl = _to_float(cells[defl_idx])
            if load is None or defl is None or load <= 0 or defl <= 0:
                continue
            factor = col_unit_factor.get(defl_idx, 1.0)
            entries.append(LoadTableEntry(
                span_m=span_m,
                load_type=lt,
                max_load_kg=load,
                deflection_mm=defl * factor,
            ))
    return entries


# ── Metadaten aus Markdown extrahieren ────────────────────────────────────────

def _parse_markdown_text_table(md: str) -> list[LoadTableEntry]:
    """Heuristischer Parser für Datenblätter, deren Lasttabelle PP-Structure
    nicht als HTML erkennt. Erwartetes Muster (z. B. GlobalTruss F34):

        m  4,00 5,00 6,00 ...           ← Stützweiten
        kg/m  501,00 344,00 ...         ← UDL
        cm  1,36 2,30 ...               ← UDL Durchbiegung
        kg  922,00 763,00 ...           ← CPL
        cm  1,01 1,64 ...               ← CPL Durchbiegung
        kg  627,00 528,00 ...           ← 1/3 PL
        cm  1,16 1,93 ...               ← 1/3 PL Durchbiegung
        kg  496,00 411,00 ...           ← 1/4 PL
        cm  1,28 2,09 ...               ← 1/4 PL Durchbiegung
        kg  393,00 324,00 ...           ← 1/5 PL
        cm  1,29 2,09 ...               ← 1/5 PL Durchbiegung

    Zahlen können (durch fehlerhaftes OCR-Spacing) ohne Trennzeichen
    aneinandergereiht sein – sie werden mit Regex (\\d+,\\d{2}) extrahiert.
    Reihenfolge der Lasttypen ist durch Datenblatt-Konvention festgelegt.
    """
    # Fließtext flach machen: Zwischenzeilen mit beschreibendem Text raus
    lines = md.split("\n")
    # Nur Zeilen behalten, die mit "m ", "kg/m", "kg ", "cm " oder
    # "mm " starten – andere sind beschreibender Text
    relevant: list[tuple[str, str]] = []   # (unit, raw_numbers)
    unit_re = re.compile(
        r"^\s*(m|kg/m|kg|cm|mm)\s*[:\s]\s*(\d.*)$",
        re.IGNORECASE,
    )
    for line in lines:
        m = unit_re.match(line.strip())
        if not m:
            continue
        unit = m.group(1).lower()
        raw = m.group(2)
        relevant.append((unit, raw))

    if len(relevant) < 3:
        return []

    def extract_nums(s: str) -> list[float]:
        # Findet alle Zahlen im Format "DDD,DD" oder "DDD.DD"
        nums = []
        for nm in re.finditer(r"(\d+)[,.](\d{1,2})", s):
            try:
                v = float(f"{nm.group(1)}.{nm.group(2)}")
                nums.append(v)
            except ValueError:
                continue
        return nums

    # Erste Zeile: Stützweiten (m)
    spans: list[float] = []
    rest_idx = 0
    for i, (unit, raw) in enumerate(relevant):
        if unit == "m":
            spans = extract_nums(raw)
            rest_idx = i + 1
            break
    if not spans:
        return []
    n_spans = len(spans)
    if n_spans < 2:
        return []

    # Erwartete Reihenfolge: UDL, UDL_defl, CPL, CPL_defl,
    #                       1/3, 1/3_defl, 1/4, 1/4_defl, 1/5, 1/5_defl
    expected = [
        ("kg/m", LoadType.UDL, "load"),
        ("cm", LoadType.UDL, "defl"),
        ("kg", LoadType.CPL, "load"),
        ("cm", LoadType.CPL, "defl"),
        ("kg", LoadType.THIRD, "load"),
        ("cm", LoadType.THIRD, "defl"),
        ("kg", LoadType.QUARTER, "load"),
        ("cm", LoadType.QUARTER, "defl"),
        ("kg", LoadType.FIFTH, "load"),
        ("cm", LoadType.FIFTH, "defl"),
    ]

    # Werte einsammeln, jeweils der erste passende Unit-Match in Reihe
    collected: dict[tuple[LoadType, str], list[float]] = {}
    used = set()
    j = rest_idx
    for exp_unit, lt, role in expected:
        # Nächste Zeile, die diesen Unit liefert
        while j < len(relevant):
            unit, raw = relevant[j]
            j += 1
            if j - 1 in used:
                continue
            if unit != exp_unit:
                # Bei mm statt cm akzeptieren
                if not (exp_unit == "cm" and unit == "mm"):
                    continue
            nums = extract_nums(raw)
            if len(nums) < 2:
                continue
            collected[(lt, role)] = nums[:n_spans]
            used.add(j - 1)
            break

    entries: list[LoadTableEntry] = []
    for lt in (LoadType.UDL, LoadType.CPL, LoadType.THIRD, LoadType.QUARTER,
               LoadType.FIFTH):
        loads = collected.get((lt, "load"))
        defls = collected.get((lt, "defl"))
        if not loads or not defls:
            continue
        # cm → mm
        defls_mm = [d * 10.0 for d in defls]
        for k, span in enumerate(spans):
            if k >= len(loads) or k >= len(defls_mm):
                break
            if span <= 0 or loads[k] <= 0 or defls_mm[k] <= 0:
                continue
            entries.append(LoadTableEntry(
                span_m=span,
                load_type=lt,
                max_load_kg=loads[k],
                deflection_mm=defls_mm[k],
            ))
    return entries


def _parse_plain_text_capacity_table(text: str) -> list[LoadTableEntry]:
    """Fallback fuer sauber extrahierbare PDF-Texttabellen wie ATC SB50PT-4.

    Erwartet zeilenweise Daten mit je 11 Zahlen:
    Spannweite, UDL Last/Defl, CPL Last/Defl, 1/3 Last/Defl,
    1/4 Last/Defl, 1/5 Last/Defl.
    """
    start = text.lower().find("tragkraft")
    if start < 0:
        return []
    tail = text[start:]
    unit_match = re.search(r"kg\s*\(4x\)\s*mm", tail, re.IGNORECASE)
    if unit_match:
        tail = tail[unit_match.end():]

    nums: list[float] = []
    for m in re.finditer(r"\d+(?:[\.,]\d+)?", tail):
        try:
            nums.append(float(m.group(0).replace(",", ".")))
        except ValueError:
            continue

    entries: list[LoadTableEntry] = []
    load_types = [
        LoadType.UDL,
        LoadType.CPL,
        LoadType.THIRD,
        LoadType.QUARTER,
        LoadType.FIFTH,
    ]
    i = 0
    last_span = 0.0
    while i + 10 < len(nums):
        span = nums[i]
        row = nums[i + 1:i + 11]
        if entries and span <= last_span:
            break
        if not (1.0 <= span <= 30.0 and all(v > 0 for v in row)):
            i += 1
            continue
        for lt_idx, lt in enumerate(load_types):
            load = row[lt_idx * 2]
            defl = row[lt_idx * 2 + 1]
            entries.append(LoadTableEntry(
                span_m=span,
                load_type=lt,
                max_load_kg=load,
                deflection_mm=defl,
            ))
        last_span = span
        i += 11

    return entries


_MANUFACTURERS = [
    ("EuroTruss", ["eurotruss"]),
    ("GlobalTruss", ["globaltruss", "global truss", "global_truss"]),
    ("ATC", ["atc-truss", "atc truss", "atc"]),
    ("Prolyte", ["prolyte"]),
    ("Litec", ["litec"]),
    ("Naxpro", ["naxpro", "naxpro-truss"]),
    ("Milos", ["milos"]),
    ("HOFKON", ["hofkon"]),
    ("Alutruss", ["alutruss"]),
]


def _detect_manufacturer(text: str) -> Optional[str]:
    low = text.lower()
    for canonical, aliases in _MANUFACTURERS:
        for a in aliases:
            if a in low:
                return canonical
    return None


_MODEL_BLACKLIST = {
    "GLOBAL", "EURO", "PROLYTE", "LITEC", "MILOS", "ALUTRUSS", "NAXPRO",
    "SYSTEM", "POINT", "TRUSS", "LOAD", "LOADING",
    "EN", "DIN", "ANSI", "TUV", "TÜV", "AND", "FOR", "INC", "THE",
    "INC", "INCLUSIVE", "TECHNICAL", "DATA",
    "A2", "A3", "A4",  # Norm-Anhänge
}


def _detect_model_code(md: str) -> Optional[str]:
    """Versucht einen Modell-Code aus dem Markdown zu lesen.
    Akzeptiert Codes mit oder ohne Ziffern (z. B. ST, XD, F34, FD34, H30V)."""

    def _accept(code: str) -> bool:
        code = code.upper()
        return (
            len(code) >= 2
            and len(code) <= 10
            and re.fullmatch(r"[A-Z][A-Z0-9-]{1,9}", code) is not None
            and code not in _MODEL_BLACKLIST
        )

    # Pattern 1: Solo-Header wie "## F34" (wird zuerst probiert,
    # damit Brand-Header wie "## GLOBAL TRUSS F34" nicht GLOBAL einfangen)
    for m in re.finditer(
        r"^#{1,3}\s+([A-Z][A-Z0-9-]{1,9})\s*$", md, re.MULTILINE
    ):
        code = m.group(1).upper()
        if _accept(code):
            return code

    # Pattern 2: "## XD Loading charts" / "## ST loading charts" / "## H30V Loading charts"
    for m in re.finditer(
        r"^#{1,3}\s+([A-Z][A-Z0-9-]{1,9})\s+loading\s+charts?",
        md, re.MULTILINE | re.IGNORECASE,
    ):
        code = m.group(1).upper()
        if _accept(code):
            return code

    # Pattern 3: "## ST TRUSS SYSTEM" / "## XD specifications"
    for m in re.finditer(
        r"^#{1,3}\s+([A-Z][A-Z0-9-]{1,9})\s+(?:truss|specifications|specs)",
        md, re.MULTILINE | re.IGNORECASE,
    ):
        code = m.group(1).upper()
        if _accept(code):
            return code

    # Fallback: typische Modell-Codes mit Ziffern (z. B. F34, FD34)
    for m in re.finditer(r"\b([A-Z]{1,5}\d{1,3}[A-Z0-9-]*)\b", md):
        code = m.group(1).upper()
        if _accept(code):
            return code
    return None


def _model_from_filename(path: str) -> Optional[str]:
    """Extrahiert den Modell-Code aus dem Dateinamen.
    Bsp.: 'div0014-Eurotruss_XD_specs_ENG.pdf' → 'XD'."""
    base = os.path.basename(path)
    # Entferne typische Hersteller-Token aus dem Dateinamen, der Rest sollte
    # ein Modell-Code sein
    stem = re.sub(r"\.pdf$", "", base, flags=re.IGNORECASE)
    parts = re.split(r"[_\-\s]+", stem)
    cleaned: list[str] = []
    skip_words = {"specs", "spec", "datasheet", "data", "eng", "uk", "us",
                  "de", "db"}
    for p in parts:
        if not p:
            continue
        if re.fullmatch(r"div\d+", p, re.IGNORECASE):
            continue
        if p.lower() in skip_words:
            continue
        if re.fullmatch(r"v\d+", p, re.IGNORECASE):
            continue
        # Hersteller raus
        if any(p.lower() == a or p.lower() in a or a in p.lower()
               for _, aliases in _MANUFACTURERS for a in aliases):
            continue
        cleaned.append(p)
    # Suche kandidaten Codes (Buchstaben + optional Ziffern)
    for c in cleaned:
        if re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}", c, re.IGNORECASE):
            return c.upper()
    return None


def _extract_metadata(markdown: str,
                      pdf_path: Optional[str] = None
                      ) -> dict[str, Optional[str]]:
    """Sucht nach Hersteller, Modell, Material, Maßen und Eigengewicht.
    Nutzt Dateinamen als Fallback, wenn der Markdown-Text keine
    eindeutigen Werte liefert."""
    md = markdown
    meta: dict[str, Optional[str]] = {
        "name": None,
        "manufacturer": None,
        "model_code": None,
        "material": None,
        "width_mm": None,
        "height_mm": None,
        "weight_per_meter_kg": None,
    }

    # Hersteller (Text → sonst Dateiname)
    meta["manufacturer"] = _detect_manufacturer(md)
    if meta["manufacturer"] is None and pdf_path:
        meta["manufacturer"] = _detect_manufacturer(os.path.basename(pdf_path))

    # Modell-Code (Text → sonst Dateiname)
    meta["model_code"] = _detect_model_code(md)
    if meta["model_code"] is None and pdf_path:
        meta["model_code"] = _model_from_filename(pdf_path)

    # Name = "<Hersteller> <Modell>"
    if meta["manufacturer"] and meta["model_code"]:
        meta["name"] = f"{meta['manufacturer']} {meta['model_code']}"
    elif meta["model_code"]:
        meta["name"] = meta["model_code"]

    # Material
    for mat in ["Aluminium", "Aluminum", "Steel", "Stahl"]:
        if re.search(re.escape(mat), md, re.IGNORECASE):
            meta["material"] = "Aluminium" if "alumin" in mat.lower() else mat
            break

    # Eigengewicht: "weight ... kg/m" oder "Gewicht ... kg/m"
    m = re.search(
        r"(?:weight|gewicht)[^\d]{0,30}(\d+[\.,]?\d*)\s*kg/?m",
        md, re.IGNORECASE,
    )
    if m:
        v = _to_float(m.group(1))
        if v and 0 < v < 100:
            meta["weight_per_meter_kg"] = v

    # Breite × Höhe: "Width: 290 mm Height: 290 mm" oder ähnlich
    m = re.search(r"(?:width|breite)[^\d]{0,15}(\d+[\.,]?\d*)\s*mm",
                  md, re.IGNORECASE)
    if m:
        v = _to_float(m.group(1))
        if v and 0 < v < 5000:
            meta["width_mm"] = v
    m = re.search(r"(?:height|höhe)[^\d]{0,15}(\d+[\.,]?\d*)\s*mm",
                  md, re.IGNORECASE)
    if m:
        v = _to_float(m.group(1))
        if v and 0 < v < 5000:
            meta["height_mm"] = v

    return meta
