"""OKR 2026 monthly targets — embedded into the dashboard at build time.

These are the defaults shown in the Target tab. User edits there override
these values in browser localStorage. Gap and exports should read from the
built dashboard (CFG.defaultTargets), not from this file directly.

Yearly targets saved in the Target tab live in browser localStorage until
exported to okr_2026_published_targets.json (Target tab → Publish for sharing).
That file is merged into defaultTargets at build time so GitHub Pages viewers
see the same Yearly Target values.
"""
from __future__ import annotations

import json
from pathlib import Path

SOLD_FROM_SELECTION_TARGET_NAME = "Sold from selection (store level)"
YEARLY_TARGET_KEY = "yearly"
PUBLISHED_TARGETS_PATH = Path(__file__).resolve().parent / "okr_2026_published_targets.json"

# Single annual target per metric — key in flat map: f"{metric}|yearly"
OKR_2026_YEARLY_TARGETS: dict[str, float] = {
    "DC": 36.0,
}

# 12 months: Jan–Dec 2026. Synced with dashboard Target tab (Jan–Jun 2026).
OKR_2026_TARGET_BY_METRIC: dict[str, list[float | None]] = {
    "Orders": [366, 329, 357, 381, 410, 408, 447, 458, 460, 498, 481, 503],
    "DDE FEE/order": [154.8, 152.8, 154.1, 158.2, 157.2, 157.8, 160.1, 162, 164, 164.9, 165.9, 167],
    "FTU": [126, 126, 118, 118, 143, 143, 151, 151, 160, 168, 168, 177],
    "FTU Conversion": [26, 26, 25, 24, 23, 26, 25, 25, 24, 25, 25, 26],
    "Returning Clients": [208, 214, 236, 259, 259, 259, 293, 293, 293, 319, 319, 319],
    "Returning Client Conversion": [58, 58, 55, 55, 60, 61, 61, 56, 61, 62, 62, 62],
    "PPM%": [37.0, 37.2, 37.3, 37.4, 37.5, 37.6, 37.6, 37.6, 37.7, 37.8, 37.9, 37.9],
    # Spreadsheet shows negative shrink; dashboard stores positive (|value|).
    "Shrink/DDE FEE": [1.5, 1.5, 1.6, 1.6, 1.7, 1.7, 1.7, 1.7, 1.4, 1.4, 1.3, 1.4],
    "OFL / order (ILS)": [13.0, 13.3, 13.3, 14.5, 14.5, 12.8, 13.8, 13.7, 16.5, 13.7, 13.8, 13.8],
    "VP%": [0.9, 2.8, 1.2, -0.5, 3.9, 2.2, 2.0, 6.1, 1.8, 3.3, 4.4, 4.8],
    # Monthly Plan — Variable Profit absolute target (K ILS), GOV-weighted gap for VP%.
    "VP (K ILS)": [637, 1783, 841, -404, 3190, 1754, 1817, 4713, 1711, 3377, 4377, 5054],
    "Weighted Availability": [92.0, 92.0, 90.5, 89.0, 90.0, 90.5, 91.5, 92.0, 89.0, 88.9, 91.0, 91.5],
    "KVI & Promo WA%": [92.4, 93.7, 89.0, 92.0, 92.0, 91.5, 93.8, 92.5, 91.5, 89.0, 93.8, 92.5],
    SOLD_FROM_SELECTION_TARGET_NAME: [89.0, 82.0, 83.0, 84.0, 84.0, 85.0, 83.0, 86.0, 87.0, 87.0, 87.0, 88.0],
    "POFR%": [93.5, 93.5, 93.5, 93.5, 93.5, 93.5, 95.2, 95.2, 95.2, 95.2, 95.2, 95.2],
    "Under 45min >": [55, 55, 55, 55, 55, 55, 67, 67, 67, 67, 67, 67],
    "Maintenance costs": [280, 280, 280, 280, 300, 310, 330, 330, 330, 340, 340, 340],
    "Fulfillment & Drive partner": [83333, 83333, 83333, 83333, 83333, 83333, None, None, None, None, None, None],
    "Turning B stores to A": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    "Avg Units per Order": [11.6, 11.6, 11.6, 11.8, 11.8, 11.8, 12.15, 12.15, 12.15, 12.32, 12.32, 12.32],
    "Order Frequency": [2.98, 2.85, 3.32, 3.11, 3.04, 3.03, 2.55, 2.55, 2.55, 2.65, 2.65, 2.65],
    "Penetration Rate": [14.6, 14.6, 14.6, 15.0, 15.0, 15.0, 15.5, 15.5, 15.5, 16.0, 16.0, 16.0],
    "Available Product Selection": [4850, 5000, 5100, 5100, 5100, 5200, 5250, 5250, 5300, 5400, 5400, 5400],
    "%Fresh Food / DDE": [38.3, 38.3, 38.3, 38.4, 38.4, 38.4, 38.4, 38.5, 38.6, 38.8, 38.8, 38.9],
    "IDQ": [97.7, 97.7, 97.65, 98.0, 98.0, 98.0, 98.5, 98.5, 98.5, 99.0, 99.0, 99.0],
    "UPH >": [119.5, 120.2, 119.9, 120.3, 118.4, 118.1, 117.6, 120.1, 122, 126.1, 127.5, 120.5],
}


# Weight metric for weighted-average yearly derivation.
_GAP_WEIGHT_METRIC: dict[str, str] = {
    "DDE FEE/order": "Orders",
    "Shrink/DDE FEE": "Orders",
    "OFL / order (ILS)": "Orders",
}

# How to derive Yearly Target from the 12-month OKR plan when no explicit override exists.
# sum = Σ monthly · avg = simple average · weighted_orders = Orders-weighted average
_YEARLY_DERIVE_MODE: dict[str, str] = {
    "Orders": "sum",
    "DDE FEE/order": "weighted_orders",
    "FTU": "sum",
    "FTU Conversion": "avg",
    "Returning Clients": "sum",
    "Returning Client Conversion": "avg",
    "PPM%": "avg",
    "Shrink/DDE FEE": "weighted_orders",
    "OFL / order (ILS)": "weighted_orders",
    "VP%": "avg",
    "Weighted Availability": "avg",
    "KVI & Promo WA%": "avg",
    SOLD_FROM_SELECTION_TARGET_NAME: "avg",
    "POFR%": "avg",
    "Under 45min >": "avg",
    "Maintenance costs": "sum",
    "Fulfillment & Drive partner": "sum",
    "Turning B stores to A": "sum",
    "Avg Units per Order": "avg",
    "Order Frequency": "avg",
    "Penetration Rate": "avg",
    "Available Product Selection": "avg",
    "%Fresh Food / DDE": "avg",
    "IDQ": "avg",
    "UPH >": "avg",
}


def _monthly_target_series(metric: str, month_keys: list[str]) -> list[float]:
    values = OKR_2026_TARGET_BY_METRIC.get(metric, [])
    out: list[float] = []
    for i, _mk in enumerate(month_keys):
        if i >= len(values):
            break
        v = values[i]
        if v is None:
            continue
        out.append(float(v))
    return out


def _weighted_by_orders(metric: str, month_keys: list[str]) -> float | None:
    weights = _monthly_target_series("Orders", month_keys)
    values = _monthly_target_series(metric, month_keys)
    n = min(len(weights), len(values))
    if not n:
        return None
    w_sum = sum(weights[:n])
    if w_sum == 0:
        return None
    return sum(values[i] * weights[i] for i in range(n)) / w_sum


def build_implicit_yearly_targets(month_keys: list[str]) -> dict[str, float]:
    """Yearly Target defaults derived from the OKR monthly plan (full-year)."""
    out: dict[str, float] = {}
    for metric in OKR_2026_TARGET_BY_METRIC:
        series = _monthly_target_series(metric, month_keys)
        if not series:
            continue
        mode = _YEARLY_DERIVE_MODE.get(metric, "avg")
        if mode == "sum":
            val: float = sum(series)
        elif mode == "weighted_orders":
            w = _weighted_by_orders(metric, month_keys)
            if w is None:
                continue
            val = w
        else:
            val = sum(series) / len(series)
        out[f"{metric}|{YEARLY_TARGET_KEY}"] = round(val, 4)
    return out


def load_published_targets() -> dict[str, float | str]:
    """Targets exported from the dashboard for GitHub Pages (yearly + overrides)."""
    if not PUBLISHED_TARGETS_PATH.is_file():
        return {}
    raw = json.loads(PUBLISHED_TARGETS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float | str] = {}
    for key, val in raw.items():
        if key.startswith("_") or val is None or val == "":
            continue
        out[str(key)] = val if isinstance(val, str) else float(val)
    return out


def build_default_targets_flat(month_keys: list[str]) -> dict[str, float | str]:
    """Flat map: 'Metric|2026-01' -> value (for embedded dashboard JS)."""
    out: dict[str, float | str] = {}
    for metric, values in OKR_2026_TARGET_BY_METRIC.items():
        for i, month in enumerate(month_keys):
            if i >= len(values):
                break
            v = values[i]
            if v is None:
                continue
            out[f"{metric}|{month}"] = float(v)
    for metric, val in OKR_2026_YEARLY_TARGETS.items():
        out[f"{metric}|{YEARLY_TARGET_KEY}"] = float(val)
    for key, val in build_implicit_yearly_targets(month_keys).items():
        out[key] = val
    for key, val in load_published_targets().items():
        out[key] = val
    return out
