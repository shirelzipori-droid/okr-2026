"""Export Main KPIs gap check to Excel — reads Actual + Target from the dashboard HTML."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DASHBOARD_HTML = ROOT / "auto_outputs" / "okr_2026_interactive_dashboard.html"
OUT_XLSX = ROOT / "auto_outputs" / "okr_2026_gap_check_latest.xlsx"


def _load_dashboard_cfg() -> dict:
    if not DASHBOARD_HTML.is_file():
        raise SystemExit("Run build_okr_2026_interactive_dashboard.py first.")
    text = DASHBOARD_HTML.read_text(encoding="utf-8")
    match = re.search(r"const CFG = (\{.*?\});", text, re.S)
    if not match:
        raise SystemExit("Dashboard payload not found in HTML.")
    return json.loads(match.group(1))


def _month_keys(cfg: dict) -> list[str]:
    return list(cfg.get("monthKeys") or [])


def _month_labels(cfg: dict) -> list[str]:
    return list(cfg.get("monthLabels") or [])


def _target(cfg: dict, metric: str, month_key: str) -> float | None:
    v = (cfg.get("defaultTargets") or {}).get(f"{metric}|{month_key}")
    return float(v) if v is not None else None


def _actual(cfg: dict, metric: str, month_idx: int) -> float | None:
    series = (cfg.get("actuals") or {}).get(metric)
    if not series or month_idx >= len(series):
        return None
    v = series[month_idx]
    return float(v) if v is not None else None


def _vp_k(cfg: dict, month_idx: int) -> float | None:
    arr = cfg.get("vpAbsoluteK") or []
    if month_idx >= len(arr) or arr[month_idx] is None:
        return None
    return float(arr[month_idx])


def _gov_k(cfg: dict, month_idx: int) -> float | None:
    arr = cfg.get("govK") or []
    if month_idx >= len(arr) or arr[month_idx] is None:
        return None
    return float(arr[month_idx])


def _gap_cumulative_absolute(cfg: dict, metric: str, month_keys: list[str]) -> dict:
    acts, tgts = [], []
    for i, mk in enumerate(month_keys):
        a, t = _actual(cfg, metric, i), _target(cfg, metric, mk)
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


def _gap_average(cfg: dict, metric: str, month_keys: list[str]) -> dict:
    acts, tgts = [], []
    for i, mk in enumerate(month_keys):
        a, t = _actual(cfg, metric, i), _target(cfg, metric, mk)
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


def _gap_weighted(cfg: dict, metric: str, month_keys: list[str]) -> dict:
    gap_weight = cfg.get("gapWeightMetrics") or {}
    w = gap_weight.get(metric, "Orders")
    aw_sum = aw_w = tw_sum = tw_w = 0.0
    used = 0
    for i, mk in enumerate(month_keys):
        a, t = _actual(cfg, metric, i), _target(cfg, metric, mk)
        wa, wt = _actual(cfg, w, i), _target(cfg, w, mk)
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


def _gap_gov_vp(cfg: dict, month_keys: list[str]) -> dict:
    gap_abs = cfg.get("gapAbsTargetMetrics") or {}
    abs_metric = gap_abs.get("VP%")
    if not abs_metric:
        return {}
    vp_a = vp_t = gov = 0.0
    used = 0
    for i, mk in enumerate(month_keys):
        a, t = _vp_k(cfg, i), _target(cfg, abs_metric, mk)
        g = _gov_k(cfg, i)
        if a is None or t is None or g is None:
            continue
        vp_a += a
        vp_t += t
        gov += g
        used += 1
    if not used or not gov:
        return {}
    gap = vp_a - vp_t
    vp_pct_a = 100 * vp_a / gov
    vp_pct_t = 100 * vp_t / gov
    return {
        "gap_mode": "gov_weighted_cumulative",
        "sum_vp_actual_k": vp_a,
        "sum_vp_target_k": vp_t,
        "gap_abs_k": gap,
        "gap_pct": None if vp_t == 0 else 100 * gap / vp_t,
        "vp_pct_actual": vp_pct_a,
        "vp_pct_target": vp_pct_t,
        "ref": f"ΣVP {vp_a:,.0f}K vs {vp_t:,.0f}K",
    }


def _compute_gap(cfg: dict, metric: str, month_keys: list[str]) -> dict:
    gap_modes = cfg.get("gapModes") or {}
    mode = gap_modes.get(metric, cfg.get("gapModeDefault", "absolute"))
    if mode == "cumulative_absolute":
        return _gap_cumulative_absolute(cfg, metric, month_keys)
    if mode == "average_vs_average":
        return _gap_average(cfg, metric, month_keys)
    if mode == "weighted_average":
        return _gap_weighted(cfg, metric, month_keys)
    if mode == "gov_weighted_cumulative":
        return _gap_gov_vp(cfg, month_keys)
    return _gap_cumulative_absolute(cfg, metric, month_keys)


def main() -> None:
    cfg = _load_dashboard_cfg()
    month_keys = _month_keys(cfg)[:6]
    month_labels = _month_labels(cfg)[:6]
    main_metrics = list(cfg.get("mainMetrics") or [])
    default_owners = cfg.get("defaultOwners") or {}
    gap_modes = cfg.get("gapModes") or {}

    monthly_rows: list[dict] = []
    gap_rows: list[dict] = []

    for metric in main_metrics:
        owner = default_owners.get(metric, {})
        row: dict = {
            "Leader": owner.get("leader", ""),
            "Partner": owner.get("partner", ""),
            "Metric": metric,
            "Gap Mode": gap_modes.get(metric, "absolute"),
        }
        for i, lbl in enumerate(month_labels):
            row[f"{lbl} Actual"] = _actual(cfg, metric, i)
        row[""] = None
        for i, mk in enumerate(month_keys):
            lbl = month_labels[i]
            row[f"{lbl} Target"] = _target(cfg, metric, mk)
        monthly_rows.append(row)

        gap = _compute_gap(cfg, metric, month_keys)
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

    vp_rows = []
    for i, (mk, lbl) in enumerate(zip(month_keys, month_labels)):
        vp_rows.append({
            "Month": lbl,
            "VP Actual (K ILS)": _vp_k(cfg, i),
            "GOV Actual (K ILS)": _gov_k(cfg, i),
            "VP% Actual": _actual(cfg, "VP%", i),
            " ": None,
            "VP Target (K ILS)": _target(cfg, "VP (K ILS)", mk),
            "VP% Target": _target(cfg, "VP%", mk),
        })

    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        pd.DataFrame(monthly_rows).to_excel(writer, sheet_name="Monthly Actual+Target", index=False)
        pd.DataFrame(gap_rows).to_excel(writer, sheet_name="Gap Summary Jan-Jun", index=False)
        pd.DataFrame(vp_rows).to_excel(writer, sheet_name="VP Detail", index=False)

    print("Wrote", OUT_XLSX.name)


if __name__ == "__main__":
    main()
