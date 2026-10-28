"""Transport emissions estimates from a published, citable source.

Source: U.S. EPA, "GHG Emission Factors Hub" (2025 edition, released January 2025),
Table 10 — Scope 3 Category 6 Business Travel & Category 7 Employee Commuting.
https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf

CO2e is computed from the table's per-gas factors with the Hub's own 100-year AR5
global warming potentials (Table 11): CO2 = 1, CH4 = 28, N2O = 265.

Every estimate returned carries its source, method, units, assumptions and uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass

EPA_SOURCE = {
    "name": "U.S. EPA GHG Emission Factors Hub, Table 10",
    "version": "2025 edition (January 2025)",
    "url": "https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf",
}
GWP_CH4, GWP_N2O = 28, 265
KM_PER_MILE = 1.609344


@dataclass(frozen=True)
class ModeFactor:
    key: str
    label: str
    co2_kg: float  # kg CO2 per unit
    ch4_g: float  # g CH4 per unit
    n2o_g: float  # g N2O per unit
    unit: str  # "vehicle-mile" | "passenger-mile"

    @property
    def co2e_kg(self) -> float:
        return self.co2_kg + self.ch4_g * GWP_CH4 / 1000 + self.n2o_g * GWP_N2O / 1000


# Values transcribed from EPA Hub 2025, Table 10.
FACTORS: dict[str, ModeFactor] = {
    "car": ModeFactor("car", "Passenger car", 0.297, 0.0059, 0.0053, "vehicle-mile"),
    "bus": ModeFactor("bus", "Bus", 0.066, 0.0046, 0.0019, "passenger-mile"),
    "transit_rail": ModeFactor("transit_rail", "Transit rail (subway, tram)", 0.093, 0.0075, 0.0010, "passenger-mile"),
}

# EarthPulse planning heuristics (not from EPA): when walking/cycling is offered as an option.
WALK_MAX_KM = 2.5
BIKE_MAX_KM = 10.0


def trip_estimates(one_way_km: float, car_occupants: int = 1, car_free: bool = False) -> dict:
    """Round-trip CO2e estimates per traveller for one destination.

    Distance is straight-line (great-circle), so real routes are longer and every figure is
    a lower bound. Returned dict is JSON-ready and self-describing.
    """
    occupants = max(1, min(int(car_occupants or 1), 8))
    rt_km = 2 * max(one_way_km, 0.0)
    rt_mi = rt_km / KM_PER_MILE
    modes = []
    if not car_free:
        f = FACTORS["car"]
        modes.append({
            "mode": "car", "label": f.label,
            "kg_co2e": round(rt_mi * f.co2e_kg / occupants, 2),
            "factor": f"{f.co2e_kg:.4f} kg CO2e per {f.unit}" + (f", shared by {occupants}" if occupants > 1 else ""),
        })
    for key in ("bus", "transit_rail"):
        f = FACTORS[key]
        modes.append({
            "mode": key, "label": f.label,
            "kg_co2e": round(rt_mi * f.co2e_kg, 2),
            "factor": f"{f.co2e_kg:.4f} kg CO2e per {f.unit}",
            "caveat": "Assumes a route exists — service not verified.",
        })
    if one_way_km <= BIKE_MAX_KM:
        modes.append({"mode": "bike", "label": "Bike", "kg_co2e": 0.0,
                      "factor": "No tailpipe emissions (manufacturing and food energy excluded)"})
    if one_way_km <= WALK_MAX_KM:
        modes.append({"mode": "walk", "label": "Walk", "kg_co2e": 0.0,
                      "factor": "No tailpipe emissions"})
    return {
        "kind": "computed",
        "one_way_km": round(one_way_km, 2),
        "round_trip_km": round(rt_km, 2),
        "modes": modes,
        "units": "kg CO2e per traveller, round trip",
        "method": "Straight-line distance × 2 (round trip), converted to miles, × EPA per-mile CO2e factor "
                  "(CO2 + 28×CH4 + 265×N2O). Car factor is per vehicle-mile, divided by occupants.",
        "assumptions": [
            "Straight-line distance; real road/transit routes are longer, so these are lower bounds.",
            "U.S. national-average factors; your vehicle or local transit fleet may differ.",
            f"Walking offered within {WALK_MAX_KM} km and cycling within {BIKE_MAX_KM} km (EarthPulse heuristic).",
        ],
        "uncertainty": "Directional comparison only. Typical road circuity makes true distance meaningfully longer "
                       "than straight-line; transit factors vary widely by occupancy.",
        "source": EPA_SOURCE,
    }


def leg_estimate(km: float, occupants: int = 1, car_free: bool = False) -> dict:
    """One-way leg between two stops: suggested lower-impact mode vs. driving, per traveller.

    Suggested mode is walk within WALK_MAX_KM, otherwise bus (EPA bus factor; route not verified).
    """
    occupants = max(1, min(int(occupants or 1), 8))
    km = max(km, 0.0)
    mi = km / KM_PER_MILE
    if km <= WALK_MAX_KM:
        mode, label, kg = "walk", "Walk", 0.0
    else:
        mode, label, kg = "bus", "Bus or transit", mi * FACTORS["bus"].co2e_kg
    car_kg = None if car_free else mi * FACTORS["car"].co2e_kg / occupants
    return {
        "km": round(km, 2),
        "mode": mode,
        "label": label,
        "kg_co2e": round(kg, 3),
        "car_kg_co2e": round(car_kg, 3) if car_kg is not None else None,
    }


def car_vs_lowest(est: dict) -> tuple[float | None, float]:
    """From a trip_estimates() dict: (car kg or None, lowest non-car kg)."""
    car = next((m["kg_co2e"] for m in est["modes"] if m["mode"] == "car"), None)
    low = min((m["kg_co2e"] for m in est["modes"] if m["mode"] != "car"), default=0.0)
    return car, low
