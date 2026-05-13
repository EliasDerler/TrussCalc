"""FEM-Solver für Traversen-Strecken mit mehreren Auflagern (AnaStruct)."""
import numpy as np
from typing import Optional
from anastruct import SystemElements

from trusscalc.core.models import (
    TrussSection, Support, PointLoad, DistributedLoad, SupportResult, DeflectionResult,
)


_N_DEFLECTION_POINTS = 200   # Auflösung der Durchbiegungskurve


def solve(
    sections: list[TrussSection],
    supports: list[Support],
    point_loads: list[PointLoad],
    distributed_loads: list[DistributedLoad],
    ei_n_m2: float,
    self_weight_kg_per_m: Optional[float],
    total_length_m: float,
) -> tuple[list[SupportResult], DeflectionResult]:
    """
    Berechnet Auflagerkräfte und Durchbiegung.
    Iterative Auflagerentfernung wenn ein Auflager abhebt (Reaktion < 0).
    """
    active_supports = list(supports)
    for _ in range(len(supports) + 1):
        s_results, defl = _run_once(
            active_supports, point_loads, distributed_loads,
            ei_n_m2, self_weight_kg_per_m, total_length_m,
        )
        # Prüfen ob Auflager abheben
        negative = [r for r in s_results if r.reaction_kg < -0.1]
        if not negative:
            break
        # Auflager mit negativster Reaktion entfernen
        worst = min(negative, key=lambda r: r.reaction_kg)
        active_supports = [s for s in active_supports if s.id != worst.support.id]
        if not active_supports:
            break

    # Alle ursprünglichen Auflager in Ergebnis aufnehmen (inaktive mit reaction=0).
    # Für inaktive Auflager zusätzlich die Lift-Höhe an deren Position aus der
    # Durchbiegungskurve auslesen (uy > 0 ⇒ Traverse oberhalb der Auflagerlinie).
    active_ids = {r.support.id for r in s_results}
    positions_arr = np.asarray(defl.positions_m) if defl.positions_m else None
    deflections_arr = np.asarray(defl.deflections_mm) if defl.deflections_mm else None

    full_results: list[SupportResult] = []
    for sup in supports:
        if sup.id in active_ids:
            full_results.append(next(r for r in s_results if r.support.id == sup.id))
        else:
            lift_mm = 0.0
            if positions_arr is not None and deflections_arr is not None and len(positions_arr) > 0:
                idx = int(np.argmin(np.abs(positions_arr - sup.position_m)))
                d_at = float(deflections_arr[idx])
                # AnaStruct-Konvention: uy > 0 = abwärts, uy < 0 = aufwärts.
                # Aufwärts an einer abgehobenen Auflagerposition = Lift-Höhe.
                if d_at < 0:
                    lift_mm = -d_at
            full_results.append(SupportResult(
                support=sup, reaction_kg=0.0, utilization=0.0, is_active=False,
                lift_height_mm=lift_mm,
            ))

    return full_results, defl


def _run_once(
    supports: list[Support],
    point_loads: list[PointLoad],
    distributed_loads: list[DistributedLoad],
    ei_n_m2: float,
    self_weight_kg_per_m: Optional[float],
    total_length_m: float,
) -> tuple[list[SupportResult], DeflectionResult]:
    if not supports:
        raise ValueError("Mindestens ein Auflager erforderlich.")

    ss = SystemElements(EI=ei_n_m2, EA=1e9)

    # Knotenpositionen: alle "kritischen" Punkte (Auflager, Lasten, Endpunkte)
    # PLUS feine Zwischenknoten, damit die kubische Biegelinie aufgelöst wird.
    # Ohne Zwischenknoten hätte ein Element zwischen z.B. Last und fernem
    # Auflager nur 2 Knoten – das Durchbiegungsmaximum innerhalb des Elements
    # würde durch lineare Knoteninterpolation komplett verloren gehen.
    critical_positions = {0.0, total_length_m}
    critical_positions.update(s.position_m for s in supports)
    critical_positions.update(p.position_m for p in point_loads)
    for d in distributed_loads:
        critical_positions.add(d.start_m)
        critical_positions.add(d.end_m)

    n_subdiv = 200  # Auflösung über die gesamte Spannweite
    all_pos: set[float] = set(critical_positions)
    if total_length_m > 0:
        step = total_length_m / n_subdiv
        x = 0.0
        while x < total_length_m:
            all_pos.add(round(x, 6))
            x += step
    node_positions = sorted(all_pos)

    element_ids: list[int] = []
    for i in range(len(node_positions) - 1):
        x1, x2 = node_positions[i], node_positions[i + 1]
        if x2 - x1 < 1e-6:
            continue
        eid = ss.add_element([(x1, 0), (x2, 0)], EI=ei_n_m2, EA=1e9)
        element_ids.append(eid)

    # Auflager setzen
    # AnaStruct: add_support_hinged sperrt x+y (benötigt für laterale Stabilität)
    # add_support_roll (direction='x') sperrt y (vertikal), erlaubt x (horizontal)
    node_map = {pos: idx + 1 for idx, pos in enumerate(node_positions)}
    support_node_ids: dict[str, int] = {}
    first_support = True
    for sup in sorted(supports, key=lambda s: s.position_m):
        nid = _nearest_node(sup.position_m, node_positions, node_map)
        if first_support:
            ss.add_support_hinged(nid)   # Erstes Auflager: Gelenk (sperrt x+y)
            first_support = False
        else:
            ss.add_support_roll(nid)     # Weitere: Rolle (sperrt nur y)
        support_node_ids[sup.id] = nid

    # Alle UDL-Beiträge (Eigengewicht + User-Streckenlasten) pro Element
    # aufsummieren, dann EINMAL q_load aufrufen. AnaStruct addiert nicht,
    # wenn q_load mehrfach auf dasselbe Element angewendet wird, sondern
    # überschreibt den Wert – das würde alle bis auf den letzten Aufruf
    # ignorieren.
    element_q: dict[int, float] = {eid: 0.0 for eid in element_ids}

    # Eigengewicht: uniform auf allen Elementen
    if self_weight_kg_per_m and self_weight_kg_per_m > 0:
        q_self = -self_weight_kg_per_m * 9.81  # N/m, negativ = nach unten
        for eid in element_ids:
            element_q[eid] += q_self

    # User-Streckenlasten: nur auf Elemente innerhalb des Lastbereichs,
    # mit Berücksichtigung partieller Überdeckung
    for dl in distributed_loads:
        q = -dl.load_kg_per_m * 9.81
        for eid in element_ids:
            el = ss.element_map[eid]
            ex1 = el.vertex_1.x
            ex2 = el.vertex_2.x
            element_length = ex2 - ex1
            if element_length <= 1e-9:
                continue
            overlap_start = max(dl.start_m, ex1)
            overlap_end = min(dl.end_m, ex2)
            overlap_length = overlap_end - overlap_start
            if overlap_length <= 1e-6:
                continue
            # Anteil der Element-Länge, der unter Last liegt → q skalieren
            fraction = overlap_length / element_length
            element_q[eid] += q * fraction

    # Einmalig pro Element die Summe anwenden
    for eid, q_total in element_q.items():
        if abs(q_total) > 1e-9:
            ss.q_load(q_total, eid, direction="element")

    # Punktlasten
    for pl in point_loads:
        nid = _nearest_node(pl.position_m, node_positions, node_map)
        ss.point_load(nid, Fy=-pl.load_kg * 9.81)

    ss.solve()

    # Auflagerkräfte auslesen (AnaStruct gibt Node-Objekte zurück)
    s_results: list[SupportResult] = []
    for sup in supports:
        nid = support_node_ids[sup.id]
        node = ss.reaction_forces.get(nid)
        fy = node.Fy if node is not None else 0.0
        # AnaStruct Konvention: negativer Fy = Struktur drückt nach unten auf Auflager
        # → Auflagerkraft = positiv wenn Auflager gedrückt wird (Drucklager)
        reaction_kg = -fy / 9.81  # N → kg, negieren für physikalisch intuitive Darstellung
        if sup.has_max_force and sup.max_force_kg > 0:
            utilization = reaction_kg / sup.max_force_kg
        else:
            utilization = 0.0
        s_results.append(SupportResult(
            support=sup, reaction_kg=reaction_kg, utilization=utilization, is_active=True,
        ))

    # Durchbiegungskurve
    positions = np.linspace(0, total_length_m, _N_DEFLECTION_POINTS)
    deflections = _sample_deflection(ss, positions, node_positions)
    max_idx = int(np.argmax(np.abs(deflections)))
    defl_result = DeflectionResult(
        positions_m=positions.tolist(),
        deflections_mm=deflections.tolist(),
        max_deflection_mm=abs(deflections[max_idx]),
        max_deflection_position_m=float(positions[max_idx]),
    )
    return s_results, defl_result


def _nearest_node(pos: float, node_positions: list[float], node_map: dict) -> int:
    closest = min(node_positions, key=lambda p: abs(p - pos))
    return node_map[closest]


def _sample_deflection(
    ss: SystemElements, positions: np.ndarray, node_positions: list[float]
) -> np.ndarray:
    """Liest Durchbiegungswerte an beliebigen Positionen aus AnaStruct."""
    deflections = np.zeros(len(positions))
    for i, x in enumerate(positions):
        # Nächstes Element finden
        for eid, el in ss.element_map.items():
            x1 = el.vertex_1.x
            x2 = el.vertex_2.x
            if x1 <= x <= x2 + 1e-9:
                # Lokale Koordinate
                if x2 - x1 < 1e-9:
                    continue
                xi = (x - x1) / (x2 - x1)
                try:
                    # Lineare Interpolation zwischen Knoten-Durchbiegungen
                    d1 = el.node_1.uy if el.node_1 else 0.0
                    d2 = el.node_2.uy if el.node_2 else 0.0
                    d1 = d1 if d1 is not None else 0.0
                    d2 = d2 if d2 is not None else 0.0
                    deflections[i] = (d1 * (1 - xi) + d2 * xi) * 1000  # m → mm
                except Exception:
                    pass
                break
    return deflections
