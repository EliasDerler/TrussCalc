"""
PDF-Datenblatt-Parser für Traverse-Spezifikationsblätter.
Erkennt Lasttabellen (Stützweite, Last, Durchbiegung) automatisch.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

from trusscalc.core.models import LoadTableEntry, LoadType, TrussType, TrussSource


# Erkennungsmuster für Spaltenköpfe
_LOAD_TYPE_PATTERNS: list[tuple[LoadType, list[str]]] = [
    (LoadType.UDL,     ["udl", "uniform", "gleichmäßig", "gleichmaessig", "distributed"]),
    (LoadType.CPL,     ["cpl", "centre", "center", "center point", "mittel", "mitte"]),
    (LoadType.THIRD,   ["1/3", "third"]),
    (LoadType.QUARTER, ["1/4", "quarter"]),
    (LoadType.FIFTH,   ["1/5", "fifth"]),
]

_SPAN_PATTERNS = ["span", "stützweite", "stuetzweite", "length", "länge", "laenge", "l (m)", "m"]
_NUMBER_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*$")
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg\s*/\s*m", re.IGNORECASE)
_DIM_RE = re.compile(r"(\d+)\s*(?:x|×)\s*(\d+)\s*mm", re.IGNORECASE)


@dataclass
class ParsedDatasheet:
    """Rohergebnis des PDF-Parsings."""
    manufacturer: str = ""
    model_code: str = ""
    material: str = ""
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    weight_per_meter_kg: Optional[float] = None
    load_entries: list[LoadTableEntry] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    raw_tables: list[list[list[str]]] = field(default_factory=list)


def parse_pdf(pdf_path: str) -> ParsedDatasheet:
    """Parst ein Traversendatenblatt und gibt strukturierte Daten zurück."""
    result = ParsedDatasheet()
    try:
        with pdfplumber.open(pdf_path) as pdf:
            all_text = ""
            for page in pdf.pages:
                text = page.extract_text() or ""
                all_text += text + "\n"
                for table in page.extract_tables():
                    if table:
                        cleaned = [[_clean_cell(c) for c in row] for row in table]
                        result.raw_tables.append(cleaned)

            _extract_metadata(all_text, result)
            _extract_load_tables(result)
    except Exception as exc:
        result.parse_warnings.append(f"PDF-Lesefehler: {exc}")
    return result


def _clean_cell(cell) -> str:
    if cell is None:
        return ""
    return str(cell).replace("\n", " ").strip()


def _extract_metadata(text: str, result: ParsedDatasheet) -> None:
    # Gewicht je Meter
    weight_match = _WEIGHT_RE.search(text)
    if weight_match:
        result.weight_per_meter_kg = _parse_number(weight_match.group(1))

    # Abmessungen (z.B. "400 x 290 mm")
    dims = _DIM_RE.findall(text)
    if dims:
        # Größte Dimension = Höhe, kleinere = Breite
        for d1, d2 in dims:
            h, w = max(int(d1), int(d2)), min(int(d1), int(d2))
            if 100 < h < 2000 and 100 < w < 2000:
                result.height_mm = float(h)
                result.width_mm = float(w)
                break

    # Aluminium-Material
    if re.search(r"alum|6082|6061|en\s*aw", text, re.IGNORECASE):
        result.material = "Aluminium"

    # Hersteller-Erkennung (erste Zeile oft Hersteller)
    first_lines = text.strip().split("\n")[:5]
    known = ["globaltruss", "eurotruss", "litec", "prolyte", "milos", "tomcat"]
    for line in first_lines:
        lower = line.lower()
        for brand in known:
            if brand in lower:
                result.manufacturer = line.strip()[:60]
                break
        if result.manufacturer:
            break


def _extract_load_tables(result: ParsedDatasheet) -> None:
    for table in result.raw_tables:
        entries = _parse_table(table)
        if entries:
            result.load_entries.extend(entries)

    if not result.load_entries:
        result.parse_warnings.append(
            "Keine Lasttabelle automatisch erkannt. "
            "Bitte Werte manuell eingeben."
        )


def _parse_table(table: list[list[str]]) -> list[LoadTableEntry]:
    """Versucht aus einer rohen Tabelle Lasttabellen-Einträge zu extrahieren."""
    if not table or len(table) < 3:
        return []

    # Header-Zeile finden
    header_idx = None
    header_row = []
    for i, row in enumerate(table[:5]):
        row_text = " ".join(r.lower() for r in row if r)
        has_span = any(kw in row_text for kw in _SPAN_PATTERNS)
        has_load = any(kw in row_text for lt, kws in _LOAD_TYPE_PATTERNS for kw in kws)
        if has_span or has_load:
            header_idx = i
            header_row = row
            break

    if header_idx is None:
        # Kein Header gefunden – prüfen ob erste Spalte numerische Stützweitenwerte
        header_idx = 0
        header_row = table[0]

    # Spalten zuordnen
    col_span: Optional[int] = None
    col_map: dict[int, tuple[LoadType, str]] = {}  # col → (LoadType, "load"|"defl")

    header_text = [c.lower() for c in header_row]
    for ci, cell in enumerate(header_text):
        if any(kw in cell for kw in _SPAN_PATTERNS):
            col_span = ci
        for lt, kws in _LOAD_TYPE_PATTERNS:
            if any(kw in cell for kw in kws):
                # Prüfen ob nächste Spalte Durchbiegung ist
                col_map[ci] = (lt, "load")
                if ci + 1 < len(header_row) and _is_defl_col(header_text[ci + 1] if ci + 1 < len(header_text) else ""):
                    col_map[ci + 1] = (lt, "defl")

    # Wenn keine Header erkannt: alle numerischen Spalten durchprobieren
    if col_span is None:
        col_span = 0

    if not col_map:
        # Spaltenanzahl: Span + (Load + Defl) Paare
        n_cols = len(header_row)
        if n_cols >= 3:
            load_types = [LoadType.CPL, LoadType.UDL, LoadType.THIRD, LoadType.QUARTER, LoadType.FIFTH]
            pair_cols = n_cols - 1
            for i in range(min(pair_cols // 2, len(load_types))):
                li = 1 + i * 2
                di = li + 1
                if di < n_cols:
                    lt = load_types[i]
                    col_map[li] = (lt, "load")
                    col_map[di] = (lt, "defl")

    entries: list[LoadTableEntry] = []
    # Temporär: Lasten und Durchbiegungen getrennt sammeln
    temp: dict[tuple[LoadType, float], dict] = {}

    for row in table[header_idx + 1:]:
        if len(row) <= col_span:
            continue
        span_val = _parse_number(row[col_span])
        if span_val is None or span_val <= 0 or span_val > 100:
            continue

        for ci, (lt, kind) in col_map.items():
            if ci >= len(row):
                continue
            val = _parse_number(row[ci])
            if val is None:
                continue
            key = (lt, span_val)
            if key not in temp:
                temp[key] = {}
            temp[key][kind] = val

    for (lt, span_m), vals in temp.items():
        if "load" in vals and "defl" in vals:
            entries.append(LoadTableEntry(
                span_m=span_m,
                load_type=lt,
                max_load_kg=vals["load"],
                deflection_mm=vals["defl"],
            ))
        elif "load" in vals:
            entries.append(LoadTableEntry(
                span_m=span_m,
                load_type=lt,
                max_load_kg=vals["load"],
                deflection_mm=0.0,
            ))

    return entries


def _is_defl_col(text: str) -> bool:
    return any(kw in text for kw in ["defl", "deflec", "durchbieg", "mm", "cm", "δ"])


def _parse_number(text: str) -> Optional[float]:
    if not text:
        return None
    m = _NUMBER_RE.match(text.strip().replace(",", "."))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    # Zahl aus gemischtem Text extrahieren
    nums = re.findall(r"\d+(?:[.,]\d+)?", text)
    if nums:
        try:
            return float(nums[0].replace(",", "."))
        except ValueError:
            return None
    return None


def parsed_to_truss_type(parsed: ParsedDatasheet, name: str) -> TrussType:
    """Konvertiert ParsedDatasheet in ein TrussType-Objekt."""
    return TrussType(
        name=name,
        manufacturer=parsed.manufacturer or None,
        model_code=parsed.model_code or None,
        width_mm=parsed.width_mm,
        height_mm=parsed.height_mm,
        weight_per_meter_kg=parsed.weight_per_meter_kg,
        material=parsed.material or None,
        source=TrussSource.DATASHEET,
        load_table=parsed.load_entries,
    )
