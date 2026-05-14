"""Vorbemessung für freistehende Traversen-Tower."""
from __future__ import annotations

from trusscalc.core.models import TowerInput, TowerResult, TrussType
from trusscalc.core.interpolator import LoadTableInterpolator

GRAVITY = 9.80665


def calculate_tower(data: TowerInput, truss_type: TrussType | None = None) -> TowerResult:
    """Berechnet eine konservative V1-Vorbemessung für einen Einzeltower.

    Die Berechnung ist bewusst vom FEM-Balkenmodell getrennt. Sie liefert eine
    Gleichgewichtsbetrachtung gegen Kippen, Basislasten und eine manuelle
    Schrauben-/Verbinder-Näherung.
    """
    warnings: list[str] = []
    is_valid = True

    if data.truss_type_id <= 0 or truss_type is None:
        warnings.append("Kein Traversentyp für den Tower ausgewählt.")
        is_valid = False
    if data.height_m <= 0:
        warnings.append("Tower-Höhe muss größer als 0 m sein.")
        is_valid = False
    if data.force_height_m < 0:
        warnings.append("Angriffshöhe der Horizontalkraft darf nicht negativ sein.")
        is_valid = False
    if data.gamma <= 0:
        warnings.append("Sicherheitsfaktor muss größer als 0 sein.")
        is_valid = False

    foundation = data.foundation
    connector = data.connector
    uses_connector = foundation.type == "concrete_socket"
    if foundation.width_m <= 0:
        warnings.append("Fundamentbreite muss größer als 0 m sein.")
        is_valid = False
    if foundation.depth_m <= 0:
        warnings.append("Fundamenttiefe muss größer als 0 m sein.")
        is_valid = False
    if foundation.type == "concrete_socket" and foundation.insertion_depth_m <= 0:
        warnings.append("Einstecktiefe muss bei Beton-Sockel größer als 0 m sein.")
        is_valid = False
    if uses_connector:
        if connector.bolt_count <= 0:
            warnings.append("Schraubenanzahl muss größer als 0 sein.")
            is_valid = False
        if connector.bolt_lever_arm_m <= 0:
            warnings.append("Wirksamer Schrauben-Hebelarm muss größer als 0 m sein.")
            is_valid = False
        if connector.allowable_tension_kn <= 0:
            warnings.append("Zulässige Zugkraft je Schraube muss größer als 0 kN sein.")
            is_valid = False
        if connector.allowable_shear_kn <= 0:
            warnings.append("Zulässige Querkraft je Schraube muss größer als 0 kN sein.")
            is_valid = False

    gamma = max(data.gamma, 0.0)
    horizontal_kn = max(data.horizontal_force_kn, 0.0)
    force_height = max(data.force_height_m, 0.0)
    payload_kg = max(data.payload_kg, 0.0)
    payload_ecc = data.payload_eccentricity_m

    payload_kn = payload_kg * GRAVITY / 1000.0

    tower_self_weight = 0.0
    if truss_type and truss_type.has_weight and data.height_m > 0:
        tower_self_weight = truss_type.weight_per_meter_kg * data.height_m
    elif truss_type is not None:
        warnings.append(
            "Eigengewicht des Tower-Traversentyps ist unbekannt und wird nicht angesetzt."
        )

    foundation_weight = max(foundation.weight_kg, 0.0)
    ballast_kg = max(foundation.ballast_kg, 0.0)
    total_vertical = foundation_weight + ballast_kg + payload_kg + tower_self_weight

    base_lever = max(foundation.width_m, 0.0) / 2.0
    ballast_lever = max(base_lever + foundation.ballast_offset_m, 0.0)
    payload_lever = base_lever - payload_ecc
    payload_resisting_moment = payload_kn * max(payload_lever, 0.0)
    payload_overturning_moment = payload_kn * max(-payload_lever, 0.0)
    design_moment = gamma * (horizontal_kn * force_height + payload_overturning_moment)

    center_weight_kg = foundation_weight + tower_self_weight
    resisting_moment = (
        center_weight_kg * GRAVITY / 1000.0 * base_lever
        + payload_resisting_moment
        + ballast_kg * GRAVITY / 1000.0 * ballast_lever
    )

    tipping_util = _safe_ratio(design_moment, resisting_moment)
    missing_moment = max(0.0, design_moment - resisting_moment)
    required_ballast = 0.0
    if missing_moment > 0:
        if ballast_lever > 0:
            required_ballast = missing_moment / ballast_lever * 1000.0 / GRAVITY
        else:
            required_ballast = float("inf")
            warnings.append("Ballast-Hebelarm ist 0 m; Ballastbedarf kann nicht bestimmt werden.")

    if uses_connector:
        bolt_count = max(connector.bolt_count, 1)
        loaded_bolts = max(1.0, bolt_count / 2.0)
        bolt_tension = (
            design_moment / max(connector.bolt_lever_arm_m, 1e-9) / loaded_bolts
        )
        bolt_shear = gamma * horizontal_kn / bolt_count
        tension_util = _safe_ratio(bolt_tension, connector.allowable_tension_kn)
        shear_util = _safe_ratio(bolt_shear, connector.allowable_shear_kn)
        bolt_util = max(tension_util, shear_util)
    else:
        bolt_tension = 0.0
        bolt_shear = 0.0
        bolt_util = 0.0

    max_horizontal_force = _max_horizontal_force_kn(
        gamma=gamma,
        force_height=force_height,
        resisting_moment=resisting_moment,
        payload_overturning_moment=payload_overturning_moment,
        uses_connector=uses_connector,
        connector=connector,
    )
    edge_force_kn = 0.0
    edge_force_kg = 0.0
    if foundation.width_m > 0:
        edge_force_kn = design_moment / foundation.width_m
        edge_force_kg = edge_force_kn * 1000.0 / GRAVITY

    top_offset = 0.0
    if foundation.type == "concrete_socket":
        top_offset = (
            max(foundation.clearance_mm, 0.0)
            / max(foundation.insertion_depth_m, 1e-9)
            * max(data.height_m, 0.0)
        )
        if top_offset > 20.0:
            warnings.append(
                "Sockelspiel erzeugt einen großen Kopfversatz; Bewegungs- und Anschlagrisiko prüfen."
            )

    bending_deflection = _tower_bending_deflection_mm(
        data=data,
        truss_type=truss_type,
        horizontal_kn=horizontal_kn,
        force_height=force_height,
        payload_kn=payload_kn,
        payload_ecc=payload_ecc,
        gamma=gamma,
        warnings=warnings,
    )
    total_top_displacement = top_offset + bending_deflection

    if not is_valid:
        status = "red"
    elif tipping_util > 1.0 or bolt_util > 1.0:
        status = "red"
    elif (
        tipping_util > 0.8
        or bolt_util > 0.8
        or top_offset > 20.0
        or total_top_displacement > 20.0
    ):
        status = "yellow"
    else:
        status = "green"

    return TowerResult(
        design_moment_knm=design_moment,
        resisting_moment_knm=resisting_moment,
        tipping_utilization=tipping_util,
        required_ballast_kg=required_ballast,
        tower_self_weight_kg=tower_self_weight,
        total_vertical_load_kg=total_vertical,
        base_shear_kn=gamma * horizontal_kn,
        base_compression_kg=total_vertical,
        bolt_tension_kn=bolt_tension,
        bolt_shear_kn=bolt_shear,
        bolt_utilization=bolt_util,
        top_offset_mm=top_offset,
        bending_deflection_mm=bending_deflection,
        total_top_displacement_mm=total_top_displacement,
        status=status,
        warnings=warnings,
        is_valid=is_valid,
        max_horizontal_force_kn=max_horizontal_force,
        edge_force_kn=edge_force_kn,
        edge_force_kg=edge_force_kg,
    )


def _max_horizontal_force_kn(
    gamma: float,
    force_height: float,
    resisting_moment: float,
    payload_overturning_moment: float,
    uses_connector: bool,
    connector,
) -> float:
    if gamma <= 0 or force_height <= 0:
        return 0.0
    limits = []
    tipping_force = (resisting_moment / gamma - payload_overturning_moment) / force_height
    limits.append(tipping_force)
    if uses_connector:
        bolt_count = max(connector.bolt_count, 0)
        loaded_bolts = max(1.0, bolt_count / 2.0)
        tension_moment = (
            max(connector.allowable_tension_kn, 0.0)
            * loaded_bolts
            * max(connector.bolt_lever_arm_m, 0.0)
        )
        tension_force = (tension_moment / gamma - payload_overturning_moment) / force_height
        shear_force = max(connector.allowable_shear_kn, 0.0) * bolt_count / gamma
        limits.extend([tension_force, shear_force])
    finite_limits = [value for value in limits if value == value and value != float("inf")]
    if not finite_limits:
        return 0.0
    return max(0.0, min(finite_limits))


def _tower_bending_deflection_mm(
    data: TowerInput,
    truss_type: TrussType | None,
    horizontal_kn: float,
    force_height: float,
    payload_kn: float,
    payload_ecc: float,
    gamma: float,
    warnings: list[str],
) -> float:
    """Nähert die Kopfverformung des vertikalen Towers als Kragstab.

    Horizontalkraft wird als Punktlast in Angriffhöhe angesetzt. Exzentrische
    vertikale Zuladung wird als Kopf-/Basismoment berücksichtigt. Das ist eine
    Gebrauchstauglichkeitsnäherung und kein globaler 3D-Nachweis.
    """
    if not truss_type or data.height_m <= 0:
        return 0.0
    try:
        ei = LoadTableInterpolator(truss_type).true_bending_ei()
    except Exception:
        ei = None
    if not ei or ei <= 0:
        warnings.append(
            "Tower-Biegung konnte nicht berechnet werden, weil kein EI aus dem Datenblatt ableitbar ist."
        )
        return 0.0

    length = max(data.height_m, 0.0)
    load_height = min(max(force_height, 0.0), length)
    horizontal_n = gamma * horizontal_kn * 1000.0
    payload_moment_nm = gamma * payload_kn * 1000.0 * payload_ecc

    deflection_m = 0.0
    if horizontal_n > 0 and load_height > 0:
        deflection_m += horizontal_n * load_height**2 * (3 * length - load_height) / (6 * ei)
    if abs(payload_moment_nm) > 0:
        deflection_m += abs(payload_moment_nm) * length**2 / (2 * ei)
    return max(0.0, deflection_m * 1000.0)


def _safe_ratio(value: float, limit: float) -> float:
    if limit <= 0:
        return float("inf") if value > 0 else 0.0
    return value / limit
