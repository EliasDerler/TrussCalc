"""SQLite Datenbank-Manager für TrussCalc."""
import sqlite3
import json
import os
from pathlib import Path
from typing import Optional

from trusscalc.core.models import (
    TrussType, LoadTableEntry, LoadType, TrussSource, Project,
    ProjectBundle, TrussSection, Support, PointLoad, DistributedLoad, UnitSystem,
)

_DB_PATH = Path(os.environ.get("TRUSSCALC_DB", "trusscalc.db"))
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    global _DB_PATH
    if db_path:
        _DB_PATH = db_path
    with get_connection() as conn:
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Erst-Befüllung: wenn DB leer, Default-Traversen importieren
    seed_default_truss_types_if_empty()


def _resources_path() -> Path:
    """Pfad zum 'resources/'-Verzeichnis – funktioniert in Dev-Mode und in
    PyInstaller-Bundles (über sys._MEIPASS)."""
    import sys
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller-Bundle
        return Path(sys._MEIPASS) / "trusscalc" / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def seed_default_truss_types_if_empty() -> int:
    """Wenn keine Traversen in der DB sind, lade `default_truss_types.json`
    und schreibe alle Einträge. Liefert Anzahl der neu hinzugefügten Typen."""
    json_path = _resources_path() / "default_truss_types.json"
    if not json_path.exists():
        return 0
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM truss_types").fetchone()
        if row and row[0] > 0:
            return 0  # DB nicht leer – kein Seeding
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    n_added = 0
    for t_data in payload.get("truss_types", []):
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
                name=t_data.get("name", "Unbenannt"),
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
    return n_added


# ── Traversentypen ────────────────────────────────────────────────────────────

def save_truss_type(truss: TrussType) -> int:
    with get_connection() as conn:
        if truss.id is None:
            cur = conn.execute(
                """INSERT INTO truss_types
                   (name, manufacturer, model_code, width_mm, height_mm,
                    weight_per_meter_kg, material, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (truss.name, truss.manufacturer, truss.model_code,
                 truss.width_mm, truss.height_mm, truss.weight_per_meter_kg,
                 truss.material, truss.source.value),
            )
            truss.id = cur.lastrowid
        else:
            conn.execute(
                """UPDATE truss_types SET name=?, manufacturer=?, model_code=?,
                   width_mm=?, height_mm=?, weight_per_meter_kg=?, material=?, source=?
                   WHERE id=?""",
                (truss.name, truss.manufacturer, truss.model_code,
                 truss.width_mm, truss.height_mm, truss.weight_per_meter_kg,
                 truss.material, truss.source.value, truss.id),
            )
        # Lasttabelle ersetzen
        conn.execute("DELETE FROM load_table_entries WHERE truss_type_id=?", (truss.id,))
        conn.executemany(
            """INSERT INTO load_table_entries
               (truss_type_id, span_m, load_type, max_load_kg, deflection_mm)
               VALUES (?,?,?,?,?)""",
            [(truss.id, e.span_m, e.load_type.value, e.max_load_kg, e.deflection_mm)
             for e in truss.load_table],
        )
    return truss.id


def load_truss_type(truss_id: int) -> Optional[TrussType]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM truss_types WHERE id=?", (truss_id,)).fetchone()
        if row is None:
            return None
        return _row_to_truss(conn, row)


def list_truss_types() -> list[TrussType]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM truss_types ORDER BY manufacturer, name").fetchall()
        return [_row_to_truss(conn, r) for r in rows]


def delete_truss_type(truss_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM truss_types WHERE id=?", (truss_id,))


def _row_to_truss(conn: sqlite3.Connection, row: sqlite3.Row) -> TrussType:
    entries = conn.execute(
        "SELECT * FROM load_table_entries WHERE truss_type_id=? ORDER BY load_type, span_m",
        (row["id"],),
    ).fetchall()
    load_table = [
        LoadTableEntry(
            id=e["id"],
            truss_type_id=e["truss_type_id"],
            span_m=e["span_m"],
            load_type=LoadType(e["load_type"]),
            max_load_kg=e["max_load_kg"],
            deflection_mm=e["deflection_mm"],
        )
        for e in entries
    ]
    return TrussType(
        id=row["id"],
        name=row["name"],
        manufacturer=row["manufacturer"],
        model_code=row["model_code"],
        width_mm=row["width_mm"],
        height_mm=row["height_mm"],
        weight_per_meter_kg=row["weight_per_meter_kg"],
        material=row["material"],
        source=TrussSource(row["source"]),
        load_table=load_table,
    )


# ── PDF-Datenblätter ──────────────────────────────────────────────────────────

def save_truss_pdf(truss_type_id: int, pdf_bytes: bytes, filename: str) -> int:
    with get_connection() as conn:
        conn.execute("DELETE FROM truss_pdfs WHERE truss_type_id=?", (truss_type_id,))
        cur = conn.execute(
            "INSERT INTO truss_pdfs (truss_type_id, pdf_data, filename) VALUES (?,?,?)",
            (truss_type_id, pdf_bytes, filename),
        )
        return cur.lastrowid


def load_truss_pdf(truss_type_id: int) -> Optional[bytes]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT pdf_data FROM truss_pdfs WHERE truss_type_id=?", (truss_type_id,)
        ).fetchone()
        return row["pdf_data"] if row else None


# ── Projekte ──────────────────────────────────────────────────────────────────

def save_project(project: Project | ProjectBundle) -> int:
    bundle = _ensure_bundle(project)
    data = _bundle_to_json(bundle)
    with get_connection() as conn:
        if bundle.id is None:
            cur = conn.execute(
                """INSERT INTO projects (name, description, project_data,
                   modified_at) VALUES (?,?,?, CURRENT_TIMESTAMP)""",
                (bundle.name, bundle.description, data),
            )
            bundle.id = cur.lastrowid
            project.id = bundle.id
        else:
            conn.execute(
                """UPDATE projects SET name=?, description=?, project_data=?,
                   modified_at=CURRENT_TIMESTAMP WHERE id=?""",
                (bundle.name, bundle.description, data, bundle.id),
            )
    return bundle.id


def load_project(project_id: int) -> Optional[ProjectBundle]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            return None
        return _json_to_bundle(row["project_data"], row["id"], row["name"], row["description"])


def list_projects() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, created_at, modified_at FROM projects ORDER BY modified_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def _project_to_json(project: Project) -> str:
    def section_dict(s: TrussSection) -> dict:
        return {"id": s.id, "length_m": s.length_m, "position_m": s.position_m,
                "truss_type_id": s.truss_type_id}

    def support_dict(s: Support) -> dict:
        return {"id": s.id, "position_m": s.position_m, "max_force_kg": s.max_force_kg}

    def pl_dict(p: PointLoad) -> dict:
        return {"id": p.id, "position_m": p.position_m, "load_kg": p.load_kg}

    def dl_dict(d: DistributedLoad) -> dict:
        return {"id": d.id, "start_m": d.start_m, "end_m": d.end_m,
                "load_kg_per_m": d.load_kg_per_m}

    return json.dumps({
        "truss_type_id": project.truss_type_id,
        "unit_system": project.unit_system.value,
        "sections": [section_dict(s) for s in project.sections],
        "supports": [support_dict(s) for s in project.supports],
        "point_loads": [pl_dict(p) for p in project.point_loads],
        "distributed_loads": [dl_dict(d) for d in project.distributed_loads],
    }, ensure_ascii=False)


def save_project_to_file(path: str, project: Project) -> None:
    """Speichert ein Projekt als eigenständige .tcproj-Datei (JSON)."""
    payload = {
        "format_version": 1,
        "name": project.name,
        "description": project.description,
        "data": json.loads(_project_to_json(project)),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load_project_from_file(path: str) -> Project:
    """Lädt ein Projekt aus einer .tcproj-Datei."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    data_str = json.dumps(payload["data"])
    return _json_to_project(
        data_str,
        pid=None,
        name=payload.get("name", "Unbenannt"),
        desc=payload.get("description", ""),
    )


def _json_to_project(data: str, pid: int, name: str, desc: str) -> Project:
    d = json.loads(data)
    sections = [TrussSection(**s) for s in d.get("sections", [])]
    supports = [Support(**s) for s in d.get("supports", [])]
    point_loads = [PointLoad(**p) for p in d.get("point_loads", [])]
    distributed_loads = [DistributedLoad(**dl) for dl in d.get("distributed_loads", [])]
    return Project(
        id=pid,
        name=name,
        description=desc,
        truss_type_id=d["truss_type_id"],
        unit_system=UnitSystem(d.get("unit_system", UnitSystem.KG_M.value)),
        sections=sections,
        supports=supports,
        point_loads=point_loads,
        distributed_loads=distributed_loads,
    )


def _project_to_dict_v2(project: Project) -> dict:
    data = json.loads(_project_to_json(project))
    data["name"] = project.name
    data["description"] = project.description
    return data


def _ensure_bundle(project: Project | ProjectBundle) -> ProjectBundle:
    if isinstance(project, ProjectBundle):
        return project
    return ProjectBundle(
        id=project.id,
        name=project.name,
        description=project.description,
        unit_system=project.unit_system,
        subprojects=[project],
    )


def _bundle_to_json(bundle: ProjectBundle) -> str:
    return json.dumps({
        "format_version": 2,
        "unit_system": bundle.unit_system.value,
        "subprojects": [_project_to_dict_v2(p) for p in bundle.subprojects],
    }, ensure_ascii=False)


def _dict_to_project_v2(data: dict, name: str = "", desc: str = "") -> Project:
    project = _json_to_project(
        json.dumps(data),
        pid=None,
        name=data.get("name") or name,
        desc=data.get("description") or desc,
    )
    return project


def _json_to_bundle(data: str, pid: int, name: str, desc: str) -> ProjectBundle:
    payload = json.loads(data)
    if "subprojects" not in payload:
        project = _json_to_project(data, None, name or "Sub-Projekt 1", desc)
        if not project.name:
            project.name = "Sub-Projekt 1"
        return ProjectBundle(
            id=pid,
            name=name or project.name or "Projekt",
            description=desc,
            unit_system=project.unit_system,
            subprojects=[project],
        )
    unit = UnitSystem(payload.get("unit_system", UnitSystem.KG_M.value))
    projects = [
        _dict_to_project_v2(
            sub,
            name=sub.get("name") or f"Sub-Projekt {idx + 1}",
            desc=sub.get("description", ""),
        )
        for idx, sub in enumerate(payload.get("subprojects", []))
    ]
    if not projects:
        projects = [Project(name="Sub-Projekt 1", truss_type_id=0, unit_system=unit)]
    for project in projects:
        project.unit_system = unit
    return ProjectBundle(
        id=pid,
        name=name or "Projekt",
        description=desc,
        unit_system=unit,
        subprojects=projects,
    )


def save_project_to_file(path: str, project: Project | ProjectBundle) -> None:
    """Speichert ein Projekt als eigenständige .tcproj-Datei (JSON v2)."""
    bundle = _ensure_bundle(project)
    payload = {
        "format_version": 2,
        "name": bundle.name,
        "description": bundle.description,
        "data": json.loads(_bundle_to_json(bundle)),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load_project_from_file(path: str) -> ProjectBundle:
    """Lädt ein Projekt aus einer .tcproj-Datei und migriert v1 nach v2."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return _json_to_bundle(
        json.dumps(payload["data"]),
        pid=None,
        name=payload.get("name", "Unbenannt"),
        desc=payload.get("description", ""),
    )
