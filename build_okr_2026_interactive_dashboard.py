"""Build interactive OKR 2026 dashboard — Actual vs Target with period filter.

Sheet 1: Actual values compared to targets (red when target missed).
Sheet 2: Editable targets (auto-saved in browser localStorage).
Sheet 3: For review (Snowflake + Looker comparison).

Usage:
  python build_okr_2026_interactive_dashboard.py
  python build_okr_2026_interactive_dashboard.py --skip-fetch
"""
from __future__ import annotations

import argparse
import base64
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
from okr_2026_dashboard import _load_cached_metrics
from okr_2026_validation import (
    APPROVED_LOOKER_EXPLORES,
    LOOKER,
    LOOKER_EXPLORE_NOT_CERTIFIED,
    LOOKER_FIELD_ALIASES,
    LOOKER_LINKS,
    MAINTENANCE_REVIEW_PAYLOAD,
    METRIC_SOURCE,
    NETSUITE_87310_KILS,
    CLIENT_GROWTH_REVIEW_METRICS,
    REVIEW_TAB_METRICS,
    SOLD_FROM_SELECTION_PROMOTED_NAME,
    SOLD_FROM_SELECTION_VARIANTS,
    TO_DELETE_TAB_METRICS,
    USER_VERIFIED,
    WEEKLY_LEADER_METRICS,
    WEEKLY_OKR_METRICS,
    WEEKLY_REVIEW_METRICS,
    fetch_metrics,
    fetch_metrics_weekly,
    load_weekly_cache,
    write_weekly_cache,
)

# English copy for the interactive dashboard UI (embedded payload + templates).
DASHBOARD_MAINTENANCE_REVIEW_NOTE = (
    "IBM Store Maintenance ≠ NetSuite 87310 — current Snowflake role cannot see leaf; "
    "dashboard values = IBM Pulse fallback. Pending reconciliation with Mgmt PL / finance."
)
DASHBOARD_SOLD_SELECTION_REVIEW_NOTE = (
    "Pending your verification — approved Looker: wolt_market_exploration/wolt_market_purchases (V ✅). "
    "Do not use wolt_market_data/wolt_market_purchases (not approved). "
    "Pick a variant in the dashboard after your manager meeting."
)
DASHBOARD_CLIENT_GROWTH_REVIEW_NOTE = (
    "FTU, FTU Conversion, Returning Clients & Returning Client Conversion — Golden Growth 106613 "
    "(country dedup, ISR woltmarket). Month + weekly (WEEKLY toggle). Snowflake vs Looker ref."
)
DASHBOARD_MAINTENANCE_REVIEW = {
    **MAINTENANCE_REVIEW_PAYLOAD,
    "noteHe": DASHBOARD_MAINTENANCE_REVIEW_NOTE,
}

_NOT_CERTIFIED_BADGE_EN = {
    "לא מאושר": "Not approved",
    "! לא מאושר": "! Not approved",
}


def _dashboard_not_certified_explores() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in LOOKER_EXPLORE_NOT_CERTIFIED:
        row = dict(item)
        badge = row.get("badge", "")
        row["badge"] = _NOT_CERTIFIED_BADGE_EN.get(badge, badge)
        rows.append(row)
    return rows


ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "auto_outputs" / "okr_2026_interactive_dashboard.html"
PAGES_HTML = ROOT / "docs" / "index.html"
LOGO_PATH = ROOT / "assets" / "wolt_market_logo.png"
VALIDATION_HTML = ROOT / "auto_outputs" / "okr_2026_validation.html"

DASHBOARD_MONTH_COUNT = 12
MONTH_KEYS = [f"2026-{m:02d}" for m in range(1, DASHBOARD_MONTH_COUNT + 1)]
MONTH_LABELS = [
    "Jan 26", "Feb 26", "Mar 26", "Apr 26", "May 26", "Jun 26",
    "Jul 26", "Aug 26", "Sep 26", "Oct 26", "Nov 26", "Dec 26",
]
# Default period filter — months with refreshed actuals (update when scope extends).
DEFAULT_SELECTED_MONTH_KEYS: tuple[str, ...] = (
    "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
)
STORAGE_TARGETS = "okr2026_targets_v1"
STORAGE_ACTUALS = "okr2026_actuals_v1"
STORAGE_OWNERS = "okr2026_owners_v1"
STORAGE_SOLD_CHOICE = "okr2026_sold_selection_choice_v1"
STORAGE_PROMOTED_REVIEW = "okr2026_promoted_review_v1"
TARGET_EDIT_PIN = "1618"  # 4-digit PIN to unlock Target tab editing
TARGET_UNLOCK_SESSION_KEY = "okr2026_target_unlocked_v1"

# For review → Main KPIs insert order when user clicks "Use in dashboard".
REVIEW_PROMOTION_MAIN: list[list[str]] = [
    ["FTU", "DDE FEE/order"],
    ["FTU Conversion", "FTU"],
    ["Returning Clients", "FTU Conversion"],
    ["Returning Client Conversion", "Returning Clients"],
]

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

# Gap vs target: one column for the selected period filter (month chips).
# "cumulative_absolute" = sum(actual) − sum(target) across selected months (Orders)
# "average_vs_average" = avg(actual) − avg(target); show abs + % change (DDE FEE/order)
# "absolute" = sum(actual − target) for selected period (default until configured)
GAP_MODE_DEFAULT = "absolute"
GAP_MODES: dict[str, str] = {
    "Orders": "cumulative_absolute",
    "DDE FEE/order": "average_vs_average",
}

METRIC_HINTS: dict[str, str] = {
    "Orders": "Thousands (K)",
    "FTU": "Thousands (K)",
    "Returning Clients": "Thousands (K)",
    "VSL": "ISR country incl. DC",
}

# Display format: percent | integer | decimal:N (N = decimal places for actuals)
METRIC_FORMAT: dict[str, str] = {
    "Orders": "integer",
    "DDE FEE/order": "decimal:1",
    "FTU": "integer",
    "FTU Conversion": "percent:2",
    "Returning Clients": "integer",
    "Returning Client Conversion": "percent:2",
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
    "Average Goods Rating": "decimal:2",
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



def _load_cached_weekly() -> dict | None:
    cached = load_weekly_cache()
    if cached:
        return cached
    if not VALIDATION_HTML.is_file():
        return None
    text = VALIDATION_HTML.read_text(encoding="utf-8")
    match = re.search(r"window\.OKR_VALIDATION = (\{.*?\});</script>", text, re.S)
    if not match:
        return None
    payload = json.loads(match.group(1))
    return payload.get("weekly")


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


def _default_selected_month_keys(
    actuals_snow: dict[str, list[float | None]],
) -> list[str]:
    """Jan through the last month with any Snowflake actual (e.g. Jan–Jun until July closes)."""
    last_with_data = -1
    for i, month_key in enumerate(MONTH_KEYS):
        if any(
            i < len(series) and series[i] is not None
            for series in actuals_snow.values()
        ):
            last_with_data = i
    if last_with_data < 0:
        return [MONTH_KEYS[0]]
    return MONTH_KEYS[: last_with_data + 1]


def _build_payload(
    actuals_snow: dict[str, list[float | None]],
    weekly_payload: dict | None = None,
) -> dict:
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
    approved_metrics = [
        n for n in ALL_METRIC_NAMES
        if n not in REVIEW_TAB_METRICS and n not in TO_DELETE_TAB_METRICS
    ]
    main_metrics = [m for m in MAIN_SHEET_METRICS if m in ALL_METRIC_NAMES]
    leader_metrics = [m for m in LEADER_SHEET_METRICS if m not in TO_DELETE_TAB_METRICS]
    to_delete_metrics = list(TO_DELETE_TAB_METRICS)
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
    default_owners = {
        **DEFAULT_OWNERS,
        SOLD_FROM_SELECTION_PROMOTED_NAME: {"leader": "CAT & Content", "partner": ""},
    }
    default_targets = build_default_targets_flat(MONTH_KEYS)
    default_selected_months = _default_selected_month_keys(actuals_snow)
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
        "notCertifiedLookerExplores": _dashboard_not_certified_explores(),
        "reviewPromotionMain": REVIEW_PROMOTION_MAIN,
        "reviewMetrics": list(REVIEW_TAB_METRICS),
        "reviewNote": DASHBOARD_SOLD_SELECTION_REVIEW_NOTE,
        "clientGrowthReviewNote": DASHBOARD_CLIENT_GROWTH_REVIEW_NOTE,
        "toDeleteMetrics": to_delete_metrics,
        "maintenanceReviewNote": DASHBOARD_MAINTENANCE_REVIEW_NOTE,
        "maintenanceReview": DASHBOARD_MAINTENANCE_REVIEW,
        "soldSelectionReviewNote": DASHBOARD_SOLD_SELECTION_REVIEW_NOTE,
        "lookerRef": {
            k: LOOKER[k]
            for k in REVIEW_TAB_METRICS
            if k in LOOKER
        },
        "monthKeys": MONTH_KEYS,
        "monthLabels": MONTH_LABELS,
        "defaultSelectedMonths": list(DEFAULT_SELECTED_MONTH_KEYS),
        "defaultTargets": default_targets,
        "defaultTargetsNote": "OKR 2026 target spreadsheet · Jan–Dec 2026",
        "actuals": actuals,
        "defaultOwners": default_owners,
        "looker": looker,
        "lookerFieldAliases": LOOKER_FIELD_ALIASES,
        "userVerified": sorted(USER_VERIFIED),
        "sources": sources,
        "dataSource": METRIC_DATA_SOURCE,
        "direction": {m: METRIC_DIRECTION.get(m, "higher") for m in ALL_METRIC_NAMES},
        "gapModeDefault": GAP_MODE_DEFAULT,
        "gapModes": GAP_MODES,
        "format": format_map,
        "storage": {
            "targets": STORAGE_TARGETS,
            "actuals": STORAGE_ACTUALS,
            "owners": STORAGE_OWNERS,
            "soldChoice": STORAGE_SOLD_CHOICE,
            "promotedReview": STORAGE_PROMOTED_REVIEW,
            "targetUnlockSession": TARGET_UNLOCK_SESSION_KEY,
        },
        "targetEditPin": TARGET_EDIT_PIN,
        "weeklyMetrics": list(WEEKLY_OKR_METRICS),
        "weeklyReviewMetrics": list(WEEKLY_REVIEW_METRICS),
        "weeklyLeaderMetrics": list(WEEKLY_LEADER_METRICS),
        "weekKeys": (weekly_payload or {}).get("weekKeys", []),
        "weekLabels": (weekly_payload or {}).get("weekLabels", []),
        "actualsWeekly": (weekly_payload or {}).get("actuals", {}),
        "lastCompletedWeekStart": (weekly_payload or {}).get("lastCompletedWeekStart", ""),
        "weeklyDataAsOf": (weekly_payload or {}).get("dataAsOf", ""),
        "weeklyViewCount": 6,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>OKR 2026 — Wolt Market ISR</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {
      --wolt-cyan: #00C2E8;
      --wolt-cyan-dark: #0095B3;
      --wolt-cyan-deep: #007A94;
      --wolt-cyan-light: #5DD4EF;
      --wolt-cyan-pale: #E8FAFE;
      --wolt-cyan-muted: #C2EEF8;
      --bg: #edf8fb;
      --surface: #ffffff;
      --surface2: #f6fdff;
      --border: #b8e4ef;
      --text: #0a2540;
      --muted: #5a7d8c;
      --accent: var(--wolt-cyan);
      --accent-dim: var(--wolt-cyan-dark);
      --miss-bg: #ffe4e6;
      --miss-border: #fb7185;
      --miss-text: #9f1239;
      --hit-bg: #d1fae5;
      --hit-border: #34d399;
      --hit-text: #065f46;
      --neutral-bg: #f0f9fc;
      --tab-active: var(--wolt-cyan);
      --radius: 24px;
      --radius-sm: 16px;
      --radius-pill: 999px;
      --font-ui: "Space Grotesk", "Segoe UI", system-ui, sans-serif;
      --font-body: "Outfit", "Segoe UI", system-ui, sans-serif;
      --shadow-sm: 0 2px 12px rgba(0, 149, 179, 0.1);
      --shadow-md: 0 16px 40px rgba(0, 149, 179, 0.14);
      --shadow-lg: 0 24px 56px rgba(0, 122, 148, 0.16);
      --table-head-bg: linear-gradient(180deg, #e8fafe 0%, #d4f4fc 100%);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-body);
      background:
        radial-gradient(ellipse 90% 55% at 8% -12%, rgba(0, 194, 232, 0.22), transparent 58%),
        radial-gradient(ellipse 70% 45% at 98% 0%, rgba(93, 212, 239, 0.16), transparent 52%),
        linear-gradient(180deg, #edf8fb 0%, #f8fdfe 48%, #e5f4f8 100%);
      color: var(--text);
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }
    .wrap { max-width: none; margin: 0 auto; padding: 16px 10px 40px; }
    .brand-header {
      background: linear-gradient(128deg, rgba(0, 194, 232, 0.95) 0%, rgba(0, 152, 189, 0.92) 55%, rgba(0, 122, 148, 0.88) 100%);
      border-radius: 32px;
      padding: 28px 32px;
      margin-bottom: 24px;
      box-shadow: var(--shadow-lg);
      position: relative;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.28);
      backdrop-filter: blur(12px);
    }
    .brand-header::before {
      content: "";
      position: absolute;
      top: -40%;
      right: -8%;
      width: 280px;
      height: 280px;
      background: radial-gradient(circle, rgba(255,255,255,0.22) 0%, transparent 70%);
      pointer-events: none;
    }
    .brand-header::after {
      content: "";
      position: absolute;
      bottom: -50%;
      left: 5%;
      width: 200px;
      height: 200px;
      background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
      pointer-events: none;
    }
    .brand-top {
      display: grid;
      grid-template-columns: auto 1fr;
      align-items: center;
      gap: 22px;
      position: relative;
      z-index: 1;
      min-height: 96px;
    }
    .wm-logo {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 24px;
      overflow: hidden;
      box-shadow: 0 12px 36px rgba(0, 60, 80, 0.3);
      line-height: 0;
      height: 96px;
    }
    .wm-logo-img {
      display: block;
      height: 100%;
      width: auto;
      max-width: 280px;
      object-fit: contain;
    }
    .brand-text {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      text-align: center;
      min-width: 240px;
      pointer-events: none;
    }
    .brand-text h1 {
      margin: 0 0 4px;
      font-family: var(--font-ui);
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.04em;
      color: #fff;
      line-height: 1.1;
    }
    .brand-text .subtitle {
      color: rgba(255, 255, 255, 0.9);
      font-size: 14px;
      margin: 0;
      font-weight: 500;
    }
    .toolbar {
      display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
      background: rgba(255, 255, 255, 0.82);
      backdrop-filter: blur(18px);
      border: 1px solid rgba(184, 228, 239, 0.85);
      border-radius: var(--radius);
      padding: 14px 16px;
      margin-bottom: 18px;
      box-shadow: var(--shadow-sm);
    }
    .toolbar-block label {
      display: block; font-family: var(--font-ui); font-size: 10px; text-transform: uppercase;
      letter-spacing: 0.1em; color: var(--muted); margin-bottom: 8px; font-weight: 600;
    }
    .period-chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      border: 1px solid var(--border); background: var(--surface2); color: var(--text);
      border-radius: var(--radius-pill); padding: 8px 16px; font-size: 13px; cursor: pointer;
      font-family: var(--font-ui); font-weight: 600;
      transition: all 0.2s ease;
    }
    .chip:hover { border-color: var(--wolt-cyan); background: var(--wolt-cyan-pale); }
    .chip.active {
      background: linear-gradient(135deg, var(--wolt-cyan) 0%, var(--wolt-cyan-dark) 100%);
      border-color: var(--wolt-cyan-dark);
      color: #fff;
      box-shadow: 0 4px 12px rgba(0, 149, 179, 0.35);
    }
    .chip:disabled, .chip.disabled { opacity: 0.45; cursor: not-allowed; }
    .leader-toolbar {
      padding: 12px 14px; border-bottom: 1px solid var(--border);
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
      background: var(--wolt-cyan-pale); font-weight: 700; color: var(--wolt-cyan-deep);
      border-top: 2px solid var(--wolt-cyan-light);
    }
    .btn {
      border: none; border-radius: var(--radius-pill); padding: 9px 18px; font-size: 13px;
      font-family: var(--font-ui); font-weight: 600; cursor: pointer; background: var(--surface2);
      color: var(--text); border: 1px solid var(--border);
      transition: all 0.2s ease;
    }
    .btn:hover { border-color: var(--wolt-cyan); color: var(--wolt-cyan-dark); }
    .btn-primary {
      background: linear-gradient(135deg, var(--wolt-cyan) 0%, var(--wolt-cyan-dark) 100%);
      border-color: var(--wolt-cyan-dark);
      color: #fff;
      box-shadow: 0 4px 12px rgba(0, 149, 179, 0.3);
    }
    .btn-muted { opacity: 0.8; }
    .action-col { min-width: 170px; vertical-align: middle; }
    tr.row-selected td { background: rgba(0, 194, 232, 0.08); }
    tr.row-selected .metric-cell { box-shadow: inset 3px 0 0 var(--wolt-cyan); }
    .tab-shell { margin-bottom: 0; }
    .tabs {
      display: inline-flex; gap: 4px; margin-bottom: 0; padding: 6px;
      background: rgba(255, 255, 255, 0.78);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(184, 228, 239, 0.9);
      border-radius: var(--radius-pill);
      box-shadow: var(--shadow-sm);
    }
    .tab {
      padding: 11px 22px; border: none;
      border-radius: var(--radius-pill); background: transparent;
      color: var(--muted); cursor: pointer; font-family: var(--font-ui);
      font-weight: 600; font-size: 14px;
      transition: all 0.22s ease;
    }
    .tab:hover { color: var(--wolt-cyan-dark); background: rgba(232, 250, 254, 0.85); }
    .tab.active {
      background: linear-gradient(135deg, var(--wolt-cyan) 0%, var(--wolt-cyan-dark) 100%);
      color: #fff;
      box-shadow: 0 6px 20px rgba(0, 149, 179, 0.38);
    }
    .tab.tab-delete { color: #b91c1c; }
    .tab.tab-delete:hover { color: #991b1b; background: #fef2f2; }
    .tab.tab-delete.active {
      background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
      color: #fff;
      box-shadow: 0 6px 20px rgba(220, 38, 38, 0.35);
    }
    .src-to-delete { background: #fee2e2; color: #991b1b; }
    .panel {
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(184, 228, 239, 0.85);
      border-radius: var(--radius);
      padding: 0; overflow: hidden;
      box-shadow: var(--shadow-md);
      margin-top: 16px;
    }
    .panel.hidden { display: none; }
    .panel-head {
      padding: 12px 14px; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
      background: linear-gradient(180deg, var(--surface) 0%, var(--surface2) 100%);
    }
    .panel-head h2 { margin: 0; font-size: 16px; color: var(--wolt-cyan-deep); font-weight: 700; font-family: var(--font-ui); }
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
    .table-scroll { overflow-x: auto; overflow-y: auto; max-height: calc(100vh - 180px); }
    table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; min-width: 980px; }
    th, td { border-bottom: 1px solid var(--border); padding: 10px 6px; text-align: center; vertical-align: top; }
    th { position: sticky; top: 0;
      background: var(--table-head-bg);
      z-index: 2; color: var(--wolt-cyan-deep);
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700;
      border-bottom: 2px solid var(--wolt-cyan-muted);
    }
    th.leader-col, th.partner-col, th.corner, th.month-col, th.action-col {
      background: var(--table-head-bg);
    }
    th.leader-col, th.partner-col, th.corner {
      font-size: 13px; font-weight: 700; font-family: var(--font-ui);
      letter-spacing: 0.08em; vertical-align: middle; padding: 12px 6px;
      text-align: center;
    }
    th.month-col {
      font-size: 13px; font-weight: 700; font-family: var(--font-ui);
      letter-spacing: 0.05em; vertical-align: middle; padding: 8px 5px;
      min-width: 76px;
    }
    th.gap-col {
      font-size: 13px; font-weight: 700; font-family: var(--font-ui);
      letter-spacing: 0.04em; vertical-align: middle; padding: 10px 10px;
      min-width: 128px; width: 128px;
      background: linear-gradient(180deg, #007a94 0%, #005f73 100%);
      color: #fff;
      border-bottom: 2px solid #004d5c;
    }
    th.gap-col .th-sub { color: rgba(255, 255, 255, 0.88); }
    th.gap-divider, td.gap-divider {
      width: 5px; min-width: 5px; max-width: 5px; padding: 0;
      background: var(--wolt-cyan-muted);
      border-left: 2px solid var(--wolt-cyan-dark);
      vertical-align: middle;
    }
    td.gap-col { vertical-align: middle; min-width: 128px; width: 128px; padding: 10px 8px; }
    th.month-col .th-sub, .edit-sub {
      display: block; font-size: 12px; font-weight: 600; text-transform: none;
      letter-spacing: 0.02em; margin-top: 4px; color: var(--muted);
      font-family: var(--font-body);
    }
    th.corner, td.metric-cell {
      text-align: center; position: sticky; left: 184px; z-index: 1;
      min-width: 232px; max-width: 280px; width: 232px; line-height: 1.45; white-space: normal;
      vertical-align: middle;
    }
    td.metric-cell { background: var(--surface); }
    th.corner { z-index: 3; left: 184px; background: var(--table-head-bg); }
    th.leader-col, td.leader-col {
      text-align: center; position: sticky; left: 0; z-index: 2;
      min-width: 84px; width: 84px; font-size: 15px; font-weight: 700;
      font-family: var(--font-ui); vertical-align: middle; color: var(--wolt-cyan-deep);
      letter-spacing: -0.01em; line-height: 1.25;
    }
    td.leader-col { background: var(--surface); }
    th.leader-col { background: var(--table-head-bg); }
    th.partner-col, td.partner-col {
      text-align: center; position: sticky; left: 84px; z-index: 2;
      min-width: 100px; width: 100px; font-size: 15px; font-weight: 700;
      font-family: var(--font-ui); vertical-align: middle; color: var(--wolt-cyan-deep);
      letter-spacing: -0.01em; line-height: 1.25;
    }
    td.partner-col { background: var(--surface); }
    th.partner-col { background: var(--table-head-bg); }
    th.leader-col { z-index: 4; left: 0; }
    th.partner-col { z-index: 4; left: 84px; }
    .meta-input {
      width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 12px;
      color: var(--text); padding: 6px 8px; font-size: 12px;
    }
    .meta-input:focus { outline: none; border-color: var(--wolt-cyan); box-shadow: 0 0 0 3px rgba(0, 194, 232, 0.2); }
    .target-lock-bar {
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      font-size: 12px; color: var(--muted);
    }
    .target-lock-bar.locked { color: #92400e; }
    .target-lock-bar.unlocked { color: #065f46; }
    .btn-target-lock {
      border: 1px solid var(--border); background: var(--surface);
      color: var(--text); border-radius: 8px; padding: 6px 12px;
      font-size: 12px; font-weight: 600; cursor: pointer; font-family: var(--font-ui);
    }
    .btn-target-lock:hover { border-color: var(--wolt-cyan); color: var(--wolt-cyan-deep); }
    .btn-target-lock.primary {
      background: var(--wolt-cyan-deep); border-color: var(--wolt-cyan-deep); color: #fff;
    }
    .btn-target-lock.primary:hover { background: #007a94; border-color: #007a94; color: #fff; }
    #panelEdit.target-locked .target-input,
    #panelEdit.target-locked .owner-input {
      pointer-events: none; background: var(--surface2); color: var(--muted); cursor: not-allowed;
    }
    .target-pin-modal {
      position: fixed; inset: 0; z-index: 2000;
      display: flex; align-items: center; justify-content: center;
      background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(2px);
    }
    .target-pin-modal.hidden { display: none; }
    .target-pin-dialog {
      width: min(92vw, 320px); background: #fff; border-radius: 12px;
      border: 1px solid var(--border); box-shadow: var(--shadow-md); padding: 18px 16px 14px;
    }
    .target-pin-dialog h3 { margin: 0 0 6px; font-size: 16px; color: var(--wolt-cyan-deep); }
    .target-pin-dialog p { margin: 0 0 12px; font-size: 13px; color: var(--muted); }
    .target-pin-input {
      width: 100%; box-sizing: border-box; text-align: center; letter-spacing: 0.35em;
      font-size: 22px; font-weight: 700; padding: 10px 12px; border-radius: 8px;
      border: 1px solid var(--border); font-family: var(--font-ui);
    }
    .target-pin-input:focus { outline: none; border-color: var(--wolt-cyan); box-shadow: 0 0 0 3px rgba(0, 194, 232, 0.2); }
    .target-pin-error { margin-top: 8px; font-size: 12px; color: #b91c1c; }
    .target-pin-error.hidden { display: none; }
    .target-pin-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
    .target-val { font-size: 10px; color: var(--muted); margin-top: 6px; line-height: 1.35; }
    .edit-sub { font-size: 12px; color: var(--muted); font-weight: 600; display: block; margin-top: 4px; }
    .manual-row td { background: rgba(237, 233, 254, 0.35); }
    .metric-name {
      font-weight: 700; color: var(--text); font-family: var(--font-ui);
      font-size: 15px; letter-spacing: -0.01em; line-height: 1.25;
    }
    .metric-alias { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.3; }
    .metric-hint { font-size: 10px; color: #64748b; margin-top: 2px; }
    .src-link {
      display: inline-flex; align-items: center; justify-content: center; gap: 4px; margin-top: 6px;
      font-size: 11px; color: var(--wolt-cyan-dark); text-decoration: none; font-weight: 600;
    }
    .src-link:hover { text-decoration: underline; }
    .src-link svg { width: 12px; height: 12px; opacity: 0.85; }
    .perf-cell-wrap {
      display: flex; flex-direction: column; align-items: stretch; gap: 5px; min-width: 72px;
    }
    .cell-actual {
      border-radius: var(--radius-sm); padding: 6px 5px; min-width: 72px; min-height: 44px;
      background: var(--neutral-bg); border: 1px solid var(--border);
      box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    .cell-actual.has-target { min-height: 44px; }
    .cell-actual.miss {
      background: var(--miss-bg) !important; border: 2px solid var(--miss-border) !important; color: var(--miss-text);
    }
    .cell-actual.hit {
      background: var(--hit-bg) !important; border: 2px solid var(--hit-border) !important; color: var(--hit-text);
    }
    .cell-actual.no-target { border-style: dashed; opacity: 0.92; }
    .actual-val { font-size: 15px; font-weight: 700; line-height: 1.2; font-family: var(--font-ui); letter-spacing: -0.02em; }
    .cell-gap {
      border-radius: var(--radius-sm); padding: 10px 8px; min-width: 112px; width: 100%; min-height: 52px;
      background: #f8fdff; border: 1px solid #c2eef8;
      box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center;
    }
    .cell-gap.miss {
      background: var(--miss-bg) !important; border: 2px solid var(--miss-border) !important; color: var(--miss-text);
    }
    .cell-gap.hit {
      background: var(--hit-bg) !important; border: 2px solid var(--hit-border) !important; color: var(--hit-text);
    }
    .cell-gap.empty { color: #94a3b8; font-style: italic; font-size: 12px; border-style: dashed; }
    .gap-val { font-size: 15px; font-weight: 700; line-height: 1.15; font-family: var(--font-ui); letter-spacing: -0.02em; }
    .gap-val.gap-pct { font-size: 12px; font-weight: 700; margin-top: 3px; opacity: 0.95; }
    .gap-ref {
      font-size: 10px; font-weight: 600; color: var(--muted); margin-top: 3px; line-height: 1.25;
      text-transform: uppercase; letter-spacing: 0.03em;
    }
    .cell-gap.hit .gap-ref, .cell-gap.miss .gap-ref { opacity: 0.85; }
    .cell-target-mini {
      padding: 6px 10px; border-radius: var(--radius-sm); text-align: center;
      background: var(--wolt-cyan-pale); border: 1.5px solid var(--wolt-cyan-light);
      font-size: 11px; font-weight: 700; color: var(--wolt-cyan-deep); line-height: 1.3;
      box-shadow: 0 2px 8px rgba(0, 149, 179, 0.1);
    }
    .cell-target-mini .lbl {
      display: block; font-size: 9px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.04em; color: var(--wolt-cyan-dark); margin-bottom: 2px;
    }
    .cell-week-mini {
      padding: 6px 10px; border-radius: var(--radius-sm); text-align: center;
      background: #f0f9fc; border: 1.5px dashed var(--border);
      font-size: 11px; font-weight: 700; color: var(--muted); line-height: 1.3;
    }
    .cell-week-mini .lbl {
      display: block; font-size: 9px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.04em; color: var(--muted); margin-bottom: 2px;
    }
    .actual-inline-input {
      width: 100%; min-width: 72px; max-width: 110px;
      background: #fff; border: 1px solid var(--border); border-radius: 12px;
      color: var(--text); padding: 8px 10px; font-size: 15px; font-weight: 700;
      text-align: center; font-variant-numeric: tabular-nums;
    }
    .actual-inline-input:focus { outline: none; border-color: var(--wolt-cyan); box-shadow: 0 0 0 3px rgba(0,194,232,0.2); }
    .target-only-cell { display: flex; align-items: center; justify-content: center; min-height: 52px; }
    .edit-cell-stack { display: flex; flex-direction: column; gap: 8px; align-items: center; min-height: 52px; justify-content: center; }
    .cell-actual.miss .target-val { color: #fca5a5; }
    .delta { font-size: 10px; margin-top: 2px; opacity: 0.9; }
    .no-actual { color: #64748b; font-style: italic; }
    .target-input {
      width: 100%; min-width: 72px; max-width: 110px;
      background: var(--surface2); border: 1px solid var(--border); border-radius: 12px;
      color: var(--text); padding: 8px 10px; font-size: 14px; text-align: center;
      font-variant-numeric: tabular-nums;
    }
    .target-input:focus { outline: none; border-color: var(--wolt-cyan); box-shadow: 0 0 0 3px rgba(0,194,232,0.2); }
    .target-wrap { display: inline-flex; align-items: center; justify-content: center; gap: 2px; width: 100%; }
    .target-wrap.percent .target-input { max-width: 88px; }
    .target-suffix { color: var(--muted); font-size: 13px; font-weight: 600; }
    .save-toast {
      position: fixed; bottom: 24px; right: 24px;
      background: linear-gradient(135deg, var(--wolt-cyan) 0%, var(--wolt-cyan-dark) 100%);
      border: none; padding: 12px 20px; border-radius: var(--radius-pill);
      font-family: var(--font-ui); font-size: 13px; font-weight: 600; color: #fff;
      opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 99;
      box-shadow: var(--shadow-md);
    }
    .save-toast.show { opacity: 1; }
    .summary-bar {
      display: flex; gap: 20px; flex-wrap: wrap; padding: 12px 18px;
      background: var(--surface2); border-bottom: 1px solid var(--border); font-size: 13px;
    }
    .summary-bar strong { color: var(--wolt-cyan-dark); }
    .hint-banner {
      margin: 0 0 16px; padding: 14px 18px; border-radius: var(--radius-sm); font-size: 13px;
      background: var(--wolt-cyan-pale); border: 1px solid var(--wolt-cyan-muted); color: var(--wolt-cyan-deep);
    }
    .hint-banner.warn { background: #fffbeb; border-color: #fcd34d; color: #92400e; }
    .essi-sources { width: 100%; font-size: 12px; margin-top: 10px; border-collapse: collapse; }
    .essi-sources th, .essi-sources td { border: 1px solid #166534; padding: 8px 10px; text-align: left; }
    .essi-sources th { background: #dcfce7; color: #166534; }
    .essi-meta { font-size: 12px; color: #166534; margin: 8px 0 0; line-height: 1.5; }
    .weekly-row-actions { margin-top: 8px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .btn-weekly {
      font-family: var(--font-ui);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.06em;
      padding: 4px 10px;
      border-radius: var(--radius-pill);
      border: 1px solid var(--wolt-cyan-dark);
      background: rgba(255, 255, 255, 0.9);
      color: var(--wolt-cyan-deep);
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .btn-weekly:hover { background: var(--wolt-cyan-pale); }
    .btn-weekly.active {
      background: linear-gradient(180deg, var(--wolt-cyan) 0%, var(--wolt-cyan-dark) 100%);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 2px 8px rgba(0, 149, 179, 0.35);
    }
    .weekly-unavailable {
      font-size: 10px;
      color: var(--muted);
      margin-top: 8px;
      font-style: italic;
    }
    tr.row-weekly-mode td:not(.leader-col):not(.partner-col):not(.metric-cell) {
      background: rgba(240, 249, 252, 0.55);
    }
    footer { margin-top: 20px; font-size: 12px; color: var(--muted); line-height: 1.6; }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="brand-header">
      <div class="brand-top">
        <div class="wm-logo">
          <img class="wm-logo-img" src="__LOGO_DATA_URI__" alt="Wolt Market"/>
        </div>
        <div class="brand-text">
          <h1>OKR 2026</h1>
          <p class="subtitle">ISR · 1P Local · Main KPIs · Jan–Dec 2026</p>
        </div>
      </div>
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

    <div class="tab-shell">
      <div class="tabs">
        <button type="button" class="tab active" data-tab="performance">Main KPIs</button>
        <button type="button" class="tab" data-tab="leader">KPI by Leader</button>
        <button type="button" class="tab" data-tab="edit">Target</button>
        <button type="button" class="tab" data-tab="review">For review</button>
        <button type="button" class="tab tab-delete" data-tab="todelete">TO DELETE</button>
      </div>
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
          <span style="color:var(--muted);">+ cumulative Gap column</span>
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
          <span style="color:var(--muted);">+ cumulative Gap column</span>
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
      <div class="leader-toolbar">
        <div>
          <label>Filter by Leader</label>
          <div class="leader-chips" id="editLeaderChips"></div>
        </div>
      </div>
      <div class="panel-head">
        <h2>Target — goals only</h2>
        <div class="target-lock-bar locked" id="targetLockBar">
          <span id="targetLockStatus">🔒 Locked — enter PIN to edit</span>
          <button type="button" class="btn-target-lock primary" id="btnUnlockTargets">Enter PIN</button>
          <button type="button" class="btn-target-lock hidden" id="btnLockTargets">Lock editing</button>
        </div>
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
        <h2>For review</h2>
        <span style="font-size:12px;color:var(--muted);">Sold from selection — pick a variant</span>
      </div>
      <div class="hint-banner warn" id="reviewBanner"></div>
      <div class="table-scroll">
        <table id="reviewTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="panel hidden" id="panelToDelete">
      <div class="panel-head">
        <h2>TO DELETE</h2>
        <div class="legend">
          <span><i class="swatch-hit"></i> On target</span>
          <span><i class="swatch-miss"></i> Below target</span>
        </div>
      </div>
      <div class="table-scroll">
        <table id="toDeleteTable">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <footer>
      VSL includes Wolt Market DC (ISR country). Jun OFL may be partial until UE recon closes.
      IDQ pending definition review.
    </footer>
  </div>

  <div class="target-pin-modal hidden" id="targetPinModal" aria-hidden="true">
    <div class="target-pin-dialog" role="dialog" aria-labelledby="targetPinTitle">
      <h3 id="targetPinTitle">Unlock Target editing</h3>
      <p>Enter 4-digit PIN</p>
      <input type="password" class="target-pin-input" id="targetPinInput" maxlength="4" inputmode="numeric" pattern="[0-9]*" autocomplete="off"/>
      <p class="target-pin-error hidden" id="targetPinError">Wrong PIN — try again</p>
      <div class="target-pin-actions">
        <button type="button" class="btn-target-lock" id="targetPinCancel">Cancel</button>
        <button type="button" class="btn-target-lock primary" id="targetPinSubmit">Unlock</button>
      </div>
    </div>
  </div>

  <div class="save-toast" id="saveToast">Saved</div>

  <script>
    const CFG = __PAYLOAD__;

    let selectedMonths = new Set(CFG.defaultSelectedMonths || CFG.monthKeys);
    let selectedMainLeader = null;
    let selectedLeader = null;
    let selectedEditLeader = null;
    let targets = {};  /* user overrides only — defaults in CFG.defaultTargets */
    let actualOverrides = {};
    let owners = {};
    let storageOk = true;
    let saveTimer = null;
    let activeTargetInput = null;
    const targetUnlockKey = (CFG.storage && CFG.storage.targetUnlockSession) || "okr2026_target_unlocked_v1";
    let targetEditUnlocked = sessionStorage.getItem(targetUnlockKey) === "1";
    const weeklyModeMetrics = new Set();

    function isTargetEditUnlocked() { return targetEditUnlocked; }

    function applyTargetEditLockState() {
      const panel = document.getElementById("panelEdit");
      const bar = document.getElementById("targetLockBar");
      const status = document.getElementById("targetLockStatus");
      const btnUnlock = document.getElementById("btnUnlockTargets");
      const btnLock = document.getElementById("btnLockTargets");
      const locked = !targetEditUnlocked;
      if (panel) panel.classList.toggle("target-locked", locked);
      if (bar) {
        bar.classList.toggle("locked", locked);
        bar.classList.toggle("unlocked", !locked);
      }
      if (status) {
        status.textContent = locked
          ? "🔒 Locked — enter PIN to edit"
          : "🔓 Unlocked — targets auto-save";
      }
      if (btnUnlock) btnUnlock.classList.toggle("hidden", !locked);
      if (btnLock) btnLock.classList.toggle("hidden", locked);
    }

    function openTargetPinModal() {
      const modal = document.getElementById("targetPinModal");
      const inp = document.getElementById("targetPinInput");
      const err = document.getElementById("targetPinError");
      if (!modal || !inp) return;
      inp.value = "";
      if (err) err.classList.add("hidden");
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
      setTimeout(() => inp.focus(), 0);
    }

    function closeTargetPinModal() {
      const modal = document.getElementById("targetPinModal");
      if (!modal) return;
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }

    function submitTargetPin() {
      const inp = document.getElementById("targetPinInput");
      const err = document.getElementById("targetPinError");
      if (!inp) return;
      const pin = String(inp.value || "").trim();
      if (pin.length !== 4 || !/^\d{4}$/.test(pin)) {
        if (err) { err.textContent = "Enter exactly 4 digits"; err.classList.remove("hidden"); }
        return;
      }
      if (pin !== String(CFG.targetEditPin || "")) {
        if (err) { err.textContent = "Wrong PIN — try again"; err.classList.remove("hidden"); }
        inp.select();
        return;
      }
      targetEditUnlocked = true;
      sessionStorage.setItem(targetUnlockKey, "1");
      closeTargetPinModal();
      applyTargetEditLockState();
      renderEdit();
      showSaveToast("Target editing unlocked");
    }

    function lockTargetEditing() {
      targetEditUnlocked = false;
      sessionStorage.removeItem(targetUnlockKey);
      applyTargetEditLockState();
      renderEdit();
      showSaveToast("Target editing locked");
    }

    function showSaveToast(msg) {
      const toast = document.getElementById("saveToast");
      if (!toast) return;
      toast.textContent = msg;
      toast.classList.add("show");
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => toast.classList.remove("show"), 2800);
    }

    function hasWeeklyView(metric) {
      return (CFG.weeklyMetrics || []).includes(metric)
        || (CFG.weeklyReviewMetrics || []).includes(metric)
        || (CFG.weeklyLeaderMetrics || []).includes(metric);
    }

    function isWeeklyMode(metric) {
      return weeklyModeMetrics.has(metric) && hasWeeklyView(metric);
    }

    function weekIndex(weekKey) {
      return (CFG.weekKeys || []).indexOf(weekKey);
    }

    function weekLabelForKey(weekKey) {
      const i = weekIndex(weekKey);
      return i >= 0 ? (CFG.weekLabels[i] || weekKey) : weekKey;
    }

    function addWeeksIso(iso, deltaWeeks) {
      const [y, m, d] = iso.split("-").map(Number);
      const dt = new Date(Date.UTC(y, m - 1, d));
      dt.setUTCDate(dt.getUTCDate() + deltaWeeks * 7);
      return dt.toISOString().slice(0, 10);
    }

    /** Last n completed weeks ending at lastCompletedWeekStart (oldest → newest). */
    function trailingWeekKeys(n) {
      const count = n || CFG.weeklyViewCount || 6;
      const anchor = CFG.lastCompletedWeekStart;
      if (!anchor || count <= 0) return [];
      const out = [];
      for (let i = count - 1; i >= 0; i--) {
        out.push(addWeeksIso(anchor, -i));
      }
      return out;
    }

    function weekPeriodsForView() {
      return trailingWeekKeys(CFG.weeklyViewCount || 6);
    }

    function getWeeklyActual(metric, weekKey) {
      const series = (CFG.actualsWeekly || {})[metric];
      if (!series) return null;
      const i = weekIndex(weekKey);
      if (i < 0) return null;
      return series[i];
    }

    function weeklyToggleHtml(metric) {
      if (!hasWeeklyView(metric)) {
        return `<span class="weekly-unavailable">No weekly view</span>`;
      }
      if (isWeeklyMode(metric)) {
        return `<button type="button" class="btn-weekly active" data-weekly-toggle="${escAttr(metric)}">MONTHLY</button>`;
      }
      return `<button type="button" class="btn-weekly" data-weekly-toggle="${escAttr(metric)}">WEEKLY</button>`;
    }

    function bindWeeklyToggles(root) {
      root.querySelectorAll("[data-weekly-toggle]").forEach(btn => {
        btn.addEventListener("click", () => {
          const m = btn.dataset.weeklyToggle;
          if (weeklyModeMetrics.has(m)) weeklyModeMetrics.delete(m);
          else weeklyModeMetrics.add(m);
          renderPerformance();
          renderLeader();
          renderReview();
        });
      });
    }

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
    let promotedReviewMetrics = loadJson(CFG.storage.promotedReview, []);

    function syncPromotedFromSoldChoice() {
      const vm = resolveSoldVariantMetric();
      if (vm && !promotedReviewMetrics.includes(vm)) {
        promotedReviewMetrics.push(vm);
        persistJson(CFG.storage.promotedReview, promotedReviewMetrics, "__okrPromotedReviewMem");
      }
    }
    syncPromotedFromSoldChoice();

    function resolveSoldVariantMetric() {
      if (!soldSelectionChoice || !CFG.soldSelectionVariants[soldSelectionChoice]) return null;
      return CFG.soldSelectionVariants[soldSelectionChoice].metricName;
    }

    function isReviewPromoted(metric, variantKey) {
      if (variantKey) {
        return soldSelectionChoice === variantKey && promotedReviewMetrics.includes(metric);
      }
      return promotedReviewMetrics.includes(metric);
    }

    function insertMetricAfter(list, metric, after) {
      if (list.includes(metric)) return list.slice();
      const out = list.slice();
      const idx = out.indexOf(after);
      out.splice(idx >= 0 ? idx + 1 : out.length, 0, metric);
      return out;
    }

    function buildMainMetricsList() {
      let out = (CFG.mainMetrics || CFG.baseMetrics || CFG.metrics || []).slice();
      for (const row of (CFG.reviewPromotionMain || [])) {
        const metric = row[0];
        const after = row[1];
        if (promotedReviewMetrics.includes(metric)) {
          out = insertMetricAfter(out, metric, after);
        }
      }
      const soldDisplay = CFG.promotedSoldSelectionName;
      const vm = resolveSoldVariantMetric();
      if (vm && promotedReviewMetrics.includes(vm) && !out.includes(soldDisplay)) {
        out = insertMetricAfter(out, soldDisplay, CFG.soldSelectionInsertAfter || "KVI & Promo WA%");
      }
      return out;
    }

    function buildLeaderMetricsList() {
      let out = (CFG.leaderMetrics || []).slice();
      const soldDisplay = CFG.promotedSoldSelectionName;
      const vm = resolveSoldVariantMetric();
      if (vm && promotedReviewMetrics.includes(vm) && !out.includes(soldDisplay)) {
        out = insertMetricAfter(out, soldDisplay, CFG.soldSelectionInsertAfterLeader || "Area Product Selection");
      }
      return out;
    }

    function buildEditMetricsList() {
      const main = buildMainMetricsList();
      const leader = buildLeaderMetricsList();
      const toDelete = CFG.toDeleteMetrics || [];
      const seen = new Set();
      const out = [];
      [...main, ...leader, ...toDelete].forEach(m => {
        if (!seen.has(m)) { seen.add(m); out.push(m); }
      });
      return out;
    }

    let toDeleteMetricsList = (CFG.toDeleteMetrics || []).slice();

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

    function refreshViewsAfterPromotion(toastMsg) {
      refreshMetricsLists();
      renderMainLeaderChips();
      renderPerformance();
      renderLeader();
      renderEditLeaderChips();
      renderEdit();
      renderReview();
      updateHintBanner();
      if (toastMsg) {
        const toast = document.getElementById("saveToast");
        toast.textContent = toastMsg;
        toast.classList.add("show");
        clearTimeout(saveTimer);
        saveTimer = setTimeout(() => toast.classList.remove("show"), 2800);
      }
    }

    function promoteReviewMetric(metric, variantKey) {
      if (variantKey) {
        soldSelectionChoice = variantKey;
        persistJson(CFG.storage.soldChoice, soldSelectionChoice, "__okrSoldChoiceMem");
      }
      if (!promotedReviewMetrics.includes(metric)) {
        promotedReviewMetrics.push(metric);
        persistJson(CFG.storage.promotedReview, promotedReviewMetrics, "__okrPromotedReviewMem");
      }
      const onLeader = variantKey ? "Main KPIs, KPI by Leader & Target" : "Main KPIs & Target";
      refreshViewsAfterPromotion(`Added: ${metric} — ${onLeader}`);
    }

    function clearReviewPromotion(metric, variantKey) {
      promotedReviewMetrics = promotedReviewMetrics.filter(m => m !== metric);
      persistJson(CFG.storage.promotedReview, promotedReviewMetrics, "__okrPromotedReviewMem");
      if (variantKey && soldSelectionChoice === variantKey) {
        soldSelectionChoice = null;
        try { localStorage.removeItem(CFG.storage.soldChoice); } catch (e) { storageOk = false; }
      }
      refreshViewsAfterPromotion(null);
    }

    function setSoldSelectionChoice(key) {
      const spec = CFG.soldSelectionVariants[key];
      if (!spec) return;
      promoteReviewMetric(spec.metricName, key);
    }

    function clearSoldSelectionChoice() {
      const spec = soldSelectionChoice && CFG.soldSelectionVariants[soldSelectionChoice];
      if (spec) clearReviewPromotion(spec.metricName, soldSelectionChoice);
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

    function filteredEditMetrics() {
      let list = editMetricsList.slice();
      if (selectedEditLeader) {
        list = list.filter(m => leaderMatchesFilter(m, selectedEditLeader));
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
        pending_send: ["Pending send", "wf-pending_send"],
        cancelled: ["Cancelled", "wf-cancelled"],
        pending_impl: ["Later", "wf-pending_impl"],
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
        el.innerHTML = "<strong>No targets.</strong> Go to <strong>Target</strong> to enter targets — or reload if you cleared overrides.";
      } else {
        el.className = "hint-banner";
        let soldNote = "";
        if (soldSelectionChoice && CFG.soldSelectionVariants[soldSelectionChoice]) {
          soldNote = ` · <strong>Sold from selection</strong>: ${escHtml(CFG.soldSelectionVariants[soldSelectionChoice].lookerField)}`;
        }
        const srcNote = (CFG.defaultTargets && Object.keys(CFG.defaultTargets).length)
          ? " · Targets from OKR spreadsheet (editable in Target)"
          : "";
        el.innerHTML = `<strong>${n} target(s).</strong> Green = on target · Red = missed · target shown below actual.${srcNote}${soldNote}`;
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
      if (!isTargetEditUnlocked()) return;
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
      if (!isTargetEditUnlocked()) return;
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

    function gapMode(metric) {
      return (CFG.gapModes && CFG.gapModes[metric]) || CFG.gapModeDefault || "absolute";
    }

    function averageTargetForMetric(metric, monthKeys) {
      const vals = monthKeys
        .map(k => getTarget(metric, k))
        .filter(v => v !== null && v !== undefined);
      if (!vals.length) return null;
      return vals.reduce((a, b) => a + b, 0) / vals.length;
    }

    function averageCompareTotals(metric, monthKeys) {
      const ordered = monthKeys.slice().sort();
      let actualSum = 0;
      let targetSum = 0;
      let used = 0;
      for (const mk of ordered) {
        const idx = monthIndex(mk);
        const actual = getActual(metric, idx);
        const target = getTarget(metric, mk);
        if (actual === null || target === null) continue;
        actualSum += actual;
        targetSum += target;
        used += 1;
      }
      if (!used) return null;
      const avgActual = actualSum / used;
      const avgTarget = targetSum / used;
      const gap = avgActual - avgTarget;
      const pctGap = avgTarget !== 0 ? (gap / avgTarget) * 100 : null;
      return { actual: avgActual, target: avgTarget, gap, pctGap, months: used };
    }

    function selectionTotals(metric, monthKeys) {
      const ordered = monthKeys.slice().sort();
      let actualSum = 0;
      let targetSum = 0;
      let used = 0;
      for (const mk of ordered) {
        const idx = monthIndex(mk);
        const actual = getActual(metric, idx);
        const target = getTarget(metric, mk);
        if (actual === null || target === null) continue;
        actualSum += actual;
        targetSum += target;
        used += 1;
      }
      if (!used) return null;
      return { actual: actualSum, target: targetSum, gap: actualSum - targetSum, months: used };
    }

    function computeSelectionGap(metric, monthKeys) {
      const mode = gapMode(metric);
      if (mode === "average_vs_average") return averageCompareTotals(metric, monthKeys);
      return selectionTotals(metric, monthKeys);
    }

    function formatGapValue(metric, gap) {
      if (gap === null) return "—";
      let txt = formatDisplay(metric, gap, false);
      if (gap > 0) txt = "+" + txt;
      return txt;
    }

    function formatGapPct(pct) {
      if (pct === null || pct === undefined || !Number.isFinite(pct)) return "";
      const sign = pct > 0 ? "+" : "";
      return sign + pct.toFixed(1) + "%";
    }

    function selectedPeriodLabel(monthKeys) {
      if (!monthKeys.length) return "";
      const ordered = monthKeys.slice().sort();
      const first = CFG.monthLabels[monthIndex(ordered[0])];
      const last = CFG.monthLabels[monthIndex(ordered[ordered.length - 1])];
      return first === last ? first : `${first}–${last}`;
    }

    function gapReferenceLabel(metric, monthKeys, totals) {
      const mode = gapMode(metric);
      if (!totals) return "";
      if (mode === "average_vs_average") {
        return `Avg ${formatTargetValue(metric, totals.actual)} vs ${formatTargetValue(metric, totals.target)}`;
      }
      if (mode === "cumulative_absolute") {
        return `ΣT ${formatTargetValue(metric, totals.target)}`;
      }
      return `ΣT ${formatTargetValue(metric, totals.target)}`;
    }

    function gapValueHtml(metric, totals) {
      const mode = gapMode(metric);
      if (mode === "average_vs_average") {
        const pctTxt = formatGapPct(totals.pctGap);
        return `<div class="gap-val">${formatGapValue(metric, totals.gap)}</div>`
          + (pctTxt ? `<div class="gap-val gap-pct">${escHtml(pctTxt)}</div>` : "");
      }
      return `<div class="gap-val">${formatGapValue(metric, totals.gap)}</div>`;
    }

    function actualPerformanceCellHtml(metric, actual, target, manual, mIdx, monthKey, actualShown) {
      if (actual === null && !manual && target === null) {
        return `<td><div class="cell-actual no-actual">—</div></td>`;
      }
      const met = actual !== null && target !== null ? meetsTarget(actual, target, metric) : null;
      let cls = "cell-actual";
      if (target === null) cls += " no-target";
      else if (actual !== null) { cls += met ? " hit" : " miss"; cls += " has-target"; }
      else cls += " no-target has-target";
      let actualHtml = "";
      if (manual && mIdx !== undefined) {
        actualHtml = actualInlineInputHtml(metric, mIdx, monthKey, actualShown);
      } else {
        actualHtml = `<div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div>`;
      }
      let targetHtml = "";
      if (target !== null) {
        targetHtml = `<div class="cell-target-mini"><span class="lbl">Target</span>${formatTargetValue(metric, target)}</div>`;
      }
      return `<td><div class="perf-cell-wrap"><div class="${cls}">${actualHtml}</div>${targetHtml}</div></td>`;
    }

    function gapPerformanceCellHtml(metric, monthKeys) {
      const totals = computeSelectionGap(metric, monthKeys);
      if (!totals || totals.gap === null || totals.gap === undefined) {
        return `<td class="gap-col"><div class="cell-gap empty">—</div></td>`;
      }
      const met = meetsTarget(totals.actual, totals.target, metric);
      const cls = met ? "hit" : "miss";
      const ref = gapReferenceLabel(metric, monthKeys, totals);
      const periodLbl = selectedPeriodLabel(monthKeys);
      return `<td class="gap-col"><div class="cell-gap ${cls}">`
        + gapValueHtml(metric, totals)
        + `<div class="gap-ref">${escHtml(periodLbl)}</div>`
        + (ref ? `<div class="gap-ref">${escHtml(ref)}</div>` : "")
        + `</div></td>`;
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
        for_review: ["For review", "src-review"],
        looker_not_approved: ["For review", "src-review"],
        to_delete: ["TO DELETE", "src-to-delete"],
      };
      const [label, cls] = map[kind] || ["Manual", "src-manual"];
      return `<span class="src-badge ${cls}">${label}</span>`;
    }

    function ownerCellHtml(idx, field) {
      const metric = metricByIdx(editMetricsList, idx);
      const val = escAttr(getOwner(metric)[field] || "");
      const ro = !isTargetEditUnlocked() ? ' readonly tabindex="-1"' : "";
      return `<input type="text" class="meta-input owner-input" data-idx="${idx}" data-field="${field}" value="${val}" placeholder="—"${ro}/>`;
    }

    function valueInputHtml(idx, monthKey, kind, shown) {
      const metric = metricByIdx(editMetricsList, idx);
      const ph = targetPlaceholder(metric);
      const cls = kind === "actual" ? "actual-input" : "target-input";
      const lockAttrs = (kind === "target" && !isTargetEditUnlocked()) ? ' readonly tabindex="-1"' : "";
      const inp = `<input type="text" inputmode="decimal" class="${cls} value-input" data-kind="${kind}" data-idx="${idx}" data-month="${monthKey}" value="${escAttr(shown)}" placeholder="${ph}"${lockAttrs}/>`;
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
      const alias = (CFG.lookerFieldAliases || {})[metric];
      let link = "";
      if (lk.url) {
        link = `<a class="src-link" href="${escAttr(lk.url)}" target="_blank" rel="noopener">${linkIcon()} ${escHtml(lk.label || "Source")}</a>`;
      }
      const aliasHtml = alias
        ? `<div class="metric-hint">${escHtml(alias)}</div>`
        : "";
      return `<div class="metric-name">${escHtml(metric)}</div>` + aliasHtml + link
        + `<div class="weekly-row-actions">${weeklyToggleHtml(metric)}</div>`;
    }

    function renderToDelete() {
      const metrics = toDeleteMetricsList;
      renderPerformanceTableHead("toDeleteTable", metrics);
      const tbody = document.querySelector("#toDeleteTable tbody");
      if (!tbody) return;
      tbody.innerHTML = renderMetricRows(metrics, "toDeleteTable");
      bindPerformanceActualInputs(tbody);
      bindWeeklyToggles(tbody);
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
        + `<strong>May 2026:</strong> NetSuite ${m.may2026Netsuite} kILS vs IBM ${m.may2026Ibm} kILS · `
        + `gap ≈ ${m.may2026Gap} kILS</p>`
        + `<table class="essi-sources"><thead><tr><th>Month</th><th>NetSuite 87310</th><th>IBM fallback</th><th>Gap</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    function renderReview() {
      const banner = document.getElementById("reviewBanner");
      if (banner) {
        banner.innerHTML = (CFG.clientGrowthReviewNote
            ? `<strong>Client growth:</strong> ${CFG.clientGrowthReviewNote} `
            : "")
          + (CFG.soldSelectionReviewNote
            ? `<strong>Sold from selection:</strong> ${CFG.soldSelectionReviewNote} `
            : "")
          + " <strong>Looker Purchases:</strong> wolt_market_exploration (V ✅) only — not wolt_market_data."
          + " · <strong>Weekly:</strong> use WEEKLY toggle on each metric (last 6 completed weeks).";
      }
      const metrics = CFG.reviewMetrics || [];
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const anyWeekly = metrics.some(m => isWeeklyMode(m));
      const weekPeriods = anyWeekly ? weekPeriodsForView() : [];
      const thead = document.querySelector("#reviewTable thead");
      const tbody = document.querySelector("#reviewTable tbody");
      if (!thead || !tbody) return;
      thead.innerHTML = "<tr><th class='leader-col'>Leader</th><th class='partner-col'>Partner</th><th class='corner'>Metric</th>"
        + (anyWeekly
          ? weekPeriods.map(wk => `<th class="month-col">${escHtml(weekLabelForKey(wk))}<span class="th-sub">Week · Snowflake</span></th>`).join("")
          : months.map(k => {
              const i = monthIndex(k);
              return `<th class="month-col">${CFG.monthLabels[i]}<span class="th-sub">Snowflake</span></th>`;
            }).join("")
        ) + "<th class='action-col'>Action</th></tr>";
      tbody.innerHTML = metrics.map(metric => {
        const o = getOwner(metric);
        const variantKey = Object.keys(CFG.soldSelectionVariants || {}).find(
          k => CFG.soldSelectionVariants[k].metricName === metric
        );
        const isChosen = isReviewPromoted(metric, variantKey);
        const weeklyRow = isWeeklyMode(metric);
        const cells = anyWeekly
          ? weekPeriods.map(weekKey => {
              if (weeklyRow) {
                const actual = getWeeklyActual(metric, weekKey);
                return `<td><div class="cell-actual no-target"><div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div></div></td>`;
              }
              const monthKey = weekKey.slice(0, 7);
              const idx = monthIndex(monthKey);
              const actual = getActual(metric, idx);
              return `<td><div class="cell-actual no-target"><div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div></div></td>`;
            }).join("")
          : months.map(monthKey => {
          const idx = monthIndex(monthKey);
          const actual = getActual(metric, idx);
          return `<td><div class="cell-actual no-target"><div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div></div></td>`;
        }).join("");
        let action = "";
        const leaderNote = variantKey ? "Main KPIs + KPI by Leader + Target" : "Main KPIs + Target";
        if (isChosen) {
          action = `<button type="button" class="btn btn-muted" data-review-clear="${escAttr(metric)}"${variantKey ? ` data-sold-variant="${escAttr(variantKey)}"` : ""}>Clear selection</button>`
            + `<div class="metric-hint" style="color:#4ade80;margin-top:8px">✓ ${leaderNote}</div>`;
        } else {
          action = `<button type="button" class="btn btn-primary" data-review-promote="${escAttr(metric)}"${variantKey ? ` data-sold-variant="${escAttr(variantKey)}"` : ""}>Use in dashboard</button>`;
        }
        let rowCls = isChosen ? "row-selected" : "";
        if (weeklyRow) rowCls = (rowCls ? rowCls + " " : "") + "row-weekly-mode";
        const rowClsAttr = rowCls ? ` class="${rowCls}"` : "";
        return `<tr${rowClsAttr}><td class="leader-col">${o.leader || "—"}</td><td class="partner-col">${o.partner || "—"}</td><td class="metric-cell">${metricCellHtml(metric)}</td>${cells}<td class="action-col">${action}</td></tr>`;
      }).join("");
      tbody.querySelectorAll("[data-review-promote]").forEach(btn => {
        btn.addEventListener("click", () => {
          const variantKey = btn.dataset.soldVariant || null;
          promoteReviewMetric(btn.dataset.reviewPromote, variantKey);
        });
      });
      tbody.querySelectorAll("[data-review-clear]").forEach(btn => {
        btn.addEventListener("click", () => {
          const variantKey = btn.dataset.soldVariant || null;
          clearReviewPromotion(btn.dataset.reviewClear, variantKey);
        });
      });
      bindWeeklyToggles(tbody);
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
      const anyWeekly = metrics.some(m => isWeeklyMode(m));
      const weekPeriods = anyWeekly ? weekPeriodsForView() : [];
      const showGap = !anyWeekly;
      const metricIdxMap = {};
      editMetricsList.forEach((m, i) => { metricIdxMap[m] = i; });
      return metrics.map(metric => {
        const o = getOwner(metric);
        const wf = (CFG.metricWorkflow || {})[metric] || "auto";
        const mIdx = metricIdxMap[metric];
        const manual = isManualMetric(metric);
        const weeklyRow = isWeeklyMode(metric);
        const cells = anyWeekly
          ? weekPeriods.map(weekKey => {
              if (weeklyRow) {
                const actual = getWeeklyActual(metric, weekKey);
                if (actual === null) {
                  return `<td><div class="cell-actual no-actual">—</div></td>`;
                }
                return `<td><div class="perf-cell-wrap"><div class="cell-actual no-target">`
                  + `<div class="actual-val">${formatValue(metric, actual)}</div>`
                  + `</div></div></td>`;
              }
              const monthKey = weekKey.slice(0, 7);
              const idx = monthIndex(monthKey);
              const actual = getActual(metric, idx);
              const target = getTarget(metric, monthKey);
              if (actual === null && !manual && target === null) {
                return `<td><div class="cell-actual no-actual">—</div></td>`;
              }
              const met = actual !== null ? meetsTarget(actual, target, metric) : null;
              let cls = "cell-actual";
              if (target === null) cls += " no-target";
              else if (actual !== null) { cls += met ? " hit" : " miss"; cls += " has-target"; }
              else cls += " no-target has-target";
              let targetHtml = "";
              if (target !== null) {
                targetHtml = `<div class="cell-target-mini"><span class="lbl">Target</span>${formatTargetValue(metric, target)}</div>`;
              }
              return `<td><div class="perf-cell-wrap"><div class="${cls}">`
                + `<div class="actual-val">${actual === null ? "—" : formatValue(metric, actual)}</div>`
                + `</div>${targetHtml}</div></td>`;
            }).join("")
          : months.map(monthKey => {
          const idx = monthIndex(monthKey);
          const actual = getActual(metric, idx);
          const target = getTarget(metric, monthKey);
          const override = getActualOverride(metric, monthKey);
          const snow = getSnowflakeActual(metric, idx);
          const actualShown = override !== undefined
            ? formatTargetDisplay(metric, override)
            : (snow !== null ? formatTargetDisplay(metric, snow) : "");
          return actualPerformanceCellHtml(metric, actual, target, manual, mIdx, monthKey, actualShown);
        }).join("")
          + (showGap
            ? `<td class="gap-divider" aria-hidden="true"></td>`
              + gapPerformanceCellHtml(metric, months)
            : "");
        let rowCls = manual ? "manual-row" : "";
        if (wf === "cancelled") rowCls = (rowCls ? rowCls + " " : "") + "row-cancelled";
        if (weeklyRow) rowCls = (rowCls ? rowCls + " " : "") + "row-weekly-mode";
        const rowClsAttr = rowCls ? ` class="${rowCls}"` : "";
        return `<tr${rowClsAttr} data-metric="${escAttr(metric)}"><td class="leader-col">${o.leader || "—"}</td><td class="partner-col">${o.partner || "—"}</td><td class="metric-cell">${metricCellHtml(metric)}</td>${cells}</tr>`;
      }).join("");
    }

    function tableUsesWeeklyHeaders(metrics) {
      return metrics.some(m => isWeeklyMode(m));
    }

    function gapHeaderSubLabel(metrics, monthKeys) {
      const periodLbl = selectedPeriodLabel(monthKeys);
      const modes = new Set((metrics || []).map(m => gapMode(m)));
      if (modes.has("average_vs_average") && modes.has("cumulative_absolute")) {
        return `${periodLbl} · avg / cumulative`;
      }
      if (modes.has("average_vs_average")) return `${periodLbl} · avg`;
      if (modes.has("cumulative_absolute")) return `${periodLbl} · cumulative`;
      return `${periodLbl} · cumulative`;
    }

    function renderPerformanceTableHead(tableId, metrics) {
      const months = CFG.monthKeys.filter(k => selectedMonths.has(k));
      const thead = document.querySelector(`#${tableId} thead`);
      if (!thead) return;
      const anyWeekly = tableUsesWeeklyHeaders(metrics || []);
      const weekPeriods = anyWeekly ? weekPeriodsForView() : [];
      const showGap = !anyWeekly;
      const gapSub = gapHeaderSubLabel(metrics, months);
      const actualHeaders = anyWeekly
        ? weekPeriods.map(wk => `<th class="month-col">${escHtml(weekLabelForKey(wk))}<span class="th-sub">Week</span></th>`).join("")
        : months.map(k => {
            const i = monthIndex(k);
            return `<th class="month-col">${CFG.monthLabels[i]}<span class="th-sub">Actual</span></th>`;
          }).join("");
      const gapHeaders = showGap
        ? `<th class="gap-divider" aria-hidden="true"></th>`
          + `<th class="gap-col">Gap<span class="th-sub">${escHtml(gapSub)}</span></th>`
        : "";
      thead.innerHTML = "<tr><th class='leader-col'>Leader</th><th class='partner-col'>Partner</th><th class='corner'>Metric</th>"
        + actualHeaders + gapHeaders + "</tr>";
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

    function renderEditLeaderChips() {
      const el = document.getElementById("editLeaderChips");
      if (!el) return;
      const leaders = CFG.leaderOrder || [];
      const all = editMetricsList;
      let html = `<button type="button" class="chip${selectedEditLeader === null ? " active" : ""}" data-edit-leader="">All (${all.length})</button>`;
      html += leaders.map(l => {
        const count = all.filter(m => leaderMatchesFilter(m, l)).length;
        const active = selectedEditLeader === l ? " active" : "";
        const disabled = count === 0 ? " disabled" : "";
        return `<button type="button" class="chip${active}${disabled}" data-edit-leader="${escAttr(l)}"${count === 0 ? " disabled" : ""}>${escHtml(l)} (${count})</button>`;
      }).join("");
      el.innerHTML = html;
      el.querySelectorAll(".chip:not([disabled])").forEach(chip => {
        chip.addEventListener("click", () => {
          const v = chip.dataset.editLeader;
          selectedEditLeader = v || null;
          renderEditLeaderChips();
          renderEdit();
        });
      });
    }

    function renderLeader() {
      const metrics = filteredLeaderMetrics();
      renderPerformanceTableHead("leaderTable", metrics);
      const tbody = document.querySelector("#leaderTable tbody");
      if (!tbody) return;
      tbody.innerHTML = renderMetricRows(metrics, "leaderTable");
      bindPerformanceActualInputs(tbody);
      bindWeeklyToggles(tbody);
    }

    function renderPerformance() {
      const metrics = filteredMainMetrics();
      renderPerformanceTableHead("performanceTable", metrics);
      const tbody = document.querySelector("#performanceTable tbody");
      tbody.innerHTML = renderMetricRows(metrics, "performanceTable");
      bindPerformanceActualInputs(tbody);
      bindWeeklyToggles(tbody);
    }

    function bindValueInput(inp) {
      let debounce = null;
      inp.addEventListener("focus", () => {
        if (inp.dataset.kind === "target" && !isTargetEditUnlocked()) {
          inp.blur();
          openTargetPinModal();
          return;
        }
        activeTargetInput = inp;
      });
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
          return `<th class="month-col">${lbl}<span class="edit-sub">Target</span></th>`;
        }).join("") + "</tr>";

      tbody.innerHTML = filteredEditMetrics().map((metric) => {
        const mIdx = editMetricsList.indexOf(metric);
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
        inp.addEventListener("focus", () => {
          if (!isTargetEditUnlocked()) {
            inp.blur();
            openTargetPinModal();
          }
        });
        inp.addEventListener("input", () => {
          if (!isTargetEditUnlocked()) return;
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
        document.getElementById("panelToDelete").classList.toggle("hidden", id !== "todelete");
        if (id === "performance") { renderMainLeaderChips(); renderPerformance(); }
        if (id === "leader") { renderLeaderChips(); renderLeader(); }
        if (id === "edit") { renderEditLeaderChips(); renderEdit(); }
        if (id === "review") renderReview();
        if (id === "todelete") renderToDelete();
      });
    });

    document.getElementById("btnAllPeriods").addEventListener("click", () => {
      selectedMonths = new Set(CFG.monthKeys);
      renderPeriodChips(); renderMainLeaderChips(); renderPerformance(); renderLeader(); renderEditLeaderChips(); renderEdit(); renderReview(); renderToDelete();
    });
    document.getElementById("btnClearPeriods").addEventListener("click", () => {
      const defaults = CFG.defaultSelectedMonths || CFG.monthKeys;
      selectedMonths = new Set([defaults[defaults.length - 1]]);
      renderPeriodChips(); renderMainLeaderChips(); renderPerformance(); renderLeader(); renderEditLeaderChips(); renderEdit(); renderReview(); renderToDelete();
    });

    document.getElementById("btnUnlockTargets").addEventListener("click", openTargetPinModal);
    document.getElementById("btnLockTargets").addEventListener("click", lockTargetEditing);
    document.getElementById("targetPinCancel").addEventListener("click", closeTargetPinModal);
    document.getElementById("targetPinSubmit").addEventListener("click", submitTargetPin);
    document.getElementById("targetPinInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submitTargetPin(); }
      if (e.key === "Escape") { e.preventDefault(); closeTargetPinModal(); }
    });
    document.getElementById("targetPinModal").addEventListener("click", (e) => {
      if (e.target.id === "targetPinModal") closeTargetPinModal();
    });

    applyTargetEditLockState();

    renderPeriodChips();
    renderMainLeaderChips();
    renderLeaderChips();
    renderEditLeaderChips();
    renderPerformance();
    renderLeader();
    renderEdit();
    renderReview();
    renderToDelete();
    updateHintBanner();
  </script>
</body>
</html>
"""


def _logo_data_uri() -> str:
    if not LOGO_PATH.is_file():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_html(payload: dict) -> str:
    html = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    return html.replace("__LOGO_DATA_URI__", _logo_data_uri())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    if args.skip_fetch:
        actuals = _load_cached_metrics()
        if actuals is None:
            raise SystemExit("No cached metrics — run okr_2026_validation.py first.")
        weekly = _load_cached_weekly()
    else:
        actuals, _ofl_check, _vp_check, _shrink_check, _maint = fetch_metrics()
        weekly = fetch_metrics_weekly()
        write_weekly_cache(weekly)

    payload = _build_payload(actuals, weekly)
    html = build_html(payload)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    PAGES_HTML.parent.mkdir(parents=True, exist_ok=True)
    PAGES_HTML.write_text(html, encoding="utf-8")
    print("Wrote", OUT_HTML.name, "and", PAGES_HTML.relative_to(ROOT))


if __name__ == "__main__":
    main()
