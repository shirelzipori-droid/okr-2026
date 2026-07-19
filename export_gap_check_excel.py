"""Export Main KPIs gap check to Excel for manual verification."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from build_okr_2026_interactive_dashboard import (
    GAP_ABS_TARGET_METRICS,
    GAP_MODES,
    GAP_WEIGHT_METRICS,
    MONTH_KEYS,
    MONTH_LABELS,
)
from okr_2026_default_targets import OKR_2026_TARGET_BY_METRIC
from okr_2026_metrics_registry import DEFAULT_OWNERS, MAIN_SHEET_METRICS

ROOT = Path(__file__).resolve().parent
VALIDATION_HTML = ROOT / "auto_outputs" / "okr_2026_validation.html"
OUT_XLSX = ROOT / "auto_outputs" / "okr_2026_gap_check_v3.xlsx"

MONTHS_JAN_JUN = MONTH_KEYS[:6]
MONTH_LABELS_JJ = MONTH_LABELS[:6]


def _load_validation() -> dict:
    text = VALIDATION_HTML.read_text(encoding="utf-8")
    match = re.search(r"window\.OKR_VALIDATION = (\{.*?\});</script>", text, re.S)
    if not match:
        raise SystemExit("Run okr_2026_validation.py first.")
    return json.loads(match.group(1))


def _target(metric: str, month_idx: int) -> float | None:
    vals = OKR_2026_TARGET_BY_METRIC.get(metric)
    if not vals or month_idx >= len(vals):
        return None
    v = vals[month_idx]
    return float(v) if v is not None else None


def _actual(snow: dict, metric: str, month_idx: int) -> float | None:
    series = snow.get(metric)
    if not series or month_idx >= len(series):
        return None
    v = series[month_idx]
    return float(v) if v is not None else None


def _vp_k(vp_check: dict, month_idx: int) -> float | None:
    arr = vp_check.get("ibm_vp_total_ils") or []
    if month_idx >= len(arr) or arr[month_idx] is None:
        return None
    return float(arr[month_idx]) / 1000.0


def _gov_k(vp_check: dict, month_idx: int) -> float | None:
    arr = vp_check.get("ibm_gov_total_ils") or []
    if month_idx >= len(arr) or arr[month_idx] is None:
        return None
    return float(arr[month_idx]) / 1000.0


def _gap_cumulative_absolute(metric: str, snow: dict) -> dict:
    acts, tgts = [], []
    for i in range(6):
        a, t = _actual(snow, metric, i), _target(metric, i)
        if a is not None and t is not None:
            acts.append(a)
            tgts.append(t)
    if not acts:
        return {}
    sa, st = sum(acts), sum(tgts)
    return {
        "gap_mode": "cumulative_absolute",
        "sum_actual": sa,
        "sum_target": st,
        "gap_abs": sa - st,
        "gap_pct": None if st == 0 else 100 * (sa - st) / st,
        "ref": f"ΣT {st:,.0f}",
    }


def _gap_average(metric: str, snow: dict) -> dict:
    acts, tgts = [], []
    for i in range(6):
        a, t = _actual(snow, metric, i), _target(metric, i)
        if a is not None and t is not None:
            acts.append(a)
            tgts.append(t)
    if not acts:
        return {}
    aa, at = sum(acts) / len(acts), sum(tgts) / len(tgts)
    g = aa - at
    return {
        "gap_mode": "average_vs_average",
        "avg_actual": aa,
        "avg_target": at,
        "gap_abs": g,
        "gap_pct": None if at == 0 else 100 * g / at,
        "ref": f"Avg {aa:.2f} vs {at:.2f}",
    }


def _gap_weighted(metric: str, snow: dict) -> dict:
    w = GAP_WEIGHT_METRICS[metric]
    aw_sum = aw_w = tw_sum = tw_w = 0.0
    used = 0
    for i in range(6):
        a, t = _actual(snow, metric, i), _target(metric, i)
        wa, wt = _actual(snow, w, i), _target(w, i)
        if a is not None and wa is not None and wa > 0:
            aw_sum += a * wa
            aw_w += wa
        if t is not None and wt is not None and wt > 0:
            tw_sum += t * wt
            tw_w += wt
        if a is not None and t is not None:
            used += 1
    if not used or not aw_w or not tw_w:
        return {}
    aa, at = aw_sum / aw_w, tw_sum / tw_w
    g = aa - at
    return {
        "gap_mode": "weighted_average",
        "wavg_actual": aa,
        "wavg_target": at,
        "gap_abs": g,
        "gap_pct": None if at == 0 else 100 * g / at,
        "ref": f"Wavg {aa:.2f} vs {at:.2f} · {w}",
    }


def _gap_gov_vp(snow: dict, vp_check: dict) -> dict:
    abs_metric = GAP_ABS_TARGET_METRICS["VP%"]
    vp_a = vp_t = gov = 0.0
    used = 0
    for i in range(6):
        a, t = _vp_k(vp_check, i), _target(abs_metric, i)
        g = _gov_k(vp_check, i)
        if a is None or t is None or g is None:
            continue
        vp_a += a
        vp_t += t
        gov += g
        used += 1
    if not used or not gov:
        return {}
    g = vp_a - vp_t
    vp_pct_a = 100 * vp_a / gov
    vp_pct_t = 100 * vp_t / gov
    return {
        "gap_mode": "gov_weighted_cumulative",
        "sum_vp_actual_k": vp_a,
        "sum_vp_target_k": vp_t,
        "gap_abs_k": g,
        "gap_pct": None if vp_t == 0 else 100 * g / vp_t,
        "vp_pct_actual": vp_pct_a,
        "vp_pct_target": vp_pct_t,
        "ref": f"ΣVP {vp_a:,.0f}K vs {vp_t:,.0f}K · GOV {vp_pct_a:.2f}% vs {vp_pct_t:.2f}%",
    }


def _compute_gap(metric: str, snow: dict, vp_check: dict) -> dict:
    mode = GAP_MODES.get(metric, "absolute")
    if mode == "cumulative_absolute":
        return _gap_cumulative_absolute(metric, snow)
    if mode == "average_vs_average":
        return _gap_average(metric, snow)
    if mode == "weighted_average":
        return _gap_weighted(metric, snow)
    if mode == "gov_weighted_cumulative":
        return _gap_gov_vp(snow, vp_check)
    return _gap_cumulative_absolute(metric, snow)


def main() -> None:
    val = _load_validation()
    snow = val["snowflake"]
    vp_check = val.get("vp_cross_check") or {}

    monthly_rows: list[dict] = []
    gap_rows: list[dict] = []

    for metric in MAIN_SHEET_METRICS:
        owner = DEFAULT_OWNERS.get(metric, {})
        row: dict = {
            "Leader": owner.get("leader", ""),
            "Partner": owner.get("partner", ""),
            "Metric": metric,
            "Gap Mode": GAP_MODES.get(metric, "absolute"),
        }
        for i, lbl in enumerate(MONTH_LABELS_JJ):
            row[f"{lbl} Actual"] = _actual(snow, metric, i)
        row[""] = None  # separator between Actual block and Target block
        for i, lbl in enumerate(MONTH_LABELS_JJ):
            row[f"{lbl} Target"] = _target(metric, i)
        monthly_rows.append(row)

        gap = _compute_gap(metric, snow, vp_check)
        gap_row = {
            "Metric": metric,
            "Gap Mode": gap.get("gap_mode", ""),
            "Reference": gap.get("ref", ""),
            "Gap (abs)": gap.get("gap_abs", gap.get("gap_abs_k")),
            "Gap (%)": gap.get("gap_pct"),
        }
        for k, v in gap.items():
            if k not in ("gap_mode", "ref", "gap_abs", "gap_pct", "gap_abs_k"):
                gap_row[k] = v
        gap_rows.append(gap_row)

    # VP absolute detail sheet — Actual block left, Target block right
    vp_rows = []
    for i, lbl in enumerate(MONTH_LABELS_JJ):
        vp_rows.append({
            "Month": lbl,
            "VP Actual (K ILS)": _vp_k(vp_check, i),
            "GOV Actual (K ILS)": _gov_k(vp_check, i),
            "VP% Actual": _actual(snow, "VP%", i),
            " ": None,
            "VP Target (K ILS)": _target("VP (K ILS)", i),
            "VP% Target": _target("VP%", i),
        })

    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        pd.DataFrame(monthly_rows).to_excel(writer, sheet_name="Monthly Actual+Target", index=False)
        pd.DataFrame(gap_rows).to_excel(writer, sheet_name="Gap Summary Jan-Jun", index=False)
        pd.DataFrame(vp_rows).to_excel(writer, sheet_name="VP Detail", index=False)

    print("Wrote", OUT_XLSX.name, "in", OUT_XLSX.parent.name)


if __name__ == "__main__":
    main()
