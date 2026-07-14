"""Build interactive OKR 2026 dashboard — Actual vs Target with period filter.

Sheet 1: Actual values compared to targets (red when target missed).
Sheet 2: Editable targets (auto-saved in browser localStorage).
Sheet 3: מדדים לבדיקה (Snowflake + השוואת Looker).

Usage:
  python build_okr_2026_interactive_dashboard.py
  python build_okr_2026_interactive_dashboard.py --skip-fetch
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from okr_2026_metrics_registry import (
    ALL_METRIC_NAMES,
    DEFAULT_OWNERS,
    LEADER_ORDER,
    LEADER_SHEET_METRICS,
    LEADER_FILTER_GROUPS,
    MAIN_SHEET_METRICS,
    METRIC_DATA_SOURCE,
    METRIC_WORKFLOW,
)
from okr_2026_default_targets import (
    SOLD_FROM_SELECTION_TARGET_NAME,
    build_default_targets_flat,
)
from okr_2026_dashboard import SC_APPROVAL, _load_cached_metrics
from okr_2026_validation import (
    APPROVED_LOOKER_EXPLORES,
    ESSI_SESSION_PAYLOAD,
    LOOKER,
    LOOKER_EXPLORE_NOT_CERTIFIED,
    LOOKER_FIELD_ALIASES,
    LOOKER_LINKS,
    MAINTENANCE_REVIEW_NOTE,
    MAINTENANCE_REVIEW_PAYLOAD,
    METRIC_SOURCE,
    NETSUITE_87310_KILS,
    REVIEW_TAB_METRICS,
    SESSION_REVIEW_NOTE,
    SOLD_FROM_SELECTION_NOTE,
    SOLD_FROM_SELECTION_PROMOTED_NAME,
    SOLD_FROM_SELECTION_VARIANTS,
    USER_VERIFIED,
    fetch_metrics,
)

ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "auto_outputs" / "okr_2026_interactive_dashboard.html"
VALIDATION_HTML = ROOT / "auto_outputs" / "okr_2026_validation.html"

DASHBOARD_MONTH_COUNT = 12
MONTH_KEYS = [f"2026-{m:02d}" for m in range(1, DASHBOARD_MONTH_COUNT + 1)]
MONTH_LABELS = [
    "Jan 26", "Feb 26", "Mar 26", "Apr 26", "May 26", "Jun 26",
    "Jul 26", "Aug 26", "Sep 26", "Oct 26", "Nov 26", "Dec 26",
]
STORAGE_TARGETS = "okr2026_targets_v1"
STORAGE_ACTUALS = "okr2026_actuals_v1"
STORAGE_OWNERS = "okr2026_owners_v1"
STORAGE_SOLD_CHOICE = "okr2026_sold_selection_choice_v1"

SOURCE_LABEL: dict[str, str] = {
    "snowflake": "snowflake_validated",
    "user": "user_provided",
    "manual": "manual_entry",
}

# "higher" = actual must be >= target; "lower" = actual must be <= target.
METRIC_DIRECTION: dict[str, str] = {
    "Shrink/DDE FEE": "lower",
    "OFL / order (ILS)": "lower",
    "Maintenance costs": "lower",
    "Utilities costs reduce": "lower",
    "Attrition (monthly) <": "lower",
    "Store employees absence <": "lower",
    "Early Attrition (0-3) <": "lower",
}

METRIC_HINTS: dict[str, str] = {
    "Orders": "Thousands (K)",
    "Ftu Sessions": "Thousands (K)",
    "Returning User Sessions": "Thousands (K)",
    "VSL": "ISR country incl. DC",
}

# Display format: percent | integer | decimal:N (N = decimal places for actuals)
METRIC_FORMAT: dict[str, str] = {
    "Orders": "integer",
    "DDE FEE/order": "decimal:1",
    "Ftu Sessions": "integer",
    "Ftu Conversion": "percent:1",
    "Returning User Sessions": "integer",
    "Returning User Conversion": "percent:1",
    "PPM%": "percent:1",
    "Shrink/DDE FEE": "percent:2",
    "OFL / order (ILS)": "decimal:1",
    "VP%": "percent:1",
    "Weighted Availability": "percent:1",
    "KVI & Promo WA%": "percent:1",
    "Sold from selection — sold_from_selection_perc": "percent:2",
    "Sold from selection — sold_from_product_selection_perc": "percent:2",
    SOLD_FROM_SELECTION_PROMOTED_NAME: "percent:2",
    "POFR%": "percent:1",
    "Under 45min >": "percent:1",
    "Maintenance costs": "integer",
    "Avg Units per Order": "decimal:1",
    "Order Frequency": "decimal:2",
    "Penetration Rate": "percent:1",
    "Area Product Selection": "integer",
    "%Fresh Food / DDE": "percent:2",
    "IDQ": "percent:2",
    "VSL": "percent:1",
    "UP-TIME >": "percent:1",
    "% Bad Goods Rating": "percent:2",
    "New Stores": "integer",
    "Expansion": "integer",
    "Relocation": "integer",
    "Utilities costs reduce": "percent:1",
    "Fulfillment & Drive partner": "decimal:1",
    "3PFL GOV (yearly)": "integer",
    "Robotic store": "integer",
    "Turning B stores to A": "integer",
    "Awareness": "percent:1",
    "New special vendors or categories": "integer",
    "DC": "integer",
    "Forecast accuracy +/-": "percent:1",
    "UPH >": "decimal:1",
    "Attrition (monthly) <": "percent:1",
    "IDP & HQ training": "percent:1",
    "Internal Mobility": "percent:1",
    "OPS Training": "percent:1",
    "Store employees absence <": "percent:1",
    "Early Attrition (0-3) <": "percent:1",
    "Engagme >1 (HV)": "percent:1",
    "Engagme >1 (HQ)": "percent:1",
    "EngagMe growth": "percent:1",
}


def _default_format(name: str) -> str:
    if name in METRIC_FORMAT:
        return METRIC_FORMAT[name]
    if "%" in name or name.endswith(">") or name.endswith("<"):
        return "percent:1"
    if any(x in name for x in ("Stores", "GOV", "Robotic", "vendors")):
        return "integer"
    return "decimal:1"


def _pad_series(vals: list[float | None] | None, n: int = DASHBOARD_MONTH_COUNT) -> list[float | None]:
    src = list(vals or [])
    return src + [None] * max(0, n - len(src))


def _build_payload(actuals_snow: dict[str, list[float | None]]) -> dict:
    actuals: dict[str, list[float | None]] = {}
    for name in ALL_METRIC_NAMES:
        if name in actuals_snow:
            actuals[name] = _pad_series(actuals_snow[name])
        else:
            actuals[name] = [None] * DASHBOARD_MONTH_COUNT

    looker = {
        name: {
            "label": LOOKER_LINKS.get(name, ("", ""))[0],
            "url": LOOKER_LINKS.get(name, ("", ""))[1],
        }
        for name in ALL_METRIC_NAMES
    }
    sources = {}
    for name in ALL_METRIC_NAMES:
        if name in METRIC_SOURCE:
            sources[name] = METRIC_SOURCE[name]
        else:
            sources[name] = SOURCE_LABEL.get(
                METRIC_DATA_SOURCE.get(name, "manual"), "manual_entry"
            )
    approved_metrics = [n for n in ALL_METRIC_NAMES if n not in REVIEW_TAB_METRICS]
    main_metrics = [m for m in MAIN_SHEET_METRICS if m in ALL_METRIC_NAMES]
    leader_metrics = list(LEADER_SHEET_METRICS)
    variant_meta = {
        key: {
            "metricName": spec["metric_name"],
            "lookerLabel": spec["looker_label"],
            "lookerField": spec["looker_field"],
            "lookerFieldView": spec.get("looker_field_view", "wolt_market_item_metrics"),
            "lookerExplore": spec.get("looker_explore", "wolt_market_purchases"),
            "lookerExploreModel": spec.get("looker_explore_model", "wolt_market_exploration"),
            "lookerBadge": spec.get("looker_badge", "V ✅"),
            "snowflakeField": spec["snowflake_field"],
            "alias": spec["alias"],
        }
        for key, spec in SOLD_FROM_SELECTION_VARIANTS.items()
    }
    format_map = {m: _default_format(m) for m in ALL_METRIC_NAMES}
    format_map[SOLD_FROM_SELECTION_PROMOTED_NAME] = "percent:2"
    aliases = {k: v for k, v in LOOKER_FIELD_ALIASES.items() if k in ALL_METRIC_NAMES}
    aliases[SOLD_FROM_SELECTION_PROMOTED_NAME] = "Sold from selection (store level)"
    default_owners = {
        **DEFAULT_OWNERS,
        SOLD_FROM_SELECTION_PROMOTED_NAME: {"leader": "CAT & Content", "partner": ""},
    }
    default_targets = build_default_targets_flat(MONTH_KEYS)
    return {
        "mainMetrics": main_metrics,
        "leaderMetrics": leader_metrics,
        "leaderOrder": LEADER_ORDER,
        "leaderFilterGroups": LEADER_FILTER_GROUPS,
        "metricWorkflow": METRIC_WORKFLOW,
        "baseMetrics": approved_metrics,
        "metrics": approved_metrics,
        "promotedSoldSelectionName": SOLD_FROM_SELECTION_PROMOTED_NAME,
        "soldSelectionVariants": variant_meta,
        "soldSelectionInsertAfter": "KVI & Promo WA%",
        "soldSelectionInsertAfterLeader": "Area Product Selection",
        "approvedLookerExplores": APPROVED_LOOKER_EXPLORES,
        "notCertifiedLookerExplores": LOOKER_EXPLORE_NOT_CERTIFIED,
        "reviewMetrics": list(REVIEW_TAB_METRICS),
        "reviewNote": SESSION_REVIEW_NOTE,
        "maintenanceReviewNote": MAINTENANCE_REVIEW_NOTE,
        "maintenanceReview": MAINTENANCE_REVIEW_PAYLOAD,
        "soldSelectionReviewNote": SOLD_FROM_SELECTION_NOTE,
        "lookerRef": {
            k: LOOKER[k]
            for k in REVIEW_TAB_METRICS
            if k in LOOKER
        },
        "monthKeys": MONTH_KEYS,
        "monthLabels": MONTH_LABELS,
        "defaultTargets": default_targets,
        "defaultTargetsNote": "OKR 2026 target spreadsheet · Jan–Dec 2026",
        "actuals": actuals,
        "defaultOwners": default_owners,
        "looker": looker,
        "scApproval": {k: SC_APPROVAL[k] for k in ALL_METRIC_NAMES if k in SC_APPROVAL},
        "userVerified": sorted(USER_VERIFIED),
        "essiSession": ESSI_SESSION_PAYLOAD,
        "essiSessionNote": ESSI_SESSION_PAYLOAD["noteHe"],
        "essiSessionSlack": ESSI_SESSION_PAYLOAD["slackUrl"],
        "aliases": aliases,
        "sources": sources,
        "dataSource": METRIC_DATA_SOURCE,
        "direction": {m: METRIC_DIRECTION.get(m, "higher") for m in ALL_METRIC_NAMES},
        "hints": METRIC_HINTS,
        "format": format_map,
        "storage": {
            "targets": STORAGE_TARGETS,
            "actuals": STORAGE_ACTUALS,
            "owners": STORAGE_OWNERS,
            "soldChoice": STORAGE_SOLD_CHOICE,
        },
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OKR 2026 — ISR Wolt Market</title>
  <style>
    :root {
      --bg: #eef2f7;
      --surface: #ffffff;
      --surface2: #f8fafc;
      --border: #cbd5e1;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-dim: #1d4ed8;
      --miss-bg: #fecaca;
      --miss-border: #ef4444;
      --miss-text: #7f1d1d;
      --hit-bg: #bbf7d0;
      --hit-border: #22c55e;
      --hit-text: #14532d;
      --neutral-bg: #f1f5f9;
      --tab-active: #2563eb;
      --radius: 12px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(165deg, #eef2f7 0%, #f8fafc 50%, #e2e8f0 100%);
      color: var(--text);
      min-height: 100vh;
    }
    .wrap { max-width: 1480px; margin: 0 auto; padding: 24px 20px 48px; }
    header { margin-bottom: 20px; }
    h1 { margin: 0 0 6px; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }
    .subtitle { color: var(--muted); font-size: 14px; margin: 0; }
    .toolbar {
      display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 16px 18px; margin-bottom: 16px;
    }
    .toolbar-block label { display: block; font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--muted); margin-bottom: 8px; font-weight: 600; }
    .period-chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      border: 1px solid var(--border); background: var(--surface2); color: var(--text);
      border-radius: 999px; padding: 7px 14px; font-size: 13px; cursor: pointer;
      transition: all 0.15s ease;
    }
    .chip:hover { border-color: var(--accent); }
    .chip.active { background: var(--tab-active); border-color: #1d4ed8; color: #fff; }
    .chip:disabled, .chip.disabled { opacity: 0.45; cursor: not-allowed; }
    .leader-toolbar {
      padding: 14px 18px; border-bottom: 1px solid var(--border);
      background: var(--surface2); display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end;
    }
    .leader-toolbar label {
      display: block; font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--muted); margin-bottom: 8px; font-weight: 600;
    }
    .leader-chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .wf-badge {
      display: inline-block; margin-top: 6px; margin-right: 6px;
      font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;
      letter-spacing: 0.02em;
    }
    .wf-manual { background: #ede9fe; color: #5b21b6; }
    .wf-pending_send { background: #fef3c7; color: #92400e; }
    .wf-cancelled { background: #e2e8f0; color: #475569; text-decoration: line-through; }
    .wf-pending_impl { background: #dbeafe; color: #1e40af; }
    .wf-yearly { background: #fce7f3; color: #9d174d; }
    .wf-auto { background: #d1fae5; color: #065f46; }
    tr.row-cancelled td { opacity: 0.55; }
    tr.leader-section td.leader-col {
      background: #e2e8f0; font-weight: 700; color: #334155;
      border-top: 2px solid #94a3b8;
    }
    .btn {
      border: none; border-radius: 8px; padding: 8px 14px; font-size: 13px;
      font-weight: 600; cursor: pointer; background: var(--surface2);
      color: var(--text); border: 1px solid var(--border);
    }
    .btn:hover { border-color: var(--accent); }
    .btn-primary { background: var(--accent-dim); border-color: var(--accent-dim); color: #fff; }
    .btn-muted { opacity: 0.8; }
    .action-col { min-width: 170px; vertical-align: middle; }
    tr.row-selected td { background: rgba(37, 99, 235, 0.08); }
    tr.row-selected .metric-cell { box-shadow: inset 3px 0 0 var(--accent); }
    .tabs { display: flex; gap: 8px; margin-bottom: 0; }
    .tab {
      padding: 12px 20px; border: 1px solid var(--border); border-bottom: none;
      border-radius: var(--radius) var(--radius) 0 0; background: var(--surface2);
      color: var(--muted); cursor: pointer; font-weight: 600; font-size: 14px;
    }
    .tab.active { background: var(--surface); color: var(--text); border-color: var(--border);
      box-shadow: inset 0 2px 0 var(--accent); }
    .panel {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 0 var(--radius) var(--radius) var(--radius);
      padding: 0; overflow: hidden;
    }
    .panel.hidden { display: none; }
    .panel-head {
      padding: 14px 18px; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
    }
    .panel-head h2 { margin: 0; font-size: 16px; }
    .legend { display: flex; gap: 16px; font-size: 12px; color: var(--muted); }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .swatch-miss { width: 14px; height: 14px; border-radius: 3px; background: var(--miss-bg); border: 1px solid var(--miss-border); }
    .swatch-hit { width: 14px; height: 14px; border-radius: 3px; background: var(--hit-bg); border: 1px solid #166534; }
    .src-badge {
      display: inline-block; margin-top: 6px; margin-right: 6px;
      font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;
      text-transform: uppercase; letter-spacing: 0.04em;
    }
    .src-snowflake { background: #d1fae5; color: #065f46; }
    .src-user { background: #dbeafe; color: #1e40af; }
    .src-manual { background: #ede9fe; color: #5b21b6; }
    .src-review { background: #fef3c7; color: #92400e; }
    .src-blocked { background: #fee2e2; color: #991b1b; }
    .table-scroll { overflow-x: auto; overflow-y: auto; max-height: calc(100vh - 200px); }
    table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; min-width: 1100px; }
    th, td { border-bottom: 1px solid var(--border); padding: 12px 10px; text-align: center; vertical-align: top; }
    th { position: sticky; top: 0; background: #e2e8f0; z-index: 2; color: #475569;
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
    th.corner, td.metric-cell {
      text-align: left; position: sticky; left: 196px; background: var(--surface); z-index: 1;
      min-width: 280px; max-width: 360px; width: 280px; line-height: 1.45; white-space: normal;
    }
    th.corner { z-index: 3; left: 196px; }
    th.leader-col, td.leader-col {
      text-align: left; position: sticky; left: 0; background: var(--surface); z-index: 2;
      min-width: 84px; width: 84px; font-size: 12px; vertical-align: top;
    }
    th.partner-col, td.partner-col {
      text-align: left; position: sticky; left: 84px; background: var(--surface); z-index: 2;
      min-width: 112px; width: 112px; font-size: 12px; vertical-align: top;
    }
    th.leader-col { z-index: 4; left: 0; }
    th.partner-col { z-index: 4; left: 72px; }
    .meta-input {
      width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
      color: var(--text); padding: 6px 8px; font-size: 12px;
    }
    .meta-input:focus { outline: none; border-color: var(--accent); }
    .target-val { font-size: 10px; color: var(--muted); margin-top: 6px; line-height: 1.35; }
    .edit-sub { font-size: 11px; color: var(--muted); font-weight: 400; display: block; margin-top: 2px; }
    .manual-row td { background: rgba(237, 233, 254, 0.35); }
    .metric-name { font-weight: 600; color: var(--text); }
    .metric-alias { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.3; }
    .metric-hint { font-size: 10px; color: #64748b; margin-top: 2px; }
    .src-link {
      display: inline-flex; align-items: center; gap: 4px; margin-top: 6px;
      font-size: 11px; color: var(--accent); text-decoration: none; font-weight: 500;
    }
    .src-link:hover { text-decoration: underline; }
    .src-link svg { width: 12px; height: 12px; opacity: 0.85; }
    .perf-cell-wrap {
      display: flex; flex-direction: column; align-items: stretch; gap: 6px; min-width: 96px;
    }
    .cell-actual {
      border-radius: 8px; padding: 10px 8px; min-width: 96px; min-height: 52px;
      background: var(--neutral-bg); border: 1px solid var(--border);
      box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    .cell-actual.has-target { min-height: 56px; }
    .cell-actual.miss {
      background: var(--miss-bg) !important; border: 2px solid var(--miss-border) !important; color: var(--miss-text);
    }
    .cell-actual.hit {
      background: var(--hit-bg) !important; border: 2px solid var(--hit-border) !important; color: var(--hit-text);
    }
    .cell-actual.no-target { border-style: dashed; opacity: 0.92; }
    .actual-val { font-size: 17px; font-weight: 700; line-height: 1.2; }
    .cell-target-mini {
      padding: 6px 8px; border-radius: 8px; text-align: center;
      background: #fffbeb; border: 1.5px solid #f59e0b;
      font-size: 11px; font-weight: 700; color: #92400e; line-height: 1.3;
      box-shadow: 0 1px 2px rgba(146, 64, 14, 0.08);
    }
    .cell-target-mini .lbl {
      display: block; font-size: 9px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.04em; color: #b45309; margin-bottom: 2px;
    }
    .actual-inline-input {
      width: 100%; min-width: 72px; max-width: 110px;
      background: #fff; border: 1px solid var(--border); border-radius: 6px;
      color: var(--text); padding: 8px 10px; font-size: 15px; font-weight: 700;
      text-align: center; font-variant-numeric: tabular-nums;
    }
    .actual-inline-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px rgba(37,99,235,0.2); }
    .target-only-cell { display: flex; align-items: center; justify-content: center; min-height: 52px; }
    .edit-cell-stack { display: flex; flex-direction: column; gap: 8px; align-items: center; min-height: 52px; justify-content: center; }
    .cell-actual.miss .target-val { color: #fca5a5; }
    .delta { font-size: 10px; margin-top: 2px; opacity: 0.9; }
    .no-actual { color: #64748b; font-style: italic; }
    .target-input {
      width: 100%; min-width: 72px; max-width: 110px;
      background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
      color: var(--text); padding: 8px 10px; font-size: 14px; text-align: center;
      font-variant-numeric: tabular-nums;
    }
    .target-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px rgba(37,99,235,0.2); }
    .target-wrap { display: inline-flex; align-items: center; justify-content: center; gap: 2px; width: 100%; }
    .target-wrap.percent .target-input { max-width: 88px; }
    .target-suffix { color: var(--muted); font-size: 13px; font-weight: 600; }
    .save-toast {
      position: fixed; bottom: 20px; right: 20px; background: #ffffff;
      border: 1px solid var(--border); padding: 10px 16px; border-radius: 8px;
      font-size: 13px; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 99;
      box-shadow: 0 4px 12px rgba(15,23,42,0.12);
    }
    .save-toast.show { opacity: 1; }
    .summary-bar {
      display: flex; gap: 20px; flex-wrap: wrap; padding: 12px 18px;
      background: var(--surface2); border-bottom: 1px solid var(--border); font-size: 13px;
    }
    .summary-bar strong { color: var(--accent); }
    .hint-banner {
      margin: 0 0 16px; padding: 12px 16px; border-radius: 10px; font-size: 13px;
      background: #eff6ff; border: 1px solid #93c5fd; color: #1e3a8a;
    }
    .hint-banner.warn { background: #fffbeb; border-color: #fcd34d; color: #92400e; }
    .essi-card {
      background: #ecfdf5; border: 1px solid #86efac; border-radius: var(--radius);
      padding: 16px 18px; margin-bottom: 16px; color: #14532d;
    }
    .essi-card h3 { margin: 0 0 10px; font-size: 14px; color: #166534; }
    .essi-quote {
      margin: 0 0 12px; padding: 12px 14px; background: #f8fafc; border-left: 4px solid #22c55e;
      border-radius: 8px; color: #334155; font-size: 13px; line-height: 1.55;
    }
    .essi-quote p { margin: 0 0 8px; }
    .essi-quote p:last-child { margin-bottom: 0; }
    .essi-sources { width: 100%; font-size: 12px; margin-top: 10px; border-collapse: collapse; }
    .essi-sources th, .essi-sources td { border: 1px solid #166534; padding: 8px 10px; text-align: left; }
    .essi-sources th { background: #dcfce7; color: #166534; }
    .essi-card a { color: #2563eb; }
    .essi-meta { font-size: 12px; color: #166534; margin: 8px 0 0; line-height: 1.5; }
    footer { margin-top: 20px; font-size: 12px; color: var(--muted); line-height: 1.6; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>OKR 2026 — ISR Wolt Market 1P</h1>
      <p class="subtitle">Main KPIs (blue) · KPI by Leader · Jan–Dec 2026 · saved in your browser</p>
    </header>

    <div class="toolbar">
      <div class="toolbar-block">
        <label>Periods</label>
        <div class="period-chips" id="periodChips"></div>
      </div>
      <div class="toolbar-block">
        <label>&nbsp;</label>
        <div style="display:flex;gap:8px;">
          <button type="button" class="btn" id="btnAllPeriods">All</button>
          <button type="button" class="btn" id="btnClearPeriods">Latest only</button>
        </div>
      </div>
    </div>

    <div id="hintBanner" class="hint-banner warn"></div>

    <div class="tabs">
      <button type="button" class="tab active" data-tab="performance">Main KPIs</button>
      <button type="button" class="tab" data-tab="leader">KPI by Leader</button>
      <button type="button" class="tab" data-tab="edit">Target</button>
      <button type="button" class="tab" data-tab="review">לבדיקה</button>
    </div>

    <div class="panel" id="panelPerformance">
      <div class="leader-toolbar">
        <div>
          <label>Filter by Leader</label>
          <div class="leader-chips" id="mainLeaderChips"></div>
        </div>
      </div>
      <div class="panel-head">
        <h2>Main KPIs — Actual vs Target</h2>
        <div class="legend">
          <span><i class="swatch-hit"></i> On target</span>
          <span><i class="swatch-miss"></i> Below target (or above for cost metrics)</span>
        </div>
      </div>
      <div class="table-scroll">
        <table id="performanceTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="panel hidden" id="panelLeader">
      <div class="leader-toolbar">
        <div>
          <label>Filter by Leader</label>
          <div class="leader-chips" id="leaderChips"></div>
        </div>
      </div>
      <div class="panel-head">
        <h2>KPI by Leader</h2>
        <div class="legend">
          <span><i class="swatch-hit"></i> On target</span>
          <span><i class="swatch-miss"></i> Missed</span>
        </div>
      </div>
      <div class="table-scroll">
        <table id="leaderTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="panel hidden" id="panelEdit">
      <div class="panel-head">
        <h2>Target — יעדים בלבד</h2>
        <span style="font-size:12px;color:var(--muted);">הזן יעד לכל חודש · נשמר אוטומטית</span>
      </div>
      <div class="table-scroll">
        <table id="editTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="panel hidden" id="panelReview">
      <div class="panel-head">
        <h2>לבדיקה</h2>
        <span style="font-size:12px;color:var(--muted);">Sold from selection — בחר וריאנט</span>
      </div>
      <div class="hint-banner warn" id="reviewBanner"></div>
      <div class="table-scroll">
        <table id="reviewTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <footer>
      VSL includes Wolt Market DC (ISR country). Sessions in K. Jun OFL may be partial until UE recon closes.
      FTU/Returning: presentation.wolt_market_metrics · Looker WM Metrics explore.
      Essi (21 May 2026): session counts fine to use; double-counting affects users only, not sessions.
      IDQ pending definition review. Open Looker links per metric to verify source.
    </footer>
  </div>

  <div class="save-toast" id="saveToast">Saved</div>

  <script>
    const CFG = __PAYLOAD__;

    let selectedMonths = new Set(CFG.monthKeys);
    let selectedMainLeader = null;
    let selectedLeader = null;
    let targets = {};  /* user overrides only — defaults in CFG.defaultTargets */
    let actualOverrides = {};
    let owners = {};
    let storageOk = true;
    let saveTimer = null;
    let activeTargetInput = null;

    function loadJson(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        if (raw) return JSON.parse(raw);
      } catch (e) { storageOk = false; }
      return fallback;
    }

    function persistJson(key, obj, memKey) {
      try {
        localStorage.setItem(key, JSON.stringify(obj));
        storageOk = true;
      } catch (e) {
        storageOk = false;
        window[memKey] = { ...obj };
      }
    }

    let soldSelectionChoice = loadJson(CFG.storage.soldChoice, null);

    function resolveSoldVariantMetric() {
      if (!soldSelectionChoice || !CFG.soldSelectionVariants[soldSelectionChoice]) return null;
      return CFG.soldSelectionVariants[soldSelectionChoice].metricName;
    }

    function buildMainMetricsList() {
      const base = CFG.mainMetrics || CFG.baseMetrics || CFG.metrics;
      const promoted = CFG.promotedSoldSelectionName;
      if (!resolveSoldVariantMetric()) return base.slice();
      if (base.includes(promoted)) return base.slice();
      const after = CFG.soldSelectionInsertAfter || "KVI & Promo WA%";
      const idx = base.indexOf(after);
      const out = base.slice();
      out.splice(idx >= 0 ? idx + 1 : out.length, 0, promoted);
      return out;
    }

    function buildLeaderMetricsList() {
      const base = (CFG.leaderMetrics || []).slice();
      const promoted = CFG.promotedSoldSelectionName;
      if (!resolveSoldVariantMetric()) return base;
      if (base.includes(promoted)) return base;
      const after = CFG.soldSelectionInsertAfterLeader || "Area Product Selection";
      const idx = base.indexOf(after);
      const out = base.slice();
      out.splice(idx >= 0 ? idx + 1 : out.length, 0, promoted);
      return out;
    }

    function buildEditMetricsList() {
      const main = buildMainMetricsList();
      const leader = buildLeaderMetricsList();
      const review = CFG.reviewMetrics || [];
      const seen = new Set();
      const out = [];
      [...main, ...leader, ...review].forEach(m => {
        if (!seen.has(m)) { seen.add(m); out.push(m); }
      });
      return out;
    }

    let mainMetricsList = buildMainMetricsList();
    let leaderMetricsList = buildLeaderMetricsList();
    let editMetricsList = buildEditMetricsList();

    function refreshMetricsLists() {
      mainMetricsList = buildMainMetricsList();
      leaderMetricsList = buildLeaderMetricsList();
      editMetricsList = buildEditMetricsList();
    }

    function remapMetricKey(metric) {
      if (metric === CFG.promotedSoldSelectionName) {
        const vm = resolveSoldVariantMetric();
        if (vm) return vm;
      }
      return metric;
    }

    function setSoldSelectionChoice(key) {
      soldSelectionChoice = key;
      try {
        localStorage.setItem(CFG.storage.soldChoice, JSON.stringify(key));
        storageOk = true;
      } catch (e) {
        storageOk = false;
        window.__okrSoldChoiceMem = key;
      }
      refreshMetricsLists();
      renderMainLeaderChips();
      renderPerformance();
      renderLeader();
      renderEdit();
      renderReview();
      updateHintBanner();
      const toast = document.getElementById("saveToast");
      const label = CFG.soldSelectionVariants[key]?.lookerField || key;
      toast.textContent = `נבחר: ${label} — מוצג ב-Main KPIs וב-KPI by Leader`;
      toast.classList.add("show");
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => toast.classList.remove("show"), 2800);
    }

    function clearSoldSelectionChoice() {
      soldSelectionChoice = null;
      try { localStorage.removeItem(CFG.storage.soldChoice); } catch (e) { storageOk = false; }
      refreshMetricsLists();
      renderMainLeaderChips();
      renderPerformance();
      renderLeader();
      renderEdit();
      renderReview();
      updateHintBanner();
    }

    targets = loadJson(CFG.storage.targets, {});
    actualOverrides = loadJson(CFG.storage.actuals, {});
    owners = loadJson(CFG.storage.owners, {});

    function saveAll(label, refreshViews) {
      if (refreshViews === undefined) refreshViews = true;
      persistJson(CFG.storage.targets, targets, "__okrTargetsMem");
      persistJson(CFG.storage.actuals, actualOverrides, "__okrActualsMem");
      persistJson(CFG.storage.owners, owners, "__okrOwnersMem");
      const toast = document.getElementById("saveToast");
      toast.textContent = storageOk ? (label || "Saved") : (label || "Saved") + " (session only)";
      toast.classList.add("show");
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => toast.classList.remove("show"), 2000);
      if (refreshViews) {
        renderPerformance();
        renderLeader();
        updateHintBanner();
      }
    }

    function persistDraft() {
      persistJson(CFG.storage.targets, targets, "__okrTargetsMem");
      persistJson(CFG.storage.actuals, actualOverrides, "__okrActualsMem");
      persistJson(CFG.storage.owners, owners, "__okrOwnersMem");
    }

    function saveTargets(finalize) { saveAll("Targets saved", !!finalize); }
    function saveActuals(finalize) { saveAll("Actuals saved", !!finalize); }
    function saveOwners() { saveAll("Leader / Partner saved", true); }

    function metricByIdx(list, idx) { return list[idx]; }

    function leaderRank(leader) {
      const order = CFG.leaderOrder || [];
      const i = order.indexOf(leader);
      return i >= 0 ? i : 999;
    }

    function leaderMatchesFilter(metric, filterLeader) {
      if (!filterLeader) return true;
      const ownerLeader = getOwner(metric).leader;
      const groups = CFG.leaderFilterGroups || {};
      const aliases = groups[filterLeader] || [filterLeader];
      return aliases.includes(ownerLeader);
    }

    function allLeaderViewMetrics() {
      const seen = new Set();
      const out = [];
      [...mainMetricsList, ...leaderMetricsList].forEach(m => {
        if (!seen.has(m)) { seen.add(m); out.push(m); }
      });
      return out;
    }

    function filteredMainMetrics() {
      let list = mainMetricsList.slice();
      if (selectedMainLeader) {
        list = list.filter(m => leaderMatchesFilter(m, selectedMainLeader));
      }
      return list;
    }

    function filteredLeaderMetrics() {
      let list = allLeaderViewMetrics().slice();
      list.sort((a, b) => {
        const la = getOwner(a).leader;
        const lb = getOwner(b).leader;
        const ra = leaderRank(groupsMatchRank(la));
        const rb = leaderRank(groupsMatchRank(lb));
        if (ra !== rb) return ra - rb;
        const ia = OKR_INDEX(a);
        const ib = OKR_INDEX(b);
        return ia - ib;
      });
      if (selectedLeader) {
        list = list.filter(m => leaderMatchesFilter(m, selectedLeader));
      }
      return list;
    }

    function groupsMatchRank(leader) {
      const groups = CFG.leaderFilterGroups || {};
      for (const [chip, aliases] of Object.entries(groups)) {
        if (aliases.includes(leader)) return chip;
      }
      return leader;
    }

    const OKR_INDEX = (() => {
      const order = CFG.baseMetrics || CFG.metrics || [];
      const idx = {};
      order.forEach((m, i) => { idx[m] = i; });
      (CFG.mainMetrics || []).forEach((m, i) => { if (idx[m] === undefined) idx[m] = i; });
      (CFG.leaderMetrics || []).forEach((m, i) => { if (idx[m] === undefined) idx[m] = 100 + i; });
      return (m) => idx[m] !== undefined ? idx[m] : 999;
    })();

    function workflowBadge(metric) {
      const wf = (CFG.metricWorkflow || {})[metric] || "auto";
      const map = {
        manual: ["Manual", "wf-manual"],
        pending_send: ["אשלח אליך", "wf-pending_send"],
        cancelled: ["Cancelled", "wf-cancelled"],
        pending_impl: ["בהמשך", "wf-pending_impl"],
        yearly: ["Yearly", "wf-yearly"],
        auto: ["", ""],
      };
      const [label, cls] = map[wf] || ["", ""];
      if (!label) return "";
      return `<span class="wf-badge ${cls}">${label}</span>`;
    }

    function isWorkflowManual(metric) {
      const wf = (CFG.metricWorkflow || {})[metric] || "auto";
      return wf === "manual" || wf === "pending_send" || wf === "yearly";
    }

    function escHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function escAttr(s) { return escHtml(s); }

    function roundTarget(n) { return Math.round(n * 100) / 100; }

    function metricFormat(metric) {
      const key = remapMetricKey(metric);
      return CFG.format[key] || CFG.format[metric] || "decimal:1";
    }

    function isPercentMetric(metric) { return metricFormat(metric).startsWith("percent"); }

    function actualDecimals(metric) {
      const spec = metricFormat(metric);
      if (spec.startsWith("percent:")) return parseInt(spec.split(":")[1], 10) || 1;
      if (spec.startsWith("decimal:")) return parseInt(spec.split(":")[1], 10) || 1;
      return 0;
    }

    function formatDisplay(metric, value, forTarget) {
      if (value === null || value === undefined) return "—";
      const n = Number(value);
      if (!Number.isFinite(n)) return "—";
      const spec = metricFormat(metric);
      if (spec.startsWith("percent")) {
        const d = forTarget ? 2 : (parseInt(spec.split(":")[1], 10) || 1);
        return n.toFixed(d) + "%";
      }
      if (spec === "integer") return String(Math.round(n));
      const d = forTarget ? 2 : (parseInt(spec.split(":")[1], 10) || 1);
      return n.toFixed(d);
    }

    function formatTargetDisplay(metric, val) {
      if (val === undefined || val === null || val === "") return "";
      const n = Number(val);
      if (!Number.isFinite(n)) return "";
      const spec = metricFormat(metric);
      if (spec === "integer") return String(Math.round(n));
      return n.toFixed(2);
    }

    function targetPlaceholder(metric) {
      if (isPercentMetric(metric)) return "0.00";
      if (metricFormat(metric) === "integer") return "0";
      return "0.00";
    }

    function parseTargetRaw(raw) {
      const s = String(raw).trim().replace(",", ".").replace(/^\+/, "");
      if (s === "" || s === "-" || s === "." || s === "-.") return null;
      const n = Number(s);
      return Number.isFinite(n) ? roundTarget(n) : null;
    }

    function normalizeTargetValue(metric, n) {
      if (metric === "Shrink/DDE FEE") return roundTarget(Math.abs(n));
      return roundTarget(n);
    }

    function targetUsesPlusSign(metric) {
      return metric === "PPM%" || metric === "Shrink/DDE FEE";
    }

    function formatTargetInput(metric, val) {
      if (val === undefined || val === null || val === "") return "";
      let n = Number(val);
      if (!Number.isFinite(n)) return "";
      if (metric === "Shrink/DDE FEE") n = Math.abs(n);
      const spec = metricFormat(metric);
      if (spec === "integer") return String(Math.round(n));
      const s = n.toFixed(2);
      return targetUsesPlusSign(metric) ? "+" + s : s;
    }

    function countTargets() {
      let n = 0;
      const metrics = editMetricsList.length
        ? editMetricsList
        : [...(CFG.mainMetrics || []), ...(CFG.leaderMetrics || [])];
      metrics.forEach(metric => {
        CFG.monthKeys.forEach(monthKey => {
          if (getTarget(metric, monthKey) !== null) n++;
        });
      });
      return n;
    }

    function getDefaultTarget(metric, monthKey) {
      const d = (CFG.defaultTargets || {})[cellKey(metric, monthKey)];
      if (d === undefined || d === null || d === "") return null;
      return Number(d);
    }

    function updateHintBanner() {
      const el = document.getElementById("hintBanner");
      const n = countTargets();
      if (n === 0) {
        el.className = "hint-banner warn";
        el.innerHTML = "<strong>אין יעדים.</strong> לך ל-<strong>Target</strong> להזין יעדים — או לטעון מחדש אם מחקת overrides.";
      } else {
        el.className = "hint-banner";
        let soldNote = "";
        if (soldSelectionChoice && CFG.soldSelectionVariants[soldSelectionChoice]) {
          soldNote = ` · <strong>Sold from selection</strong>: ${escHtml(CFG.soldSelectionVariants[soldSelectionChoice].lookerField)}`;
        }
        const srcNote = (CFG.defaultTargets && Object.keys(CFG.defaultTargets).length)
          ? " · יעדים מגיליון OKR (ניתן לעריכה ב-Target)"
          : "";
        el.innerHTML = `<strong>${n} target(s).</strong> ירוק = עמד ביעד · אדום = פספס · יעד מתחת לביצוע.${srcNote}${soldNote}`;
      }
    }

    function cellKey(metric, monthKey) { return metric + "|" + monthKey; }

    function getOwner(metric) {
      const key = remapMetricKey(metric);
      const d = CFG.defaultOwners[key] || CFG.defaultOwners[metric] || { leader: "", partner: "" };
      const o = owners[metric] || owners[key] || {};
      return {
        leader: o.leader !== undefined ? o.leader : d.leader,
        partner: o.partner !== undefined ? o.partner : d.partner,
      };
    }

    function setOwner(idx, field, value) {
      const metric = metricByIdx(editMetricsList, idx);
      if (!owners[metric]) owners[metric] = {};
      owners[metric][field] = value;
      saveOwners();
    }

    function getSnowflakeActual(metric, idx) {
      const key = remapMetricKey(metric);
      const row = CFG.actuals[key];
      if (!row || row[idx] === null || row[idx] === undefined) return null;
      return Number(row[idx]);
    }

    function getActual(metric, idx) {
      const monthKey = CFG.monthKeys[idx];
      const k = cellKey(metric, monthKey);
      if (actualOverrides[k] !== undefined && actualOverrides[k] !== null && actualOverrides[k] !== "")
        return Number(actualOverrides[k]);
      return getSnowflakeActual(metric, idx);
    }

    function getActualOverride(metric, monthKey) {
      const k = cellKey(metric, monthKey);
      return actualOverrides[k];
    }

    function setActualIdx(idx, monthKey, raw, finalize) {
      const metric = metricByIdx(editMetricsList, idx);
      const k = cellKey(metric, monthKey);
      const trimmed = String(raw).trim();
      if (trimmed === "") { delete actualOverrides[k]; }
      else {
        const n = parseTargetRaw(trimmed);
        if (n === null) { if (!finalize) return; return; }
        actualOverrides[k] = n;
      }
      if (finalize) saveActuals(true);
      else persistDraft();
    }

    function finalizeActualInput(inp) {
      const idx = Number(inp.dataset.idx);
      const metric = metricByIdx(editMetricsList, idx);
      const n = parseTargetRaw(inp.value);
      if (n !== null) inp.value = formatTargetDisplay(metric, n);
      setActualIdx(idx, inp.dataset.month, inp.value, true);
    }

    function isManualMetric(metric) {
      if (isWorkflowManual(metric)) return true;
      const ds = CFG.dataSource[metric];
      return ds === "manual" || ds === "user";
    }

    function getTarget(metric, monthKey) {
      const k = cellKey(metric, monthKey);
      if (Object.prototype.hasOwnProperty.call(targets, k)) {
        const v = targets[k];
        if (v === null || v === "") return null;
        return Number(v);
      }
      return getDefaultTarget(metric, monthKey);
    }

    function setTargetIdx(idx, monthKey, raw, finalize) {
      const metric = metricByIdx(editMetricsList, idx);
      const k = cellKey(metric, monthKey);
      const trimmed = String(raw).trim();
      if (trimmed === "") {
        if (getDefaultTarget(metric, monthKey) !== null) targets[k] = null;
        else delete targets[k];
      } else {
        const n = parseTargetRaw(trimmed);
        if (n === null) { if (!finalize) return; return; }
        targets[k] = normalizeTargetValue(metric, n);
      }
      if (finalize) saveTargets(true);
      else persistDraft();
    }

    function finalizeTargetInput(inp) {
      const idx = Number(inp.dataset.idx);
      const metric = metricByIdx(editMetricsList, idx);
      const n = parseTargetRaw(inp.value);
      if (n !== null) inp.value = formatTargetInput(metric, normalizeTargetValue(metric, n));
      setTargetIdx(idx, inp.dataset.month, inp.value, true);
    }

    function direction(metric) { return CFG.direction[metric] || "higher"; }

    function meetsTarget(actual, target, metric) {
      if (actual === null || target === null) return null;
      const dir = direction(metric);
      const eps = 0.004;
      if (dir === "lower") return actual <= target + eps;
      return actual >= target - eps;
    }

    function formatTargetValue(metric, value) {
      return formatDisplay(metric, value, true);
    }

    function formatValue(metric, value) {
      return formatDisplay(metric, value, false);
    }

    function monthIndex(monthKey) { return CFG.monthKeys.indexOf(monthKey); }

    function linkIcon() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
    }

    function sourceBadge(metric) {
      const kind = CFG.sources[metric] || "manual_entry";
      const map = {
        snowflake_validated: ["Snowflake", "src-snowflake"],
        user_provided: ["User", "src-user"],
        manual_entry: ["Manual", "src-manual"],
        pending_review: ["Review", "src-review"],
        for_review: ["לבדיקה", "src-review"],
        looker_not_approved: ["לבדיקה", "src-review"],
      };
      const [label, cls] = map[kind] || ["Manual", "src-manual"];
      return `<span class="src-badge ${cls}">${label}</span>`;
    }

    function ownerCellHtml(idx, field) {
      const metric = metricByIdx(editMetricsList, idx);
      const val = escAttr(getOwner(metric)[field] || "");
      return `<input type="text" class="meta-input owner-input" data-idx="${idx}" data-field="${field}" value="${val}" placeholder="—"/>`;
    }

    function valueInputHtml(idx, monthKey, kind, shown) {
      const metric = metricByIdx(editMetricsList, idx);
      const ph = targetPlaceholder(metric);
      const cls = kind === "actual" ? "actual-input" : "target-input";
      const inp = `<input type="text" inputmode="decimal" class="${cls} value-input" data-kind="${kind}" data-idx="${idx}" data-month="${monthKey}" value="${escAttr(shown)}" placeholder="${ph}"/>`;
      if (isPercentMetric(metric)) {
        return `<span class="target-wrap percent">${inp}<span class="target-suffix">%</span></span>`;
      }
      return inp;
    }

    function promotedMetricCellHtml() {
      const variant = CFG.soldSelectionVariants[soldSelectionChoice];
      const metric = CFG.promotedSoldSelectionName;
      const lk = CFG.looker[variant.metricName] || {};
      let link = "";
      if (lk.url) {
        link = `<a class="src-link" href="${escAttr(lk.url)}" target="_blank" rel="noopener">${linkIcon()} ${escHtml(lk.label || "Source")}</a>`;
      }
      return `<div class="metric-name">${escHtml(metric)}</div>` + link;
    }

    function editMetricCellHtml(metric) {
      return `<div class="metric-name">${escHtml(metric)}</div>`;
    }

    function metricCellHtml(metric) {
      if (metric === CFG.promotedSoldSelectionName && soldSelectionChoice) {
        return promotedMetricCellHtml();
      }
      const lk = CFG.looker[metric] || {};
      let link = "";
      if (lk.url) {
        link = `<a class="src-link" href="${escAttr(lk.url)}" target="_blank" rel="noopener">${linkIcon()} ${escHtml(lk.label || "Source")}</a>`;
      }
      return `<div class="metric-name">${escHtml(metric)}</div>` + link;
    }

    function renderEssiCard() {
      const el = document.getElementById("essiSessionCard");
      const e = CFG.essiSession;
      if (!el || !e) return;
      const paras = (e.quote || "").split("\n\n").map(p => `<p>${escHtml(p)}</p>`).join("");
      el.innerHTML = `<h3>${escHtml(e.meta || "Essi")}</h3>`
        + `<blockquote class="essi-quote">${paras}</blockquote>`
        + `<p class="essi-meta"><a href="${escAttr(e.slackUrl)}" target="_blank" rel="noopener">פתיחת ההודעה ב-Slack</a>`
        + ` · thread על NV session conversion</p>`
        + `<table class="essi-sources"><thead><tr><th>מקור Looker</th><th>סטטוס</th><th>קישור</th></tr></thead><tbody>`
        + `<tr><td><code>wolt_market_data/wolt_market_venue_conversion</code></td>`
        + `<td>Essi ✅ — סשנים + CVR</td>`
        + `<td><a href="${escAttr(e.venueConversionUrl)}" target="_blank" rel="noopener">Venue Conversion</a></td></tr>`
        + `<tr><td><code>kpi_data/wolt_market_metrics</code></td>`
        + `<td>deprecated</td>`
        + `<td><a href="${escAttr(e.kpiDeprecatedUrl)}" target="_blank" rel="noopener">WM Metrics (ישן)</a></td></tr>`
        + `</tbody></table>`
        + `<p class="essi-meta"><strong>למה בלבדיקה?</strong> ${escHtml(e.svenjaNote || "")}</p>`
        + `<p class="essi-meta">${escHtml(e.noteHe || "")}</p>`;
    }

    function renderMaintenanceCard() {
      const el = document.getElementById("maintenanceReviewCard");
      const m = CFG.maintenanceReview;
      if (!el || !m) return;
      const months = CFG.monthLabels || [];
      const ns = m.netsuiteKils || [];
      const ibm = m.ibmKils || [];
      const rows = months.map((label, i) => {
        const nsVal = ns[i];
        const ibmVal = ibm[i];
        let gap = "—";
        if (nsVal !== null && nsVal !== undefined && ibmVal !== null && ibmVal !== undefined) {
          const d = nsVal - ibmVal;
          gap = (d > 0 ? "+" : "") + Math.round(d);
        }
        return `<tr><td>${escHtml(label)}</td><td>${nsVal == null ? "—" : nsVal}</td><td>${ibmVal == null ? "—" : ibmVal}</td><td>${gap}</td></tr>`;
      }).join("");
      el.innerHTML = `<h3 style="color:#92400e;">${escHtml(m.title || "Maintenance costs")}</h3>`
        + `<p class="essi-meta">${escHtml(CFG.maintenanceReviewNote || m.noteHe || "")}</p>`
        + `<p class="essi-meta"><strong>NetSuite:</strong> <code>${escHtml(m.netsuiteAccount || "87310")}</code> · `
        + `<strong>מאי 2026:</strong> NetSuite ${m.may2026Netsuite} kILS vs IBM ${m.may2026Ibm} kILS · `
        + `פער ≈ ${m.may2026Gap} kILS</p>`
        + `<table class="essi-sources"><thead><tr><th>חודש</th><th>NetSuite 87310</th><th>IBM fallback</th><th>Gap</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    function renderReview() {
      const banner = document.getElementById("reviewBanner");
      if (banner) {
        banner.innerHTML = (CFG.soldSelectionReviewNote
            ? `<strong>Sold from selection:</strong> ${CFG.soldSelectionReviewNote} `
            : "")
          + " <strong>Looker Purchases:</strong> רק wolt_market_exploration (V ✅) — לא wolt_market_data.";
      }
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const thead = document.querySelector("#reviewTable thead");
      const tbody = document.querySelector("#reviewTable tbody");
      if (!thead || !tbody) return;
      thead.innerHTML = "<tr><th class='leader-col'>Leader</th><th class='partner-col'>Partner</th><th class='corner'>Metric</th>"
        + months.map(k => {
          const i = monthIndex(k);
          return `<th>${CFG.monthLabels[i]}<br><span style="font-weight:400;text-transform:none">Snowflake / Looker ref</span></th>`;
        }).join("") + "<th class='action-col'>Action</th></tr>";
      const metrics = CFG.reviewMetrics || [];
      tbody.innerHTML = metrics.map(metric => {
        const o = getOwner(metric);
        const variantKey = Object.keys(CFG.soldSelectionVariants || {}).find(
          k => CFG.soldSelectionVariants[k].metricName === metric
        );
        const isChosen = variantKey && soldSelectionChoice === variantKey;
        const cells = months.map(monthKey => {
          const idx = monthIndex(monthKey);
          const actual = getActual(metric, idx);
          const lkRef = (CFG.lookerRef && CFG.lookerRef[metric]) ? CFG.lookerRef[metric][idx] : null;
          let gap = "";
          if (lkRef !== null && lkRef !== undefined && actual !== null) {
            const d = actual - lkRef;
            let deltaTxt = formatDisplay(metric, d, false);
            if (d > 0) deltaTxt = "+" + deltaTxt;
            const refLabel = metric === "Maintenance costs" ? "NetSuite" : "Looker";
            gap = `<div class="delta">Δ ${refLabel} ${deltaTxt}</div>`;
          }
          const lkLine = (lkRef !== null && lkRef !== undefined)
            ? `<div class="target-val">${metric === "Maintenance costs" ? "NetSuite 87310" : "Looker"}: ${formatValue(metric, lkRef)}</div>`
            : "";
          return `<td><div class="cell-actual no-target"><div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div>${lkLine}${gap}</div></td>`;
        }).join("");
        let action = "";
        if (variantKey) {
          if (isChosen) {
            action = `<button type="button" class="btn btn-muted" data-sold-clear="1">בטל בחירה</button>`
              + `<div class="metric-hint" style="color:#4ade80;margin-top:8px">✓ Main KPIs + KPI by Leader</div>`;
          } else {
            action = `<button type="button" class="btn btn-primary" data-sold-choice="${escAttr(variantKey)}">השתמש בדשבורד</button>`;
          }
        }
        const rowCls = isChosen ? " class='row-selected'" : "";
        return `<tr${rowCls}><td class="leader-col">${o.leader || "—"}</td><td class="partner-col">${o.partner || "—"}</td><td class="metric-cell">${metricCellHtml(metric)}</td>${cells}<td class="action-col">${action}</td></tr>`;
      }).join("");
      tbody.querySelectorAll("[data-sold-choice]").forEach(btn => {
        btn.addEventListener("click", () => setSoldSelectionChoice(btn.dataset.soldChoice));
      });
      tbody.querySelectorAll("[data-sold-clear]").forEach(btn => {
        btn.addEventListener("click", () => clearSoldSelectionChoice());
      });
    }

    function actualInlineInputHtml(metric, mIdx, monthKey, shown) {
      const ph = targetPlaceholder(metric);
      return `<input type="text" inputmode="decimal" class="actual-inline-input value-input" data-kind="actual" data-idx="${mIdx}" data-month="${monthKey}" value="${escAttr(shown)}" placeholder="${ph}"/>`;
    }

    function bindPerformanceActualInputs(root) {
      root.querySelectorAll(".actual-inline-input").forEach(inp => bindValueInput(inp));
    }

    function renderPeriodChips() {
      const el = document.getElementById("periodChips");
      el.innerHTML = CFG.monthKeys.map((k, i) => {
        const active = selectedMonths.has(k) ? " active" : "";
        return `<button type="button" class="chip${active}" data-month="${k}">${CFG.monthLabels[i]}</button>`;
      }).join("");
      el.querySelectorAll(".chip").forEach(chip => {
        chip.addEventListener("click", () => {
          const k = chip.dataset.month;
          if (selectedMonths.has(k)) {
            if (selectedMonths.size > 1) selectedMonths.delete(k);
          } else selectedMonths.add(k);
          renderPeriodChips();
          renderPerformance();
          renderLeader();
          renderEdit();
          renderReview();
        });
      });
    }

    function renderMetricRows(metrics, tableRootId) {
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const metricIdxMap = {};
      editMetricsList.forEach((m, i) => { metricIdxMap[m] = i; });
      return metrics.map(metric => {
        const o = getOwner(metric);
        const wf = (CFG.metricWorkflow || {})[metric] || "auto";
        const mIdx = metricIdxMap[metric];
        const manual = isManualMetric(metric);
        const cells = months.map(monthKey => {
          const idx = monthIndex(monthKey);
          const actual = getActual(metric, idx);
          const target = getTarget(metric, monthKey);
          const override = getActualOverride(metric, monthKey);
          const snow = getSnowflakeActual(metric, idx);
          const actualShown = override !== undefined
            ? formatTargetDisplay(metric, override)
            : (snow !== null ? formatTargetDisplay(metric, snow) : "");

          if (actual === null && !manual) {
            return `<td><div class="cell-actual no-actual">—</div></td>`;
          }

          const met = meetsTarget(actual, target, metric);
          let cls = "cell-actual";
          if (target === null) cls += " no-target";
          else { cls += met ? " hit" : " miss"; cls += " has-target"; }

          let actualHtml = "";
          if (manual && mIdx !== undefined) {
            actualHtml = actualInlineInputHtml(metric, mIdx, monthKey, actualShown);
          } else {
            actualHtml = `<div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div>`;
          }

          let targetHtml = "";
          if (target !== null) {
            targetHtml = `<div class="cell-target-mini"><span class="lbl">יעד</span>${formatTargetValue(metric, target)}</div>`;
          }

          let delta = "";
          if (target !== null && actual !== null) {
            const d = actual - target;
            let deltaTxt = formatDisplay(metric, d, false);
            if (d > 0) deltaTxt = "+" + deltaTxt;
            delta = `<div class="delta">${deltaTxt} vs יעד</div>`;
          }

          return `<td><div class="perf-cell-wrap"><div class="${cls}">${actualHtml}${delta}</div>${targetHtml}</div></td>`;
        }).join("");
        let rowCls = manual ? "manual-row" : "";
        if (wf === "cancelled") rowCls = (rowCls ? rowCls + " " : "") + "row-cancelled";
        const rowClsAttr = rowCls ? ` class="${rowCls}"` : "";
        return `<tr${rowClsAttr} data-metric="${escAttr(metric)}"><td class="leader-col">${o.leader || "—"}</td><td class="partner-col">${o.partner || "—"}</td><td class="metric-cell">${metricCellHtml(metric)}</td>${cells}</tr>`;
      }).join("");
    }

    function renderPerformanceTableHead(tableId) {
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const thead = document.querySelector(`#${tableId} thead`);
      if (!thead) return;
      thead.innerHTML = "<tr><th class='leader-col'>Leader</th><th class='partner-col'>Partner</th><th class='corner'>Metric</th>"
        + months.map(k => {
          const i = monthIndex(k);
          return `<th>${CFG.monthLabels[i]}<br><span style="font-weight:400;text-transform:none">ביצוע</span></th>`;
        }).join("") + "</tr>";
    }

    function renderMainLeaderChips() {
      const el = document.getElementById("mainLeaderChips");
      if (!el) return;
      const leaders = CFG.leaderOrder || [];
      const all = mainMetricsList;
      let html = `<button type="button" class="chip${selectedMainLeader === null ? " active" : ""}" data-main-leader="">All (${all.length})</button>`;
      html += leaders.map(l => {
        const count = all.filter(m => leaderMatchesFilter(m, l)).length;
        const active = selectedMainLeader === l ? " active" : "";
        return `<button type="button" class="chip${active}${count === 0 ? " disabled" : ""}" data-main-leader="${escAttr(l)}"${count === 0 ? " disabled" : ""}>${escHtml(l)} (${count})</button>`;
      }).join("");
      el.innerHTML = html;
      el.querySelectorAll(".chip:not([disabled])").forEach(chip => {
        chip.addEventListener("click", () => {
          const v = chip.dataset.mainLeader;
          selectedMainLeader = v || null;
          renderMainLeaderChips();
          renderPerformance();
        });
      });
    }

    function renderLeaderChips() {
      const el = document.getElementById("leaderChips");
      if (!el) return;
      const leaders = CFG.leaderOrder || [];
      const all = allLeaderViewMetrics();
      let html = `<button type="button" class="chip${selectedLeader === null ? " active" : ""}" data-leader="">All (${all.length})</button>`;
      html += leaders.map(l => {
        const count = all.filter(m => leaderMatchesFilter(m, l)).length;
        const active = selectedLeader === l ? " active" : "";
        const disabled = count === 0 ? " disabled" : "";
        return `<button type="button" class="chip${active}${disabled}" data-leader="${escAttr(l)}"${count === 0 ? " disabled" : ""}>${escHtml(l)} (${count})</button>`;
      }).join("");
      el.innerHTML = html;
      el.querySelectorAll(".chip:not([disabled])").forEach(chip => {
        chip.addEventListener("click", () => {
          const v = chip.dataset.leader;
          selectedLeader = v || null;
          renderLeaderChips();
          renderLeader();
        });
      });
    }

    function renderLeader() {
      renderPerformanceTableHead("leaderTable");
      const tbody = document.querySelector("#leaderTable tbody");
      if (!tbody) return;
      tbody.innerHTML = renderMetricRows(filteredLeaderMetrics(), "leaderTable");
      bindPerformanceActualInputs(tbody);
    }

    function renderPerformance() {
      renderPerformanceTableHead("performanceTable");
      const tbody = document.querySelector("#performanceTable tbody");
      tbody.innerHTML = renderMetricRows(filteredMainMetrics(), "performanceTable");
      bindPerformanceActualInputs(tbody);
    }

    function bindValueInput(inp) {
      let debounce = null;
      inp.addEventListener("focus", () => { activeTargetInput = inp; });
      inp.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => {
          const idx = Number(inp.dataset.idx);
          if (inp.dataset.kind === "actual") setActualIdx(idx, inp.dataset.month, inp.value, false);
          else setTargetIdx(idx, inp.dataset.month, inp.value, false);
        }, 400);
      });
      inp.addEventListener("blur", () => {
        activeTargetInput = null;
        if (inp.dataset.kind === "actual") finalizeActualInput(inp);
        else finalizeTargetInput(inp);
      });
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
      });
    }

    function renderEdit() {
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const thead = document.querySelector("#editTable thead");
      const tbody = document.querySelector("#editTable tbody");
      const focused = activeTargetInput
        ? { idx: activeTargetInput.dataset.idx, month: activeTargetInput.dataset.month, kind: activeTargetInput.dataset.kind }
        : null;

      thead.innerHTML = "<tr><th class='leader-col'>Leader</th><th class='partner-col'>Partner</th><th class='corner'>Metric</th>"
        + months.map(k => {
          const lbl = CFG.monthLabels[monthIndex(k)];
          return `<th>${lbl}<span class="edit-sub">יעד</span></th>`;
        }).join("") + "</tr>";

      tbody.innerHTML = editMetricsList.map((metric, mIdx) => {
        const rowCls = isManualMetric(metric) ? "manual-row" : "";
        const cells = months.map(monthKey => {
          const tgt = getTarget(metric, monthKey);
          const tgtShown = tgt === null ? "" : formatTargetInput(metric, tgt);
          return `<td><div class="target-only-cell">`
            + valueInputHtml(mIdx, monthKey, "target", tgtShown)
            + `</div></td>`;
        }).join("");
        return `<tr class="${rowCls}"><td class="leader-col">${ownerCellHtml(mIdx, "leader")}</td>`
          + `<td class="partner-col">${ownerCellHtml(mIdx, "partner")}</td>`
          + `<td class="metric-cell">${editMetricCellHtml(metric)}</td>${cells}</tr>`;
      }).join("");

      tbody.querySelectorAll(".value-input").forEach(inp => {
        bindValueInput(inp);
        if (focused && inp.dataset.idx === focused.idx && inp.dataset.month === focused.month && inp.dataset.kind === focused.kind) {
          inp.focus();
          const len = inp.value.length;
          inp.setSelectionRange(len, len);
        }
      });
      tbody.querySelectorAll(".owner-input").forEach(inp => {
        inp.addEventListener("input", () => {
          const metric = metricByIdx(editMetricsList, Number(inp.dataset.idx));
          if (!owners[metric]) owners[metric] = {};
          owners[metric][inp.dataset.field] = inp.value;
          persistDraft();
        });
        inp.addEventListener("blur", () => setOwner(Number(inp.dataset.idx), inp.dataset.field, inp.value.trim()));
      });
    }

    document.querySelectorAll(".tab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const id = tab.dataset.tab;
        document.getElementById("panelPerformance").classList.toggle("hidden", id !== "performance");
        document.getElementById("panelLeader").classList.toggle("hidden", id !== "leader");
        document.getElementById("panelEdit").classList.toggle("hidden", id !== "edit");
        document.getElementById("panelReview").classList.toggle("hidden", id !== "review");
        if (id === "performance") { renderMainLeaderChips(); renderPerformance(); }
        if (id === "leader") { renderLeaderChips(); renderLeader(); }
        if (id === "edit") renderEdit();
        if (id === "review") renderReview();
      });
    });

    document.getElementById("btnAllPeriods").addEventListener("click", () => {
      selectedMonths = new Set(CFG.monthKeys);
      renderPeriodChips(); renderMainLeaderChips(); renderPerformance(); renderLeader(); renderEdit(); renderReview();
    });
    document.getElementById("btnClearPeriods").addEventListener("click", () => {
      selectedMonths = new Set([CFG.monthKeys[CFG.monthKeys.length - 1]]);
      renderPeriodChips(); renderMainLeaderChips(); renderPerformance(); renderLeader(); renderEdit(); renderReview();
    });

    renderPeriodChips();
    renderMainLeaderChips();
    renderLeaderChips();
    renderPerformance();
    renderLeader();
    renderEdit();
    renderReview();
    updateHintBanner();
  </script>
</body>
</html>
"""


def build_html(payload: dict) -> str:
    return HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    if args.skip_fetch:
        actuals = _load_cached_metrics()
        if actuals is None:
            raise SystemExit("No cached metrics — run okr_2026_validation.py first.")
    else:
        actuals, _ofl_check, _vp_check, _shrink_check, _maint = fetch_metrics()

    payload = _build_payload(actuals)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(build_html(payload), encoding="utf-8")
    print("Wrote", OUT_HTML.name)


if __name__ == "__main__":
    main()
