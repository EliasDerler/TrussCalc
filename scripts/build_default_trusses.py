"""Verarbeitet alle PDFs in Traversen_Datenblaetter/ mit dem KI-Parser
und schreibt das Ergebnis in trusscalc/resources/default_truss_types.json.

Diese JSON wird beim ersten Programmstart in die User-DB seeded und beim
PyInstaller-Build mit ins .exe gepackt.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Damit `python -m scripts.build_default_trusses` aus dem Projekt-Root läuft
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trusscalc.pdf.pdf_ocr import PaddleOCRPdfParser  # noqa: E402

PDF_DIR = Path(r"C:\Claude_Projekte\Traversen_Datenblaetter")
OUT_FILE = ROOT / "trusscalc" / "resources" / "default_truss_types.json"


def serialize_truss(name: str, meta: dict, entries: list) -> dict:
    return {
        "name": name,
        "manufacturer": meta.get("manufacturer"),
        "model_code": meta.get("model_code"),
        "material": meta.get("material"),
        "width_mm": meta.get("width_mm"),
        "height_mm": meta.get("height_mm"),
        "weight_per_meter_kg": meta.get("weight_per_meter_kg"),
        "load_table": [
            {
                "span_m": e.span_m,
                "load_type": e.load_type.value,
                "max_load_kg": e.max_load_kg,
                "deflection_mm": e.deflection_mm,
            }
            for e in sorted(entries, key=lambda x: (x.load_type.value, x.span_m))
        ],
    }


def main() -> None:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"Keine PDFs in {PDF_DIR}")
        return

    print(f"Found {len(pdfs)} PDF(s):")
    for p in pdfs:
        print(f"  - {p.name}")

    parser = PaddleOCRPdfParser()
    truss_data: list[dict] = []
    log_lines: list[str] = []

    overall_t0 = time.time()
    for i, pdf in enumerate(pdfs, 1):
        print(f"\n=== [{i}/{len(pdfs)}] {pdf.name} ===")
        t0 = time.time()
        try:
            result = parser.parse(str(pdf), progress_cb=lambda m: print(f"  {m}"))
        except Exception as exc:
            print(f"  FEHLER: {exc}")
            log_lines.append(f"FAIL {pdf.name}: {exc}")
            continue

        elapsed = time.time() - t0
        meta = result.metadata
        n = len(result.entries)
        name = meta.get("name") or pdf.stem
        print(f"  Name: {name}")
        print(f"  Hersteller: {meta.get('manufacturer')}")
        print(f"  Modell:     {meta.get('model_code')}")
        print(f"  Material:   {meta.get('material')}")
        print(f"  Breite:     {meta.get('width_mm')}")
        print(f"  Höhe:       {meta.get('height_mm')}")
        print(f"  Gewicht:    {meta.get('weight_per_meter_kg')} kg/m")
        print(f"  Einträge:   {n}")
        print(f"  Zeit:       {elapsed:.1f}s")

        if n == 0:
            log_lines.append(f"WARN {pdf.name}: 0 Einträge erkannt")
            continue

        truss_data.append(serialize_truss(name, meta, result.entries))
        log_lines.append(f"OK   {pdf.name}: {n} Einträge in {elapsed:.0f}s")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format_version": 1, "truss_types": truss_data}
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nGeschrieben: {OUT_FILE} "
          f"({len(truss_data)} Traversentypen)")
    print(f"Gesamtzeit: {(time.time() - overall_t0)/60:.1f} min")
    print("\nProtokoll:")
    for line in log_lines:
        print(f"  {line}")


if __name__ == "__main__":
    main()
