"""OKR 2026 monthly targets — from OKR target spreadsheet (Jan–Dec 2026).

Used as dashboard defaults; user edits in the Target tab override these values
(stored in browser localStorage).
"""
from __future__ import annotations

SOLD_FROM_SELECTION_TARGET_NAME = "Sold from selection (store level)"

# 12 months: Jan–Dec 2026. None = no monthly target in spreadsheet.
OKR_2026_TARGET_BY_METRIC: dict[str, list[float | None]] = {
    "Orders": [386, 329, 357, 381, 410, 408, 447, 458, 460, 498, 481, 503],
    "DDE FEE/order": [154.8, 152.8, 154.1, 158.2, 157.2, 157.8, 160.1, 162, 164, 164.9, 165.9, 167],
    "New Clients": [126, 126, 118, 118, 143, 143, 151, 151, 160, 168, 168, 177],
    "New Client Conversion": [26, 26, 25, 24, 23, 26, 25, 25, 24, 25, 25, 26],
    "Returning Clients": [208, 214, 236, 259, 259, 259, 293, 293, 293, 319, 319, 319],
    "Returning Client Conversion": [58, 58, 55, 55, 60, 61, 61, 56, 61, 62, 62, 62],
    "PPM%": [37.0, 37.2, 37.3, 37.4, 37.5, 37.6, 37.6, 37.6, 37.7, 37.8, 37.9, 37.9],
    # Spreadsheet shows negative shrink; dashboard stores positive (|value|).
    "Shrink/DDE FEE": [1.5, 1.5, 1.6, 1.6, 1.7, 1.7, 1.7, 1.7, 1.4, 1.4, 1.3, 1.4],
    "OFL / order (ILS)": [13.0, 13.3, 13.3, 14.5, 14.5, 12.8, 13.8, 13.7, 16.5, 13.7, 13.8, 13.8],
    "VP%": [0.9, 2.8, 1.2, -0.5, 3.9, 2.2, 2.0, 6.1, 1.8, 3.3, 4.4, 4.8],
    "Weighted Availability": [92.0, 92.0, 90.5, 89.0, 90.0, 90.5, 91.5, 92.0, 89.0, 88.9, 91.0, 91.5],
    "KVI & Promo WA%": [92.4, 93.7, 89.0, 92.0, 92.0, 91.5, 93.8, 92.5, 91.5, 89.0, 93.8, 92.5],
    SOLD_FROM_SELECTION_TARGET_NAME: [89.0, 82.0, 83.0, 84.0, 84.0, 85.0, 83.0, 86.0, 87.0, 87.0, 87.0, 88.0],
    "POFR%": [93.5, 93.5, 93.5, 93.5, 93.5, 93.5, 95.2, 95.2, 95.2, 95.2, 95.2, 95.2],
    "Under 45min >": [55, 55, 55, 55, 55, 55, 67, 67, 67, 67, 67, 67],
    "Maintenance costs": [280, 280, 280, 280, 300, 310, 330, 330, 330, 340, 340, 340],
    "Fulfillment & Drive partner": [83333, 83333, 83333, 83333, 83333, 83333, None, None, None, None, None, None],
    "Turning B stores to A": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    "Avg Units per Order": [11.6, 11.6, 11.6, 11.8, 11.8, 11.8, 12.15, 12.15, 12.15, 12.32, 12.32, 12.32],
    "Order Frequency": [2.3, 2.3, 2.3, 2.4, 2.4, 2.4, 2.55, 2.55, 2.55, 2.65, 2.65, 2.65],
    "Penetration Rate": [14.6, 14.6, 14.6, 15.0, 15.0, 15.0, 15.5, 15.5, 15.5, 16.0, 16.0, 16.0],
    "Area Product Selection": [4850, 5000, 5100, 5100, 5100, 5200, 5250, 5250, 5300, 5400, 5400, 5400],
    "%Fresh Food / DDE": [38.3, 38.3, 38.3, 38.4, 38.4, 38.4, 38.4, 38.5, 38.6, 38.8, 38.8, 38.9],
    "IDQ": [97.7, 97.7, 97.65, 98.0, 98.0, 98.0, 98.5, 98.5, 98.5, 99.0, 99.0, 99.0],
    "UPH >": [119.5, 120.2, 119.9, 120.3, 118.4, 118.1, 117.6, 120.1, 122, 126.1, 127.5, 120.5],
}


def build_default_targets_flat(month_keys: list[str]) -> dict[str, float]:
    """Flat map: 'Metric|2026-01' -> value (for embedded dashboard JS)."""
    out: dict[str, float] = {}
    for metric, values in OKR_2026_TARGET_BY_METRIC.items():
        for i, month in enumerate(month_keys):
            if i >= len(values):
                break
            v = values[i]
            if v is None:
                continue
            out[f"{metric}|{month}"] = float(v)
    return out
