"""Interpolation der zulässigen Lasten und Durchbiegungen aus den Datenblatttabellen."""
import numpy as np
from scipy.interpolate import interp1d
from typing import Optional

from trusscalc.core.models import TrussType, LoadType


class LoadTableInterpolator:
    """Interpoliert Maximallasten und Durchbiegungen für eine gegebene Stützweite.

    Nutzt – wenn genug Daten vorhanden sind – ein **Timoshenko-2-Parameter-Modell**:
    EI (Biegesteifigkeit) und GA (Schubsteifigkeit) werden gemeinsam aus allen
    Datenblatt-Zeilen über Least-Squares gefittet. Damit lässt sich Bieg- und
    Schubverformung getrennt vorhersagen, was bei Traversen wesentlich genauer ist
    als ein reines Euler-Bernoulli-Modell.

    Fällt auf Einzelzeilen-Rückrechnung zurück, wenn der Fit nicht möglich ist
    (z. B. nur eine einzige Datenblatt-Zeile vorhanden).
    """

    def __init__(self, truss_type: TrussType) -> None:
        self.truss = truss_type
        # Eigengewicht der Traverse (für korrekte EI-Kalibrierung wichtig:
        # Datenblatt-δ enthält auch den Eigengewichts-Anteil)
        self._self_weight_kg_per_m: float = float(
            truss_type.weight_per_meter_kg or 0.0
        )
        self._tables: dict[LoadType, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._fit_cache: Optional[tuple[float, float]] = None
        self._fit_done: bool = False
        # Pro Lasttyp gefittete (EI, GA) – nur Zeilen dieses Typs
        self._fit_per_type: dict[LoadType, Optional[tuple[float, float]]] = {}
        self._fit_per_type_done: bool = False
        self._build_tables()

    def _build_tables(self) -> None:
        by_type: dict[LoadType, list] = {}
        for entry in self.truss.load_table:
            by_type.setdefault(entry.load_type, []).append(entry)

        for lt, entries in by_type.items():
            entries.sort(key=lambda e: e.span_m)
            spans = np.array([e.span_m for e in entries])
            loads = np.array([e.max_load_kg for e in entries])
            deflections = np.array([e.deflection_mm for e in entries])
            self._tables[lt] = (spans, loads, deflections)

    def _interpolate(self, load_type: LoadType, span_m: float
                     ) -> Optional[tuple[float, float]]:
        if load_type not in self._tables:
            return None
        spans, loads, deflections = self._tables[load_type]
        if span_m < spans[0] or span_m > spans[-1]:
            return None

        f_load = interp1d(spans, loads, kind="linear")
        f_defl = interp1d(spans, deflections, kind="linear")
        return float(f_load(span_m)), float(f_defl(span_m))

    def max_udl(self, span_m: float) -> Optional[tuple[float, float]]:
        """Maximale UDL-Last (kg/m) und Durchbiegung (mm) für die Stützweite."""
        result = self._interpolate(LoadType.UDL, span_m)
        return result

    def max_cpl(self, span_m: float) -> Optional[tuple[float, float]]:
        """Maximale Mittelpunkt-Einzellast (kg) und Durchbiegung (mm)."""
        return self._interpolate(LoadType.CPL, span_m)

    def allowable_deflection_mm(self, span_m: float) -> Optional[float]:
        """Zulässige Durchbiegung an einer beliebigen Stützweite.

        Pro Lasttyp wird die Maximaldurchbiegung im Timoshenko-Modell mit dem
        zugehörigen, lasttyp-spezifischen Fit vorhergesagt. Konservativ wird
        das Minimum über alle verfügbaren Lastarten gewählt. Fällt auf das
        Single-Row-Modell zurück, wenn kein Fit möglich ist.
        """
        candidates: list[float] = []
        for load_type in self._tables:
            max_load = self._max_load_at_span(load_type, span_m)
            if max_load is None or max_load <= 0:
                continue

            # Bevorzugt: lasttyp-spezifischer Fit
            type_fit = self._best_fit_for(load_type)
            if type_fit is not None:
                delta_mm = self.predicted_deflection_mm(load_type, max_load, span_m)
            else:
                ei = self._ei_from_row(load_type, span_m)
                if ei is None or ei <= 0:
                    continue
                delta_mm = self._beam_deflection(load_type, max_load, span_m, ei)

            if delta_mm is not None and delta_mm > 0:
                candidates.append(delta_mm)
        return min(candidates) if candidates else None

    def _max_load_at_span(self, load_type: LoadType, span_m: float) -> Optional[float]:
        """Schätzt die maximal zulässige Last an einer beliebigen Stützweite.

        Nutzt im moment-limitierten Bereich:
        - Punktlasten: ``P · L ≈ const``
        - Streckenlast (UDL): ``w · L² ≈ const``

        Gegenüber linearer Interpolation der Last-Werte über die Stützweite
        gibt das wesentlich genauere Ergebnisse zwischen den Tabellenzeilen.
        """
        if load_type not in self._tables:
            return None
        spans, loads, _ = self._tables[load_type]
        if len(spans) == 0:
            return None

        if load_type == LoadType.UDL:
            product = loads * spans ** 2
            divisor = span_m ** 2
        else:
            product = loads * spans
            divisor = span_m

        if divisor <= 0:
            return None

        if len(spans) == 1:
            const = float(product[0])
        elif span_m <= float(spans[0]):
            const = float(product[0])
        elif span_m >= float(spans[-1]):
            const = float(product[-1])
        else:
            f = interp1d(spans, product, kind="linear")
            const = float(f(span_m))

        return const / divisor

    @staticmethod
    def _beam_deflection(load_type: LoadType, load_val: float, L: float,
                         EI: float) -> Optional[float]:
        """Vorhergesagte Maximaldurchbiegung in mm bei gegebenem EI (nur Biegung)."""
        if EI <= 0 or L <= 0:
            return None
        if load_type == LoadType.UDL:
            w = load_val * 9.81
            delta_m = 5 * w * L ** 4 / (384 * EI)
        elif load_type == LoadType.CPL:
            P = load_val * 9.81
            delta_m = P * L ** 3 / (48 * EI)
        elif load_type == LoadType.THIRD:
            P = load_val * 9.81
            a = L / 3.0
            delta_m = P * a * (3 * L ** 2 - 4 * a ** 2) / (24 * EI)
        elif load_type == LoadType.QUARTER:
            P = load_val * 9.81
            delta_m = 19 * P * L ** 3 / (384 * EI)
        elif load_type == LoadType.FIFTH:
            P = load_val * 9.81
            delta_m = 63 * P * L ** 3 / (1000 * EI)
        else:
            return None
        return delta_m * 1000.0

    # ── Timoshenko-Modell (2-Parameter-Fit: EI + GA) ─────────────────────────

    @staticmethod
    def _coeffs_for_type(load_type: LoadType, L: float
                         ) -> Optional[tuple[float, float]]:
        """Liefert (c_bend, c_shear) so, dass die maximale Durchbiegung im
        Timoshenko-Modell ergibt:

            δ = c_bend · load_n / EI  +  c_shear · load_n / GA

        wobei ``load_n`` für Punktlasten in N je Punkt und für UDL in N/m
        einzusetzen ist; ``L`` in m, EI in N·m², GA in N.
        """
        if L <= 0:
            return None
        if load_type == LoadType.UDL:
            return (5 * L ** 4 / 384.0, L ** 2 / 8.0)
        if load_type == LoadType.CPL:
            return (L ** 3 / 48.0, L / 4.0)
        if load_type == LoadType.THIRD:
            # 2 sym. Punktlasten bei L/3 und 2L/3 (je P)
            return (23 * L ** 3 / 648.0, L / 3.0)
        if load_type == LoadType.QUARTER:
            # 3 sym. Punktlasten bei L/4, L/2, 3L/4 (je P)
            return (19 * L ** 3 / 384.0, L / 2.0)
        if load_type == LoadType.FIFTH:
            # 4 sym. Punktlasten bei L/5..4L/5 (je P)
            return (63 * L ** 3 / 1000.0, 3 * L / 5.0)
        return None

    def _solve_fit(self, rows: list[tuple[float, float, float]]
                   ) -> Optional[tuple[float, float]]:
        """Gemeinsamer LSQ-Solver. ``rows`` ist Liste von (c_bend, c_shear, δ/load).
        Liefert (EI, GA) oder None."""
        if len(rows) < 1:
            return None
        if len(rows) == 1:
            # Nur eine Zeile → reine Biegung annehmen (β = 0)
            cb, cs, y = rows[0]
            if cb <= 0 or y <= 0:
                return None
            return (cb / y, float("inf"))
        A = np.array([[r[0], r[1]] for r in rows])
        b_arr = np.array([r[2] for r in rows])
        try:
            sol, *_ = np.linalg.lstsq(A, b_arr, rcond=None)
            alpha, beta = float(sol[0]), float(sol[1])
        except Exception:
            return None
        if alpha <= 0:
            # Unphysikalisch → reine Biegung versuchen
            cb_arr = A[:, 0]
            denom = float(np.sum(cb_arr ** 2))
            if denom <= 0:
                return None
            alpha = float(np.sum(cb_arr * b_arr)) / denom
            if alpha <= 0:
                return None
            return (1.0 / alpha, float("inf"))
        EI = 1.0 / alpha
        GA = float("inf") if beta <= 0 else 1.0 / beta
        return (EI, GA)

    def fit_ei_ga(self, load_type: Optional[LoadType] = None
                  ) -> Optional[tuple[float, float]]:
        """Fittet (EI, GA) per Least-Squares.

        - ``load_type=None``: gemeinsamer Fit über alle Zeilen (kann durch
          gemischte Lastfälle verfälscht werden, etwa wenn UDL-Zeilen bei
          kurzen Spannweiten festigkeits- statt biegungslimitiert sind).
        - ``load_type=LoadType.X``: Fit nur über Zeilen dieses Typs – das ist
          das robustere Modell, sofern der Lasttyp im Projekt klar dominiert.
        """
        if load_type is not None:
            self._ensure_per_type_fit()
            return self._fit_per_type.get(load_type)

        if self._fit_done:
            return self._fit_cache

        rows: list[tuple[float, float, float]] = []
        for lt, (spans, loads, defls) in self._tables.items():
            for L, load_kg, delta_mm in zip(spans, loads, defls):
                L_f = float(L)
                load_kg_f = float(load_kg)
                delta_mm_f = float(delta_mm)
                if delta_mm_f <= 0 or L_f <= 0 or load_kg_f <= 0:
                    continue
                coeffs = self._coeffs_for_type(lt, L_f)
                if coeffs is None:
                    continue
                cb, cs = coeffs
                load_n = load_kg_f * 9.81
                delta_m = delta_mm_f / 1000.0
                rows.append((cb, cs, delta_m / load_n))
        self._fit_done = True
        self._fit_cache = self._solve_fit(rows)
        return self._fit_cache

    def _ensure_per_type_fit(self) -> None:
        if self._fit_per_type_done:
            return
        for lt, (spans, loads, defls) in self._tables.items():
            rows: list[tuple[float, float, float]] = []
            for L, load_kg, delta_mm in zip(spans, loads, defls):
                L_f = float(L)
                load_kg_f = float(load_kg)
                delta_mm_f = float(delta_mm)
                if delta_mm_f <= 0 or L_f <= 0 or load_kg_f <= 0:
                    continue
                coeffs = self._coeffs_for_type(lt, L_f)
                if coeffs is None:
                    continue
                cb, cs = coeffs
                load_n = load_kg_f * 9.81
                delta_m = delta_mm_f / 1000.0
                rows.append((cb, cs, delta_m / load_n))
            self._fit_per_type[lt] = self._solve_fit(rows)
        self._fit_per_type_done = True

    def _best_fit_for(self, load_type: Optional[LoadType]
                      ) -> Optional[tuple[float, float]]:
        """Liefert den passendsten (EI, GA)-Fit:
        - genau dieser Lasttyp, falls vorhanden;
        - sonst der per-Lasttyp Fit mit dem **kleinsten EI** (konservativ);
        - sonst der kombinierte Fit als Fallback.
        """
        self._ensure_per_type_fit()
        if load_type is not None and self._fit_per_type.get(load_type) is not None:
            return self._fit_per_type[load_type]

        per_type_fits = [f for f in self._fit_per_type.values() if f is not None]
        if per_type_fits:
            return min(per_type_fits, key=lambda f: f[0])
        return self.fit_ei_ga()

    def predicted_deflection_mm(self, load_type: LoadType, load_kg: float,
                                L: float) -> Optional[float]:
        """Vorhergesagte Durchbiegung in mm.

        Bevorzugte Methode: per-Zeile-EI (linear interpoliert in 1/EI über
        die Stützweite). Reproduziert die Datenblatt-Werte exakt an
        tabellierten Stützweiten und liefert konsistente lineare Skalierung
        mit der Last.

        Fallback: Timoshenko-LSQ-Fit, wenn keine Zeile für diesen Lasttyp
        vorhanden ist (kein Fit pro Zeile möglich).
        """
        ei = self._ei_from_row(load_type, L)
        if ei is None or ei <= 0:
            # Fallback auf LSQ-Fit
            fit = self._best_fit_for(load_type)
            if fit is None:
                return None
            EI, GA = fit
            coeffs = self._coeffs_for_type(load_type, L)
            if coeffs is None:
                return None
            cb, cs = coeffs
            load_n = load_kg * 9.81
            delta_m = cb * load_n / EI
            if GA != float("inf"):
                delta_m += cs * load_n / GA
            return delta_m * 1000.0
        return self._beam_deflection(load_type, load_kg, L, ei)

    def equivalent_ei(self, load_type: LoadType, L: float) -> Optional[float]:
        """EI, das die FEM (reine Biegung) so kalibriert, dass sie für die
        gegebene Lastart und Spannweite die Datenblatt-Durchbiegung
        reproduziert.

        Nutzt das gleiche per-Zeile-EI wie ``predicted_deflection_mm`` —
        damit ist die Konsistenz zwischen analytischer Vorhersage und FEM
        gewährleistet (sonst weichen Visualisierung und Limit voneinander ab).
        """
        ei = self._ei_from_row(load_type, L)
        if ei is not None and ei > 0:
            return ei
        # Fallback: LSQ-Fit mit Timoshenko-Korrektur
        fit = self._best_fit_for(load_type)
        if fit is None:
            return None
        EI, GA = fit
        if GA == float("inf"):
            return EI
        coeffs = self._coeffs_for_type(load_type, L)
        if coeffs is None:
            return EI
        cb, cs = coeffs
        if cb <= 0:
            return EI
        return 1.0 / (1.0 / EI + (cs / cb) / GA)

    def effective_ei(self, span_m: Optional[float] = None,
                     load_type: Optional[LoadType] = None) -> Optional[float]:
        """Äquivalente Biegesteifigkeit EI für die FEM.

        Nutzt den lasttyp-spezifischen Fit: das zurückgegebene ``EI_eff`` so,
        dass die FEM (reine Biegung) die Timoshenko-Durchbiegung für genau
        diese Lastart bei dieser Spannweite reproduziert. Ohne klare Lastart
        wird konservativ das kleinste EI_eff über alle Lastarten gewählt.
        Fällt auf Single-Row-Rückrechnung zurück, wenn keine Fits verfügbar.
        """
        if not self._tables or span_m is None:
            # Ohne Spannweite kein Fit-basierter Wert sinnvoll – Fallback
            if load_type is not None and load_type in self._tables:
                ei = self._ei_from_row(load_type, span_m)
                if ei is not None:
                    return ei
            eis = []
            for lt in self._tables:
                ei = self._ei_from_row(lt, span_m)
                if ei is not None:
                    eis.append(ei)
            return min(eis) if eis else None

        # Lasttyp-spezifisch: passendes EI_eff
        if load_type is not None:
            ei_eff = self.equivalent_ei(load_type, span_m)
            if ei_eff is not None:
                return ei_eff

        # Konservativ: kleinstes EI_eff über alle Lastarten mit gültigem Fit
        eis = []
        for lt in self._tables:
            ei_eff = self.equivalent_ei(lt, span_m)
            if ei_eff is not None and ei_eff > 0:
                eis.append(ei_eff)
        if eis:
            return min(eis)

        # Letzter Fallback: Single-Row
        if load_type is not None and load_type in self._tables:
            ei = self._ei_from_row(load_type, span_m)
            if ei is not None:
                return ei
        eis = []
        for lt in self._tables:
            ei = self._ei_from_row(lt, span_m)
            if ei is not None:
                eis.append(ei)
        return min(eis) if eis else None

    def _true_ei(self, load_type: LoadType) -> Optional[float]:
        """Das *physikalisch echte* Biege-EI: aus der längsten (durchbiegungs-
        limitierten) Datenblatt-Zeile rückgerechnet. Bei langen Spannweiten
        dominiert reine Biegung, kurze Spannweiten sind oft durch andere
        Versagenskriterien (Knoten, lokale Festigkeit) begrenzt und liefern
        zu hohe Schein-EI-Werte."""
        if load_type not in self._tables:
            return None
        spans, loads, deflections = self._tables[load_type]
        if len(spans) == 0:
            return None
        longest_idx = int(np.argmax(spans))
        return self._beam_ei(
            load_type,
            float(loads[longest_idx]),
            float(spans[longest_idx]),
            float(deflections[longest_idx]),
        )

    def true_bending_ei(self) -> Optional[float]:
        """Bestes verfügbares 'echtes' Biege-EI über alle Lasttypen.
        Wird in der FEM als einheitliches, physikalisch konstantes EI
        eingesetzt – garantiert korrekte Reaktionen und Momente bei
        statisch unbestimmten Systemen."""
        # Bevorzugt: CPL (am verlässlichsten kalibrierbar)
        for lt in (LoadType.CPL, LoadType.UDL, LoadType.THIRD,
                   LoadType.QUARTER, LoadType.FIFTH):
            ei = self._true_ei(lt)
            if ei is not None and ei > 0:
                return ei
        return None

    def stiffness_correction(self, load_type: LoadType, L: float) -> float:
        """Korrekturfaktor K(L, load_type), mit dem die FEM-Durchbiegung auf
        den Datenblatt-Wert kalibriert wird:

            δ_kalibriert = δ_FEM × K(L_subspan, load_type)

        Wichtig: K muss relativ zu jenem ``EI_global`` berechnet werden,
        das die FEM tatsächlich verwendet (``true_bending_ei()``, normalerweise
        aus CPL-Daten). Bei Verwendung des lasttyp-spezifischen ``_true_ei``
        ergäbe sich ein systematischer Offset zwischen FEM und Korrektur,
        weil das FEM die Steifigkeitsunterschiede zwischen Lasttypen nicht
        kennt.

        K wird ausschließlich auf Durchbiegungen angewendet – Reaktionen und
        Momente aus der FEM bleiben unverändert physikalisch korrekt."""
        ei_global = self.true_bending_ei()
        if ei_global is None or ei_global <= 0:
            return 1.0
        ei_local = self._ei_from_row(load_type, L)
        if ei_local is None or ei_local <= 0:
            return 1.0
        return ei_global / ei_local

    def _ei_from_row(self, load_type: LoadType,
                     span_m: Optional[float]) -> Optional[float]:
        """EI rückgerechnet pro Datenblatt-Zeile, linear in 1/EI über
        die Stützweite interpoliert.

        Vorteil: bei einer Stützweite, die exakt einer Datenblatt-Zeile
        entspricht, reproduziert die Vorhersage exakt den Datenblatt-Wert –
        gleichzeitig gibt es einen glatten Übergang zwischen Zeilen. Dieses
        Verfahren ist robust, auch wenn das pro-Zeile-EI variiert (was bei
        Traversen typisch ist, weil verschiedene Datenblatt-Zeilen durch
        unterschiedliche Versagenskriterien begrenzt sind)."""
        if load_type not in self._tables:
            return None
        spans, loads, deflections = self._tables[load_type]
        if len(spans) == 0:
            return None

        # EI pro Zeile berechnen
        rows: list[tuple[float, float]] = []
        for L_row, lv, dm in zip(spans, loads, deflections):
            ei = self._beam_ei(load_type, float(lv), float(L_row), float(dm))
            if ei is not None and ei > 0:
                rows.append((float(L_row), ei))
        if not rows:
            return None
        rows.sort(key=lambda x: x[0])

        if span_m is None:
            # Geometrischer Mittelwert über alle Zeilen
            return float(np.exp(np.mean([np.log(ei) for _, ei in rows])))

        # Außerhalb des tabellierten Bereichs: nächstgelegener Wert
        if span_m <= rows[0][0]:
            return rows[0][1]
        if span_m >= rows[-1][0]:
            return rows[-1][1]

        # Linear in 1/EI interpolieren – ergibt für CPL/UDL bei der
        # tabellierten Stützweite exakt die Datenblatt-Durchbiegung.
        for i in range(len(rows) - 1):
            L_a, ei_a = rows[i]
            L_b, ei_b = rows[i + 1]
            if L_a <= span_m <= L_b:
                t = (span_m - L_a) / (L_b - L_a)
                inv_ei = (1.0 - t) / ei_a + t / ei_b
                if inv_ei > 0:
                    return 1.0 / inv_ei
                return ei_a
        return rows[0][1]

    def _beam_ei(self, load_type: LoadType, load_val: float, L: float,
                 delta_mm: float) -> Optional[float]:
        """Rückrechnung von EI aus Last + Datenblatt-Durchbiegung.

        Wichtig: Datenblatt-δ enthält auch den Anteil aus dem Eigengewicht
        der Traverse. Daher wird das EI so bestimmt, dass

            δ_load(EI) + δ_self_weight(EI) = δ_datenblatt

        gilt – Eigengewicht physikalisch sauber abgetrennt. Dadurch liefern
        verschiedene Datenblatt-Zeilen ein nahezu konsistentes EI (statt
        eines durch Eigengewicht verzerrten "Schein-EI").
        """
        if delta_mm <= 0 or L <= 0:
            return None
        delta_m = delta_mm / 1000.0
        coeffs = self._coeffs_for_type(load_type, L)
        if coeffs is None:
            return None
        c_load, _ = coeffs
        # Eigengewichts-Anteil wirkt immer als UDL (5·L⁴/384 pro N/m)
        c_self = 5 * L ** 4 / 384.0
        numerator = (c_load * load_val
                     + c_self * self._self_weight_kg_per_m) * 9.81
        if numerator <= 0:
            return None
        return numerator / delta_m

    @property
    def span_range(self) -> Optional[tuple[float, float]]:
        if LoadType.UDL not in self._tables:
            return None
        spans = self._tables[LoadType.UDL][0]
        return float(spans[0]), float(spans[-1])
