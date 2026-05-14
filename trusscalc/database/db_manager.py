"""SQLite Datenbank-Manager für TrussCalc."""
import sqlite3
import json
import os
from pathlib import Path
from typing import Optional

from trusscalc.core.models import (
    TrussType, LoadTableEntry, LoadType, TrussSource, Project,
    ProjectBundle, TrussSystem, TrussSection, Support, PointLoad,
    DistributedLoad, UnitSystem, TowerInput, TowerFoundation,
    TowerConnector, TowerResult,
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


def _system_to_dict(system: TrussSystem) -> dict:
    data = json.loads(_project_to_json(Project(
        name=system.name,
        truss_type_id=system.truss_type_id,
        sections=system.sections,
        supports=system.supports,
        point_loads=system.point_loads,
        distributed_loads=system.distributed_loads,
    )))
    data.update({
        "id": system.id,
        "name": system.name,
        "canvas_x_m": system.canvas_x_m,
        "canvas_y_m": system.canvas_y_m,
    })
    return data


def _dict_to_system(data: dict, idx: int = 0) -> TrussSystem:
    return TrussSystem(
        id=data.get("id"),
        name=data.get("name") or f"System {idx + 1}",
        truss_type_id=int(data.get("truss_type_id") or 0),
        canvas_x_m=float(data.get("canvas_x_m", 0.0)),
        canvas_y_m=float(data.get("canvas_y_m", idx)),
        sections=[TrussSection(**s) for s in data.get("sections", [])],
        supports=[Support(**s) for s in data.get("supports", [])],
        point_loads=[PointLoad(**p) for p in data.get("point_loads", [])],
        distributed_loads=[
            DistributedLoad(**dl) for dl in data.get("distributed_loads", [])
        ],
    )


def _tower_input_to_dict(data: TowerInput | None) -> dict | None:
    if data is None:
        return None
    return {
        "truss_type_id": data.truss_type_id,
        "height_m": data.height_m,
        "horizontal_force_kn": data.horizontal_force_kn,
        "force_height_m": data.force_height_m,
        "payload_kg": data.payload_kg,
        "payload_eccentricity_m": data.payload_eccentricity_m,
        "gamma": data.gamma,
        "foundation": {
            "type": data.foundation.type,
            "width_m": data.foundation.width_m,
            "depth_m": data.foundation.depth_m,
            "weight_kg": data.foundation.weight_kg,
            "ballast_kg": data.foundation.ballast_kg,
            "ballast_offset_m": data.foundation.ballast_offset_m,
            "clearance_mm": data.foundation.clearance_mm,
            "insertion_depth_m": data.foundation.insertion_depth_m,
        },
        "connector": {
            "bolt_count": data.connector.bolt_count,
            "bolt_lever_arm_m": data.connector.bolt_lever_arm_m,
            "allowable_tension_kn": data.connector.allowable_tension_kn,
            "allowable_shear_kn": data.connector.allowable_shear_kn,
        },
    }


def _dict_to_tower_input(data: dict | None) -> TowerInput:
    data = data or {}
    foundation_data = data.get("foundation") or {}
    connector_data = data.get("connector") or {}
    return TowerInput(
        truss_type_id=int(data.get("truss_type_id") or 0),
        height_m=float(data.get("height_m", 4.0)),
        horizontal_force_kn=float(data.get("horizontal_force_kn", 1.0)),
        force_height_m=float(data.get("force_height_m", data.get("height_m", 4.0))),
        payload_kg=float(data.get("payload_kg", 0.0)),
        payload_eccentricity_m=float(data.get("payload_eccentricity_m", 0.0)),
        gamma=float(data.get("gamma", 1.30)),
        foundation=TowerFoundation(
            type=foundation_data.get("type", "steel_plate"),
            width_m=float(foundation_data.get("width_m", 1.0)),
            depth_m=float(foundation_data.get("depth_m", 1.0)),
            weight_kg=float(foundation_data.get("weight_kg", 120.0)),
            ballast_kg=float(foundation_data.get("ballast_kg", 0.0)),
            ballast_offset_m=float(foundation_data.get("ballast_offset_m", 0.0)),
            clearance_mm=float(foundation_data.get("clearance_mm", 0.0)),
            insertion_depth_m=float(foundation_data.get("insertion_depth_m", 0.5)),
        ),
        connector=TowerConnector(
            bolt_count=int(connector_data.get("bolt_count", 4)),
            bolt_lever_arm_m=float(connector_data.get("bolt_lever_arm_m", 0.25)),
            allowable_tension_kn=float(connector_data.get("allowable_tension_kn", 5.0)),
            allowable_shear_kn=float(connector_data.get("allowable_shear_kn", 5.0)),
        ),
    )


def _tower_result_to_dict(result: TowerResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "design_moment_knm": result.design_moment_knm,
        "resisting_moment_knm": result.resisting_moment_knm,
        "tipping_utilization": result.tipping_utilization,
        "required_ballast_kg": result.required_ballast_kg,
        "tower_self_weight_kg": result.tower_self_weight_kg,
        "total_vertical_load_kg": result.total_vertical_load_kg,
        "base_shear_kn": result.base_shear_kn,
        "base_compression_kg": result.base_compression_kg,
        "bolt_tension_kn": result.bolt_tension_kn,
        "bolt_shear_kn": result.bolt_shear_kn,
        "bolt_utilization": result.bolt_utilization,
        "top_offset_mm": result.top_offset_mm,
        "bending_deflection_mm": result.bending_deflection_mm,
        "total_top_displacement_mm": result.total_top_displacement_mm,
        "status": result.status,
        "warnings": result.warnings,
        "is_valid": result.is_valid,
        "max_horizontal_force_kn": result.max_horizontal_force_kn,
        "edge_force_kn": result.edge_force_kn,
        "edge_force_kg": result.edge_force_kg,
    }


def _dict_to_tower_result(data: dict | None) -> TowerResult | None:
    if not data:
        return None
    return TowerResult(
        design_moment_knm=float(data.get("design_moment_knm", 0.0)),
        resisting_moment_knm=float(data.get("resisting_moment_knm", 0.0)),
        tipping_utilization=float(data.get("tipping_utilization", 0.0)),
        required_ballast_kg=float(data.get("required_ballast_kg", 0.0)),
        tower_self_weight_kg=float(data.get("tower_self_weight_kg", 0.0)),
        total_vertical_load_kg=float(data.get("total_vertical_load_kg", 0.0)),
        base_shear_kn=float(data.get("base_shear_kn", 0.0)),
        base_compression_kg=float(data.get("base_compression_kg", 0.0)),
        bolt_tension_kn=float(data.get("bolt_tension_kn", 0.0)),
        bolt_shear_kn=float(data.get("bolt_shear_kn", 0.0)),
        bolt_utilization=float(data.get("bolt_utilization", 0.0)),
        top_offset_mm=float(data.get("top_offset_mm", 0.0)),
        bending_deflection_mm=float(data.get("bending_deflection_mm", 0.0)),
        total_top_displacement_mm=float(
            data.get(
                "total_top_displacement_mm",
                float(data.get("top_offset_mm", 0.0)) + float(data.get("bending_deflection_mm", 0.0)),
            )
        ),
        status=data.get("status", "green"),
        warnings=list(data.get("warnings", [])),
        is_valid=bool(data.get("is_valid", True)),
        max_horizontal_force_kn=float(data.get("max_horizontal_force_kn", 0.0)),
        edge_force_kn=float(
            data.get(
                "edge_force_kn",
                float(data.get("edge_force_kg", 0.0)) * 9.80665 / 1000.0,
            )
        ),
        edge_force_kg=float(data.get("edge_force_kg", 0.0)),
    )


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
    project = Project(
        id=pid,
        name=name,
        description=desc,
        truss_type_id=int(d.get("truss_type_id") or 0),
        unit_system=UnitSystem(d.get("unit_system", UnitSystem.KG_M.value)),
        sections=sections,
        supports=supports,
        point_loads=point_loads,
        distributed_loads=distributed_loads,
        systems=[
            _dict_to_system(system_data, idx)
            for idx, system_data in enumerate(d.get("systems", []))
        ],
        active_system_id=d.get("active_system_id"),
        plan_system_id=d.get("plan_system_id"),
        compare_system_ids=list(d.get("compare_system_ids", [])),
        view_mode=d.get("view_mode", "plan"),
        kind=d.get("kind", "beam"),
        tower_input=_dict_to_tower_input(d.get("tower_input")) if d.get("kind") == "tower" else None,
        tower_result=_dict_to_tower_result(d.get("tower_result")),
    )
    if not project.systems and (
        project.truss_type_id or project.sections or project.supports
        or project.point_loads or project.distributed_loads
    ):
        project.systems = [_legacy_project_to_system(project)]
        project.active_system_id = project.systems[0].id
    _ensure_project_systems(project)
    return project


def _project_to_dict_v2(project: Project) -> dict:
    _ensure_project_systems(project)
    data = json.loads(_project_to_json(project))
    data["name"] = project.name
    data["description"] = project.description
    data["kind"] = project.kind or "beam"
    data["active_system_id"] = project.active_system_id
    data["plan_system_id"] = project.plan_system_id
    data["compare_system_ids"] = project.compare_system_ids
    data["view_mode"] = project.view_mode
    data["systems"] = [_system_to_dict(system) for system in project.systems]
    data["tower_input"] = _tower_input_to_dict(project.tower_input)
    data["tower_result"] = _tower_result_to_dict(project.tower_result)
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
        "format_version": 4,
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
    project.kind = data.get("kind", "beam")
    if project.kind == "tower":
        project.tower_input = _dict_to_tower_input(data.get("tower_input"))
        project.tower_result = _dict_to_tower_result(data.get("tower_result"))
        project.truss_type_id = project.tower_input.truss_type_id
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
        project.kind = project.kind or "beam"
        if project.kind == "tower" and project.tower_input is None:
            project.tower_input = TowerInput(truss_type_id=project.truss_type_id)
        project.unit_system = unit
        _ensure_project_systems(project)
    return ProjectBundle(
        id=pid,
        name=name or "Projekt",
        description=desc,
        unit_system=unit,
        subprojects=projects,
    )


def save_project_to_file(path: str, project: Project | ProjectBundle) -> None:
    """Speichert ein Projekt als eigenständige .tcproj-Datei (JSON v3)."""
    bundle = _ensure_bundle(project)
    payload = {
        "format_version": 4,
        "name": bundle.name,
        "description": bundle.description,
        "data": json.loads(_bundle_to_json(bundle)),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load_project_from_file(path: str) -> ProjectBundle:
    """Lädt ein Projekt aus einer .tcproj-Datei und migriert v1/v2 nach v3."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return _json_to_bundle(
        json.dumps(payload["data"]),
        pid=None,
        name=payload.get("name", "Unbenannt"),
        desc=payload.get("description", ""),
    )


def _legacy_project_to_system(project: Project) -> TrussSystem:
    import uuid
    return TrussSystem(
        id=str(uuid.uuid4()),
        name="System 1",
        truss_type_id=project.truss_type_id,
        canvas_x_m=0.0,
        canvas_y_m=0.0,
        sections=project.sections,
        supports=project.supports,
        point_loads=project.point_loads,
        distributed_loads=project.distributed_loads,
    )


def _ensure_project_systems(project: Project) -> None:
    import uuid
    if getattr(project, "kind", "beam") == "tower":
        if project.tower_input is None:
            project.tower_input = TowerInput(truss_type_id=project.truss_type_id)
        project.truss_type_id = project.tower_input.truss_type_id
        return
    if not project.systems:
        if (
            project.truss_type_id or project.sections or project.supports
            or project.point_loads or project.distributed_loads
        ):
            project.systems = [_legacy_project_to_system(project)]
        else:
            project.systems = [TrussSystem(id=str(uuid.uuid4()), name="System 1")]
    needs_layout = (
        len(project.systems) > 1
        and all(abs(float(system.canvas_y_m)) < 1e-9 for system in project.systems)
    )
    for idx, system in enumerate(project.systems):
        if not system.id:
            system.id = str(uuid.uuid4())
        if not system.name:
            system.name = f"System {idx + 1}"
        if needs_layout:
            system.canvas_y_m = float(idx)
    if not project.active_system_id or all(
        system.id != project.active_system_id for system in project.systems
    ):
        project.active_system_id = project.systems[0].id
    if not project.plan_system_id or all(
        system.id != project.plan_system_id for system in project.systems
    ):
        project.plan_system_id = project.active_system_id
    valid_ids = {system.id for system in project.systems}
    project.compare_system_ids = [
        system_id for system_id in project.compare_system_ids if system_id in valid_ids
    ]
    if not project.compare_system_ids:
        project.compare_system_ids = [system.id for system in project.systems if system.id != project.plan_system_id]
        if not project.compare_system_ids:
            project.compare_system_ids = [project.plan_system_id]
    _sync_project_to_active_system(project)


def _sync_project_to_active_system(project: Project) -> None:
    system = project.active_system
    if system is None:
        return
    project.truss_type_id = system.truss_type_id
    project.sections = system.sections
    project.supports = system.supports
    project.point_loads = system.point_loads
    project.distributed_loads = system.distributed_loads
