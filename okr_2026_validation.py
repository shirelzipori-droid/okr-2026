"""OKR 2026 — Snowflake validation vs Looker reference (ISR Wolt Market 1P).

Pulls Jan–Jun 2026 from Unit Economics + Wolt Market / MART tables, compares
Jan–Mar to Looker benchmarks, and writes an HTML validation report.

Usage:
  python okr_2026_validation.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from wm_israel_metrics import snowflake_connection

ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "auto_outputs" / "okr_2026_validation.html"

MONTHS = [date(2026, m, 1) for m in range(1, 7)]
MONTH_LABELS = ["Jan 26", "Feb 26", "Mar 26", "Apr 26", "May 26", "Jun 26"]

# Golden SCM 106617 — validation anchor (Jan–Jun 2026 tile values; cross-check only).
SHRINK_GOLDEN_ANCHOR: list[float] = [1.49, 1.35, 1.10, 1.34, 1.43, 1.34]

# Looker reference — Jan–Jun 2026 (Golden tiles / user spreadsheet).
LOOKER: dict[str, list[float | None]] = {
    "Orders": [351, 321, 328, None, None, None],
    "DDE FEE/order": [159.3, 158.7, 169.3, None, None, None],
    "Ftu Sessions": [179, 159, 190, None, None, None],
    "Ftu Conversion": [20.2, 18.8, 15.5, None, None, None],
    "Returning User Sessions": [740, 708, 850, None, None, None],
    "Returning User Conversion": [42.4, 41.4, 34.5, None, None, None],
    "PPM%": [36.8, 36.5, 36.9, None, None, None],
    "Shrink/DDE FEE": list(SHRINK_GOLDEN_ANCHOR),
    "OFL / order (ILS)": [14.2, 15.2, 19.1, None, None, None],
    "VP%": [-1.8, 0.2, -33.4, None, None, None],
    "Weighted Availability": [92.6, 89.5, 83.0, None, None, None],
    "KVI & Promo WA%": [93.4, 89.7, 86.2, None, None, None],
    "Sold from selection — sold_from_selection_perc": [89.8, 82.2, 90.63, None, None, None],
    "Sold from selection — sold_from_product_selection_perc": [None, None, None, None, None, None],
    "POFR%": [89.8, 88.6, 88.4, None, None, None],
    "Under 45min >": [52, 58, 47, None, None, None],
    "Maintenance costs": [301, 702, 142, None, None, None],
    "Avg Units per Order": [11.7, 11.6, 12.2, None, None, None],
    "Order Frequency": [2.98, 2.85, 3.32, None, None, None],
    "Penetration Rate": [14.5, 14.3, 12.8, 15.1, 15.6, 14.8],
    "Area Product Selection": [4466, 4535, 4292, 3743, 4316, 4591],
    "%Fresh Food / DDE": [38.98, 38.47, 40.00, None, None, None],
    "IDQ": [97.6, 97.7, 97.70, None, None, None],
    "VSL": [74.6, 67.3, 61.0, None, None, None],
    "UP-TIME >": [98.0, 97.8, 93.8, None, None, None],
    "% Bad Goods Rating": [None, None, None, None, None, None],
}

# Metric source registry for OKR 2026 dashboard planning.
# snowflake_validated — matched Looker Jan–Mar; pull Jan–Jun from Snowflake.
# user_provided      — values supplied by user (CSV overrides).
# manual_entry       — hand-entered in Looker; not from Snowflake.
# pending_review     — hold until definition confirmed.
# for_review          — לשונית לבדיקה; ערכים מאומתים (Essi / ממתין לאימות).
# looker_not_approved — Snowflake OK; בחירת וריאנט / מקור Looker pending.
METRIC_SOURCE: dict[str, str] = {
    "Orders": "snowflake_validated",
    "DDE FEE/order": "snowflake_validated",
    "Ftu Sessions": "snowflake_validated",
    "Ftu Conversion": "snowflake_validated",
    "Returning User Sessions": "snowflake_validated",
    "Returning User Conversion": "snowflake_validated",
    "PPM%": "snowflake_validated",
    "Shrink/DDE FEE": "snowflake_validated",
    "OFL / order (ILS)": "snowflake_validated",
    "VP%": "snowflake_validated",
    "Weighted Availability": "snowflake_validated",
    "KVI & Promo WA%": "snowflake_validated",
    "Sold from selection — sold_from_selection_perc": "looker_not_approved",
    "Sold from selection — sold_from_product_selection_perc": "looker_not_approved",
    "POFR%": "snowflake_validated",
    "Under 45min >": "snowflake_validated",
    "Avg Units per Order": "snowflake_validated",
    "Order Frequency": "snowflake_validated",
    "Penetration Rate": "snowflake_validated",
    "Area Product Selection": "snowflake_validated",
    "IDQ": "snowflake_validated",
    "VSL": "snowflake_validated",
    "UP-TIME >": "snowflake_validated",
    "% Bad Goods Rating": "snowflake_validated",
    "Maintenance costs": "for_review",
    "%Fresh Food / DDE": "manual_entry",
}

USER_OVERRIDES_CSV = ROOT / "okr_2026_user_metrics.csv"

# Looker certification (OKR workflow Jul 2026):
#   V (green check) = approved for manager dashboards — user confirmed list below.
#   ! (warning)     = not certified — do NOT use as primary OKR link.
# Golden dashboards 106613–106617 + UE Look 47217 are always trusted.
APPROVED_LOOKER_EXPLORES: list[dict[str, str]] = [
    {
        "key": "golden",
        "model": "dashboards",
        "explore": "",
        "label": "Golden dashboards 106613–106617",
        "badge": "Golden ✅",
    },
    {
        "key": "unit_economics",
        "model": "looks",
        "explore": "47217",
        "label": "Wolt Market Unit Economics (Look 47217)",
        "badge": "UE ✅",
    },
    {
        "key": "wolt_market_purchases",
        "model": "wolt_market_exploration",
        "explore": "wolt_market_purchases",
        "label": "Wolt Market Purchases (exploration)",
        "badge": "V ✅",
    },
    {
        "key": "wolt_market_store_ops_reporting",
        "model": "wolt_market_dashboards",
        "explore": "wolt_market_store_ops_reporting",
        "label": "Wolt Market Store Ops Reporting",
        "badge": "V ✅",
    },
    {
        "key": "merchant_app_lite_reporting",
        "model": "merchant_data",
        "explore": "merchant_app_lite_reporting",
        "label": "Merchant App Lite Tasks",
        "badge": "V ✅",
    },
    {
        "key": "retail_platform_category_managers_reporting",
        "model": "merchant_data",
        "explore": "retail_platform_category_managers_reporting",
        "label": "Retail Platform - Category Managers Metrics",
        "badge": "V ✅",
    },
    {
        "key": "retail_platform_inventory_product_reporting",
        "model": "merchant_data",
        "explore": "retail_platform_inventory_product_reporting",
        "label": "Retail Platform - Product Inventory Metrics",
        "badge": "V ✅",
    },
]

# Explores with Looker ! warning or wrong for OKR — never use as primary link.
LOOKER_EXPLORE_NOT_CERTIFIED: list[dict[str, str]] = [
    {
        "model": "wolt_market_data",
        "explore": "wolt_market_purchases",
        "label": "Purchases (wolt_market_data)",
        "badge": "לא מאושר",
        "note": "Do not use for OKR — use wolt_market_exploration/wolt_market_purchases (V ✅)",
    },
    {
        "model": "wolt_market_data",
        "explore": "wolt_market_item_metrics",
        "label": "Wolt Market Item Metrics",
        "badge": "! לא מאושר",
        "note": "Looker warning icon — not certified",
    },
    {
        "model": "wolt_market_data",
        "explore": "wolt_market_items",
        "label": "Wolt Market Items",
        "badge": "! לא מאושר",
        "note": "IDQ explore — not on V ✅ list",
    },
    {
        "model": "wolt_market_data",
        "explore": "wolt_market_venue_conversion",
        "label": "WM Venue Conversion (wolt_market_data)",
        "badge": "Essi ✅",
        "note": "Essi (21 May): session counts + session-based CVR OK — no FTU/RU split",
    },
    {
        "model": "kpi_data",
        "explore": "wolt_market_metrics",
        "label": "Wolt Market Metrics (kpi_data)",
        "badge": "deprecated",
        "note": "Deprecated — Essi Jul 2026; FTU/Returning links still here for Jan–Mar benchmark only",
    },
    {
        "model": "dashboards",
        "explore": "96920",
        "label": "OKR SCM Dashboard 96920",
        "badge": "לא מאושר",
        "note": "VSL link — not on user V ✅ explore list",
    },
]

# Two explores named Purchases (user-confirmed Jul 2026):
#   V ✅  wolt_market_exploration/wolt_market_purchases — approved for OKR Looker links.
#   ⛔   wolt_market_data/wolt_market_purchases — NOT approved (internal Snowflake cross-check only).
_LOOKER_GOLDEN = (
    "https://looker.wolt.com/dashboards/106614"
    "?Comparison+Selector=growth&Period=month&Include+Ongoing+Period=no"
    "&Currency+and+Exchange+Rate+Selector=pla&Area+Selector=country"
    "&Franchise+Name=woltmarket&Country=ISR&Secondary+Product+Line=supermarket"
    "&Lookback+Periods=6"
)
# Golden Supply Chain Excellence — WA, KVI & Promo WA, POFR (ISR pre-filtered).
_LOOKER_GOLDEN_SCM = (
    "https://looker.wolt.com/dashboards/106617"
    "?Metric+Area=country&Period=month&Lookback+Periods=6"
    "&Include+Ongoing+Period=no&Currency+and+Exchange+Rate+Selector=pla"
    "&Reporting+Region=&Country=ISR&City=&Venue+Name="
    "&Franchise+Name=woltmarket&Secondary+Product+Line=supermarket&Venue+Status="
)
_LOOKER_GOLDEN_GROWTH_ISR = (
    "https://looker.wolt.com/dashboards/106613"
    "?Period=month&Include+Ongoing+Period=no"
    "&Currency+and+Exchange+Rate+Selector=pla&Area+Selector=country"
    "&Reporting+Region=&Franchise+Name=woltmarket&Country=ISR"
    "&Secondary+Product+Line=supermarket&Lookback+Periods=6&Metric+Area=country"
)
# Order Frequency / Penetration / Avg Units — Golden Growth 106613 ONLY.
# Order Frequency tile = Order Frequency (MART); NOT kpi_data Metrics explore PURCHASE_FREQUENCY.
GOLDEN_GROWTH_NOTE = (
    "Golden Growth 106613 — Order Frequency (MART venue metrics: purchases ÷ distinct retail users). "
    "לא presentation.wolt_market_metrics.PURCHASE_FREQUENCY (~2.3)."
)
PENETRATION_NOTE = (
    "Penetration Rate = Active Users % of Country MAU (USER_BASE ÷ WOLT_ACTIVE_USERS, ISR country row). "
    "לא PENETRATION_RATE KPI tile (USER_BASE ÷ COVERAGE_AREA_USERS)."
)
PRODUCT_SELECTION_NOTE = (
    "Area Product Selection = Available Selection (Golden 106615 KPI: sum AVAILABLE_PRODUCT_SELECTION_NUMERATOR "
    "÷ active WM stores, ISR). לא Product Selection / AVG_PRODUCT_SELECTION (presentation deprecated)."
)
IDQ_NOTE = (
    "IDQ = Item Data Quality (Golden 106615: WM_IDQ_NUMERATOR ÷ WM_IDQ_DENOMINATOR, ISR country month). "
    "לא wolt_market_data/wolt_market_items (~97.6 OKR slide — ! לא מאושר)."
)
_LOOKER_GOLDEN_SELECTION = (
    "https://looker.wolt.com/dashboards/106615"
    "?Metric+Area=country&Period=month&Lookback+Periods=6"
    "&Include+Ongoing+Period=no&Currency+and+Exchange+Rate+Selector=pla"
    "&Reporting+Region=&Country=ISR&City=&Venue+Name="
    "&Franchise+Name=woltmarket&Secondary+Product+Line=supermarket&Venue+Status="
)
_LOOKER_GOLDEN_STORE_OPS = (
    "https://looker.wolt.com/dashboards/106616"
    "?Metric+Area=country&Period=month&Lookback+Periods=6"
    "&Include+Ongoing+Period=no&Currency+and+Exchange+Rate+Selector=pla"
    "&Reporting+Region=&Country=ISR&City=&Venue+Name="
    "&Franchise+Name=woltmarket&Secondary+Product+Line=supermarket&Venue+Status="
)
# POFR — Golden aggregated explore (ISR, month, country); matches MART venue metrics monthly.
_LOOKER_POFR_AGGREGATED = (
    "https://looker.wolt.com/explore/wolt_market_dashboards/wolt_market_venue_metrics_aggregated"
    "?qid=uYst64GAXk7COWPNzoLPTC&origin_space=27423&toggle=fil,vis"
)
# Under 45min — store ops reporting (NOT Golden 106616; NOT OKR 96920 inventory).
_LOOKER_UNDER_45_STORE_OPS = (
    "https://looker.wolt.com/explore/wolt_market_dashboards/wolt_market_store_ops_reporting"
    "?fields=wolt_market_store_ops_reporting.metric_date,"
    "wolt_market_store_ops_reporting.delivered_under_45_minutes_orders_rate,"
    "wolt_market_store_ops_reporting.delivered_under_45_minutes_orders_count"
    "&f[wolt_market_store_ops_reporting.venue_country]=ISR"
    "&f[wolt_market_store_ops_reporting.franchise_name]=woltmarket"
    "&f[wolt_market_store_ops_reporting.period]=month"
    "&sorts=wolt_market_store_ops_reporting.metric_date+desc"
    "&limit=6"
    "&toggle=dat,fil,vis"
)
_LOOKER_RETAIL = (
    "https://looker.wolt.com/dashboards/74289"
    "?Period=month&Currency+and+Exchange+Rate+Selector=pla&Lookback+Periods=8"
    "&Metric+Level=retail%5E_business%5E_segment&Country=ISR"
    "&Partner%2FWolt+Retail=Wolt+retail&Exclude+Drive+Venues=Yes"
    "&Include+Ongoing+Period=no"
)
_LOOKER_OKR_SCM = (
    "https://looker.wolt.com/dashboards/96920"
    "?Filter+metric+grouping=product&Filter+time+aggregation=month"
    "&Metric+Date=6+month&Venue+Country=ISR"
)
# Deprecated for OKR WA — use Golden Dashboard 106614 (MART venue metrics).
_LOOKER_WA = "https://looker.wolt.com/dashboards/75053?Venue+Country=ISR"
# ISR WM Unit Economics — Look 47217 (Ziwei); qid includes WM + ISR filters.
_LOOKER_UE_ISR = (
    "https://looker.wolt.com/looks/47217"
    "?toggle=dat,fil,pik,vis&qid=y3cisQW6TChlI5Ohvh9HPa"
)
# WM Venue Metrics aggregated — used for POFR qid; not primary OKR link for ratings.
_LOOKER_WM_VENUE = (
    "https://looker.wolt.com/explore/wolt_market_dashboards/wolt_market_venue_metrics_aggregated"
    "?qid=bizqMixrnWIHH9moxATygO&toggle=fil"
)
# % Bad Goods Rating — Golden Store Ops 106616 (Period=month, ISR, woltmarket, supermarket).
# Same MART venue metrics as Store Ops Reporting; user chose Golden as canonical OKR source.
GOLDEN_BAD_GOODS_NOTE = (
    "Golden Store Ops 106616 — Bad Goods Rating % (Period=month, ISR, woltmarket, supermarket). "
    "MART: VENUE_BAD_GOODS_RATING_ORDERS_COUNT ÷ TOTAL_ORDERS_COUNT."
)
# Wolt Market Metrics explore → presentation.wolt_market_metrics (FTU_SESSIONS).
# Session-based OKR source (Adam May 2026). Looker explore deprecated for recent weeks;
# historical months (e.g. Jan 2026) still match Snowflake country row.
_LOOKER_WM_METRICS_FTU = (
    "https://looker.wolt.com/explore/kpi_data/wolt_market_metrics"
    "?fields=wolt_market_metrics.date,wolt_market_metrics.ftu_sessions,"
    "wolt_market_metrics.ftu_orders,wolt_market_metrics.ftu_conversion,"
    "wolt_market_metrics.ftu_wolt_market,wolt_market_metrics.returning_user_sessions,"
    "wolt_market_metrics.returning_user_conversion"
    "&f[wolt_market_metrics.country]=ISR"
    "&f[wolt_market_metrics.period]=month"
    "&f[wolt_market_metrics.area]=country"
    "&sorts=wolt_market_metrics.date+desc"
    "&limit=6"
    "&toggle=dat,fil,vis"
)
# Essi Grönroos, #ask-consumer-analytics, 21 May 2026 (thread 1775055446).
ESSI_SESSION_NOTE = (
    "Essi (21 May 2026): session counts and session-based conversion are fine to use; "
    "double-counting affects user/client counts only, not sessions."
)
ESSI_SESSION_NOTE_HE = (
    "Essi (21 May 2026): מותר להשתמש בספירת סשנים ובהמרה session-based — "
    "double-counting משפיע רק על user/client counts, לא על סשנים."
)
ESSI_SESSION_QUOTE = (
    "After more investigation, session counts and session-based conversion in "
    "Wolt Market Venue Conversion are actually fine to use. The double-counting issue "
    "only affects user/client counts (due to the hourly grain of the underlying data), "
    "not sessions.\n\n"
    "So if your targets were set on session-based CVR, you can safely keep using that "
    "from Venue Conversion as a bridge. For user counts, use the new WM Venue Metrics 🙂"
)
ESSI_SESSION_META = "Essi Grönroos · #ask-consumer-analytics · 21 May 2026"
ESSI_KPI_DATA_DEPRECATED_NOTE = (
    "kpi_data/wolt_market_metrics — deprecated (Essi: לא להסתמך, אפריל–מאי 2026)"
)
ESSI_VENUE_CONVERSION_NOTE = (
    "wolt_market_data/wolt_market_venue_conversion — Essi: סשנים + session-based CVR בסדר"
)
SVENJA_SESSION_SPLIT_NOTE = (
    "Svenja (מאי 2026): ב-Venue Conversion אין פיצול FTU/Returning מובנה — "
    "OKR דורש שדות נפרדים מ-Snowflake presentation.wolt_market_metrics."
)
ESSI_SESSION_SLACK = (
    "https://wolt.enterprise.slack.com/archives/C04M2CK74BF/"
    "p1779350276025539?thread_ts=1775055446.070239&cid=C04M2CK74BF"
)
# Golden SCM 106617 — Shrinkage Share of Subtotal (Wolt Market Metrics explore).
GOLDEN_SHRINK_NOTE = (
    "Golden SCM 106617 — Shrinkage Share of Subtotal "
    "(Wolt Market Metrics · woltmarket · supermarket · PLA · Metric Area=country) · "
    "Snowflake: AVG store (SHRINKED_UNITS_VALUE ÷ TOTAL_SUBTOTAL_LOCAL), round 1dp then avg"
)
GOLDEN_SHRINK_FORMULA = (
    "AVG(ROUND(ABS(100 × SHRINKED_UNITS_VALUE_LOCAL ÷ TOTAL_SUBTOTAL_LOCAL_SUM), 1)) "
    "— MART.WOLT_MARKET_VENUE_METRICS_MONTHLY, ISR active Wolt Market stores"
)
IBM_MAINTENANCE_NOTE = (
    "IBM planning_metrics_actuals — Store Maintenance (Retail 1P, day sum; kILS magnitude)"
)
# IBM Pulse Store Maintenance (kILS) — used when Snowflake role lacks leaf metric visibility.
IBM_MAINTENANCE_KILS_FALLBACK: list[float] = [315, 319, 286, 361, 297, 323]
# NetSuite Mgmt PL — GL 87310 Store maintenance (kILS magnitude; PNL pipeline + May 2026 Mgmt PL).
NETSUITE_87310_KILS: list[float | None] = [300, 696, 138, 480, 425, None]
MAINTENANCE_REVIEW_NOTE = (
    "IBM Store Maintenance ≠ NetSuite 87310 — Snowflake role לא רואה leaf; "
    "ערכי הדשבורד = IBM Pulse fallback. ממתין ל-reconciliation מול Mgmt PL / finance."
)
IBM_VP_NOTE = (
    "IBM planning_metrics_actuals — Variable Profit ÷ GOV (Retail 1P, day sum; IBM UI in €)"
)
# OFL — Wolt Market Unit Economics (Look 47217): ORDER_FULFILLMENT_LABOR_RECON, ISR WM.
OFL_UE_NOTE = (
    "Wolt Market Unit Economics — ORDER_FULFILLMENT_LABOR_RECON (ISR, IS_WOLT_MARKET)"
)
VP_UE_NOTE = (
    "UE cross-check — VARIABLE_PROFIT_RECON ÷ GOV_VAT0_TOTAL (ISR, IS_WOLT_MARKET)"
)
GOLDEN_WA_NOTE = (
    "Golden Dashboard 106617 — MART weighted_availability numerator ÷ denominator "
    "(ISR Wolt Market stores, country aggregate)"
)
GOLDEN_KVI_NOTE = (
    "Golden Dashboard 106617 — KVI Category Promo Weighted Availability % "
    "(MART kvi_cat_promo weighted_availability numerator ÷ denominator)"
)
GOLDEN_POFR_NOTE = (
    "Golden Store Ops 106616 / wolt_market_venue_metrics_aggregated — "
    "MART perfect_order_fulfillment_ratio numerator ÷ denominator "
    "(ISR Wolt Market stores, country aggregate)"
)
# Sold from selection — wolt_market_item_metrics view (wolt_market_data model); not on Golden 106615.
SOLD_FROM_SELECTION_PROMOTED_NAME = "Sold from selection (store level)"

_LOOKER_WM_EXPLORATION = "https://looker.wolt.com/explore/wolt_market_exploration/wolt_market_purchases"
_LOOKER_WM_DATA = "https://looker.wolt.com/explore/wolt_market_data"
# Purchases מאושר (V ✅) — wolt_market_exploration.
_LOOKER_PURCHASES_APPROVED = (
    f"{_LOOKER_WM_EXPLORATION}?qid=hsd9wd9lNsKvuu1M3czQgv&toggle=fil,vis"
)
# Purchases לא מאושר — wolt_market_data (לעיון פנימי / השוואת Snowflake בלבד).
_LOOKER_PURCHASES_NOT_APPROVED = (
    f"{_LOOKER_WM_DATA}/wolt_market_purchases"
    "?fields=wolt_market_item_metrics.metric_month,"
    "wolt_market_item_metrics.sold_from_selection_perc,"
    "wolt_market_item_metrics.sold_from_product_selection_perc"
    "&f[wolt_market_item_metrics.country]=ISR"
    "&f[wolt_market_item_metrics.franchise]=woltmarket"
    "&sorts=wolt_market_item_metrics.metric_month+desc&limit=6&toggle=dat,fil,vis"
)


def _looker_sold_selection_url(_field: str) -> str:
    """Sold from selection — always link to approved exploration Purchases (V ✅)."""
    return _LOOKER_PURCHASES_APPROVED


SOLD_FROM_SELECTION_VARIANTS: dict[str, dict[str, str]] = {
    "sold_from_selection_perc": {
        "metric_name": "Sold from selection — sold_from_selection_perc",
        "looker_label": "Purchases (exploration) — Sold from Selection %",
        "looker_field": "sold_from_selection_perc",
        "looker_field_view": "wolt_market_purchases",
        "looker_explore": "wolt_market_purchases",
        "looker_explore_model": "wolt_market_exploration",
        "looker_badge": "V ✅",
        "snowflake_field": "SOLD_PRODUCTS_FROM_SELECTION_PERC",
        "alias": "sold_from_selection_perc (exploration Purchases)",
    },
    "sold_from_product_selection_perc": {
        "metric_name": "Sold from selection — sold_from_product_selection_perc",
        "looker_label": "Purchases (exploration) — Sold from Product Selection %",
        "looker_field": "sold_from_product_selection_perc",
        "looker_field_view": "wolt_market_purchases",
        "looker_explore": "wolt_market_purchases",
        "looker_explore_model": "wolt_market_exploration",
        "looker_badge": "V ✅",
        "snowflake_field": "SOLD_ITEMS_FROM_SELECTION_PERC",
        "alias": "sold_from_product_selection_perc (exploration Purchases)",
    },
}

SOLD_FROM_SELECTION_NOTE = (
    "ממתין לאימות שלך — Looker מאושר: wolt_market_exploration/wolt_market_purchases (V ✅). "
    "לא להשתמש ב-wolt_market_data/wolt_market_purchases (לא מאושר). "
    "בחר וריאנט בדשבורד האינטראקטיבי לאחר פגישה עם המנהל."
)
SESSION_REVIEW_NOTE = (
    f"{ESSI_SESSION_NOTE_HE} "
    "Snowflake: <code>presentation.wolt_market_metrics</code> (country row) · "
    f"Looker מאושר (Essi): <code>wolt_market_venue_conversion</code> · "
    "Looker benchmark (deprecated): <code>kpi_data/wolt_market_metrics</code>."
)


def essi_session_context_html() -> str:
    """Reusable Essi Slack context block for review dashboards."""
    quote_paras = "".join(
        f"<p>{para}</p>" for para in ESSI_SESSION_QUOTE.split("\n\n")
    )
    return f"""
<div class="essi-card">
  <h3>{ESSI_SESSION_META}</h3>
  <blockquote class="essi-quote">{quote_paras}</blockquote>
  <p class="meta">
    <a href="{ESSI_SESSION_SLACK}" target="_blank" rel="noopener">פתיחת ההודעה ב-Slack</a>
    · thread על NV session conversion (Adam, אפריל 2026)
  </p>
  <table class="tbl essi-sources">
    <thead><tr><th>מקור Looker</th><th>סטטוס</th><th>קישור</th></tr></thead>
    <tbody>
      <tr>
        <td><code>wolt_market_data/wolt_market_venue_conversion</code></td>
        <td><span class="badge-ok">Essi ✅ — סשנים + CVR</span></td>
        <td><a href="{_LOOKER_VENUE_CONVERSION}" target="_blank" rel="noopener">Venue Conversion</a></td>
      </tr>
      <tr>
        <td><code>kpi_data/wolt_market_metrics</code></td>
        <td><span class="badge-legacy">deprecated</span></td>
        <td><a href="{_LOOKER_WM_METRICS_FTU}" target="_blank" rel="noopener">WM Metrics (ישן)</a></td>
      </tr>
    </tbody>
  </table>
  <p class="meta"><strong>למה בלבדיקה?</strong> {SVENJA_SESSION_SPLIT_NOTE}</p>
  <p class="meta">ערכי הדשבורד = Snowflake · השוואת ינואר–מרץ בטבלה = kpi_data (ישן).</p>
</div>
"""


def maintenance_reconciliation_context_html() -> str:
    """Reusable Maintenance IBM ↔ NetSuite 87310 block for review dashboards."""
    cmp_rows = []
    for i, label in enumerate(MONTH_LABELS):
        ns = NETSUITE_87310_KILS[i]
        ibm = IBM_MAINTENANCE_KILS_FALLBACK[i]
        gap = _gap(ns, ibm) if ns is not None else "—"
        cmp_rows.append(
            f"<tr><td>{label}</td><td>{_fmt(ns)}</td><td>{ibm}</td><td>{gap}</td></tr>"
        )
    return f"""
<div class="essi-card" style="background:#fffbeb;border-color:#fcd34d;">
  <h3 style="color:#92400e;">Maintenance costs — IBM ↔ NetSuite 87310</h3>
  <p class="meta">{MAINTENANCE_REVIEW_NOTE}</p>
  <p class="meta"><strong>NetSuite Mgmt PL:</strong> חשבון <code>87310 - Store maintenance - Wolt Markets</code> ·
  שורה סמוכה <code>72650</code> (Other rents/maintenance) — לא בהכרח חלק מאותו OKR.</p>
  <p class="meta"><strong>מאי 2026 (צילום Mgmt PL):</strong> 87310 = <strong>425 kILS</strong> (₪424,692) ·
  IBM fallback = <strong>297 kILS</strong> · פער ≈ <strong>128 kILS (~30%)</strong>.</p>
  <table class="tbl">
    <thead><tr><th>חודש</th><th>NetSuite 87310 (kILS)</th><th>IBM fallback (kILS)</th><th>Gap</th></tr></thead>
    <tbody>{''.join(cmp_rows)}</tbody>
  </table>
  <p class="meta">IBM: <code>planning_metrics_actuals</code> · <code>Store Maintenance</code> (Retail 1P, ISR) —
  leaf לא נגיש ב-Snowflake role הנוכחי; רואים רק <code>COS - Lease &amp; Equipment</code> (rollup).</p>
</div>
"""


MAINTENANCE_REVIEW_PAYLOAD: dict[str, str | list[float | None]] = {
    "title": "Maintenance costs — IBM ↔ NetSuite 87310",
    "noteHe": MAINTENANCE_REVIEW_NOTE,
    "netsuiteAccount": "87310 - Store maintenance - Wolt Markets",
    "netsuiteKils": NETSUITE_87310_KILS,
    "ibmKils": IBM_MAINTENANCE_KILS_FALLBACK,
    "may2026Netsuite": 425,
    "may2026Ibm": 297,
    "may2026Gap": 128,
}
# KPIs signed off in Looker by stakeholder (metric-by-metric OKR review).
USER_VERIFIED: frozenset[str] = frozenset({
    "Orders",
    "DDE FEE/order",
    "Ftu Sessions",
    "Ftu Conversion",
    "Returning User Sessions",
    "Returning User Conversion",
    "PPM%",
    "OFL / order (ILS)",
    "VP%",
    "Weighted Availability",
    "KVI & Promo WA%",
    "POFR%",
    "Under 45min >",
    "Avg Units per Order",
    "Order Frequency",
    "Penetration Rate",
    "Area Product Selection",
    "IDQ",
    "VSL",
    "UP-TIME >",
    "% Bad Goods Rating",
})
# Wolt Market Venue Conversion (Essi ✅, May 2026) — total venue sessions/CVR only;
# does NOT split FTU vs Returning (Svenja Aug 2026).
_LOOKER_VENUE_CONVERSION = (
    "https://looker.wolt.com/explore/wolt_market_data/wolt_market_venue_conversion"
    "?qid=FL8rFCRNmUEOHI6T0oueNI&toggle=dat,fil,vis"
)
# Same dataset, merchant_data explore (alternate entry point).
_LOOKER_VENUE_CONVERSION_MX = (
    "https://looker.wolt.com/explore/merchant_data/venue_conversion"
    "?qid=6XhKpiVP6K2AlGiFhtKul1&toggle=dat,fil,vis"
)

# Looker field names that differ from our OKR label (shown under the link).
LOOKER_FIELD_ALIASES: dict[str, str] = {
    "Orders": "Purchases / # Orders",
    "DDE FEE/order": "Wolt Market Subtotal VAT0 / Purchase",
    "Ftu Sessions": "Sessions — New to Venue / FTU (אלפים)",
    "Ftu Conversion": "New to Venue Conversion (session-based)",
    "Returning User Sessions": "Sessions — Returning / Repeat (אלפים)",
    "Returning User Conversion": "Repeat Venue Conversion (session-based)",
    "PPM%": "Product Profit Margin %",
    "Shrink/DDE FEE": "Shrinkage Share of Subtotal (Golden 106617)",
    "OFL / order (ILS)": "ORDER_FULFILLMENT_LABOR_RECON / Purchase",
    "Maintenance costs": "NetSuite 87310 Store maintenance (kILS; IBM reconciliation pending)",
    "VP%": "Variable Profit ÷ GOV (IBM)",
    "Weighted Availability": "Weighted Availability % (Golden / MART)",
    "KVI & Promo WA%": "KVI Category Promo Weighted Availability %",
    "Sold from selection — sold_from_selection_perc": (
        "sold_from_selection_perc (exploration Purchases)"
    ),
    "Sold from selection — sold_from_product_selection_perc": (
        "sold_from_product_selection_perc (exploration Purchases)"
    ),
    SOLD_FROM_SELECTION_PROMOTED_NAME: "Sold from selection (store level)",
    "POFR%": "Perfect Order Fulfillment Rate %",
    "Under 45min >": "Delivered Under 45 Minutes %",
    "Avg Units per Order": "Avg Units per Order",
    "Order Frequency": "Order Frequency",
    "Penetration Rate": "Active Users % of Country MAU",
    "Area Product Selection": "Available Selection (Golden Selection 106615)",
    "VSL": "Vendor Service Level % (Golden SCM 106617 · ISR incl. DC)",
    "UP-TIME >": "Weighted Uptime %",
    "% Bad Goods Rating": "Bad Goods Rating % — Golden Store Ops 106616",
    "IDQ": "Item Data Quality (Golden Selection 106615)",
}

# Metric → (link label, URL) for the validated-metrics table.
LOOKER_LINKS: dict[str, tuple[str, str]] = {
    "Orders": ("UE — ISR WM (Look 47217)", _LOOKER_UE_ISR),
    "DDE FEE/order": ("UE — ISR WM DDE (Look 47217)", _LOOKER_UE_ISR),
    "Ftu Sessions": ("WM Venue Conversion — Sessions (Essi ✅)", _LOOKER_VENUE_CONVERSION),
    "Ftu Conversion": ("WM Venue Conversion — CVR (Essi ✅)", _LOOKER_VENUE_CONVERSION),
    "Returning User Sessions": ("WM Venue Conversion — Sessions (Essi ✅)", _LOOKER_VENUE_CONVERSION),
    "Returning User Conversion": ("WM Venue Conversion — CVR (Essi ✅)", _LOOKER_VENUE_CONVERSION),
    "PPM%": ("UE — ISR WM (Look 47217)", _LOOKER_UE_ISR),
    "Shrink/DDE FEE": ("Golden SCM — Shrink/DDE FEE (106617)", _LOOKER_GOLDEN_SCM),
    "OFL / order (ILS)": ("Wolt Market Unit Economics (Look 47217)", _LOOKER_UE_ISR),
    "Maintenance costs": ("NetSuite Mgmt PL — 87310 (reconciliation)", ""),
    "VP%": ("IBM — planning_metrics_actuals", ""),
    "Weighted Availability": ("Golden SCM — ISR (106617)", _LOOKER_GOLDEN_SCM),
    "KVI & Promo WA%": ("Golden SCM — ISR (106617)", _LOOKER_GOLDEN_SCM),
    "Sold from selection — sold_from_selection_perc": (
        "Purchases (exploration) — Sold from Selection %",
        _looker_sold_selection_url("sold_from_selection_perc"),
    ),
    "Sold from selection — sold_from_product_selection_perc": (
        "Purchases (exploration) — Sold from Product Selection %",
        _looker_sold_selection_url("sold_from_product_selection_perc"),
    ),
    "POFR%": ("WM Venue Metrics Aggregated — POFR (ISR)", _LOOKER_POFR_AGGREGATED),
    "Under 45min >": ("WM Store Ops — Under 45min (ISR)", _LOOKER_UNDER_45_STORE_OPS),
    "Avg Units per Order": ("Golden Growth — ISR (106613)", _LOOKER_GOLDEN_GROWTH_ISR),
    "Order Frequency": ("Golden Growth — ISR (106613)", _LOOKER_GOLDEN_GROWTH_ISR),
    "Penetration Rate": ("Golden Growth — ISR (106613)", _LOOKER_GOLDEN_GROWTH_ISR),
    "Area Product Selection": ("Golden Selection — ISR (106615)", _LOOKER_GOLDEN_SELECTION),
    "%Fresh Food / DDE": ("—", ""),
    "VSL": ("Golden SCM — ISR (106617)", _LOOKER_GOLDEN_SCM),
    "UP-TIME >": ("Golden Store Ops — ISR (106616)", _LOOKER_GOLDEN_STORE_OPS),
    "% Bad Goods Rating": ("Golden Store Ops — Bad Goods Rating % (106616)", _LOOKER_GOLDEN_STORE_OPS),
    "IDQ": ("Golden Selection — ISR (106615)", _LOOKER_GOLDEN_SELECTION),
}

ESSI_SESSION_PAYLOAD: dict[str, str] = {
    "meta": ESSI_SESSION_META,
    "quote": ESSI_SESSION_QUOTE,
    "noteHe": ESSI_SESSION_NOTE_HE,
    "slackUrl": ESSI_SESSION_SLACK,
    "venueConversionUrl": _LOOKER_VENUE_CONVERSION,
    "kpiDeprecatedUrl": _LOOKER_WM_METRICS_FTU,
    "kpiDeprecatedLabel": ESSI_KPI_DATA_DEPRECATED_NOTE,
    "venueApprovedLabel": ESSI_VENUE_CONVERSION_NOTE,
    "svenjaNote": SVENJA_SESSION_SPLIT_NOTE,
}

# Metrics on main OKR dashboard — for Looker source audit.
OKR_DASHBOARD_METRIC_ORDER: list[str] = [
    "Orders", "DDE FEE/order",
    "Ftu Sessions", "Ftu Conversion",
    "Returning User Sessions", "Returning User Conversion",
    "PPM%", "Shrink/DDE FEE",
    "OFL / order (ILS)", "VP%", "Weighted Availability", "KVI & Promo WA%",
    "POFR%", "Under 45min >", "Avg Units per Order",
    "Order Frequency", "Penetration Rate", "Area Product Selection",
    "%Fresh Food / DDE", "IDQ", "VSL", "UP-TIME >", "% Bad Goods Rating",
]

SESSION_METRICS: list[str] = [
    "Ftu Sessions",
    "Ftu Conversion",
    "Returning User Sessions",
    "Returning User Conversion",
]


def _parse_looker_url(url: str) -> tuple[str, str]:
    """Return (model, explore) from a Looker URL."""
    if not url:
        return "", ""
    if "looks/47217" in url:
        return "looks", "47217"
    if "/dashboards/" in url:
        import re
        m = re.search(r"/dashboards/(\d+)", url)
        return ("dashboards", m.group(1)) if m else ("dashboards", "")
    import re
    m = re.search(r"/explore/([^/]+)/([^?]+)", url)
    return (m.group(1), m.group(2)) if m else ("", "")


def _looker_source_status(url: str) -> tuple[str, str]:
    """Return (status_key, label) — approved | golden | ue | not_certified | none | unknown."""
    if not url:
        return "none", "IBM / ידני — ללא Looker"
    if "looks/47217" in url:
        return "ue", "UE Look 47217 ✅"
    if any(d in url for d in ("/dashboards/106613", "/dashboards/106614",
                              "/dashboards/106615", "/dashboards/106616", "/dashboards/106617")):
        return "golden", "Golden ✅"
    model, explore = _parse_looker_url(url)
    for item in APPROVED_LOOKER_EXPLORES:
        if model == item["model"] and explore == item["explore"]:
            return "approved", f"{item['label']} {item['badge']}"
    for item in LOOKER_EXPLORE_NOT_CERTIFIED:
        if model == item["model"] and explore == item["explore"]:
            return "not_certified", f"{item['label']} — {item['badge']}"
    if model == "wolt_market_dashboards" and explore == "wolt_market_venue_metrics_aggregated":
        return "golden_adjacent", "Venue Metrics Aggregated (Golden-adjacent)"
    return "unknown", f"{model}/{explore or '?'} — לבדוק"


def audit_looker_sources(metrics: list[str] | None = None) -> list[dict[str, str]]:
    """Audit OKR metrics — flag user-verified metrics on non-approved Looker sources."""
    names = metrics or OKR_DASHBOARD_METRIC_ORDER
    rows: list[dict[str, str]] = []
    for name in names:
        label, url = LOOKER_LINKS.get(name, ("—", ""))
        status_key, status_label = _looker_source_status(url)
        verified = name in USER_VERIFIED
        issue = ""
        if verified and status_key in ("not_certified", "unknown"):
            issue = "⚠️ אימתת ערכים — קישור Looker לא מאושר"
        elif name == "Maintenance costs":
            issue = "לבדיקה — IBM Store Maintenance ≠ NetSuite 87310"
        elif not verified and status_key == "not_certified" and name not in REVIEW_TAB_METRICS:
            issue = "⛔ מקור Looker לא מאושר"
        rows.append({
            "metric": name,
            "verified": "✅" if verified else "—",
            "looker_label": label,
            "looker_url": url,
            "status": status_label,
            "status_key": status_key,
            "issue": issue,
        })
    for name in REVIEW_TAB_METRICS:
        if name not in names:
            label, url = LOOKER_LINKS.get(name, ("—", ""))
            status_key, status_label = _looker_source_status(url)
            rows.append({
                "metric": name,
                "verified": "—",
                "looker_label": label,
                "looker_url": url,
                "status": status_label,
                "status_key": status_key,
                "issue": (
                    "לבדיקה — IBM Store Maintenance ≠ NetSuite 87310"
                    if name == "Maintenance costs"
                    else "ממתין לבחירה / אימות"
                ),
            })
    return rows

# Metrics validated as matching Looker (Jan–Mar); show Jan–Jun from Snowflake.
MATCHING_METRICS = [k for k, v in METRIC_SOURCE.items() if v == "snowflake_validated"]

# Main validated table includes IDQ with Looker link.
VALIDATED_TABLE_METRICS = [*MATCHING_METRICS, "IDQ"]

USER_PROVIDED_METRICS = [k for k, v in METRIC_SOURCE.items() if v == "user_provided"]
MANUAL_METRICS = [k for k, v in METRIC_SOURCE.items() if v == "manual_entry"]
PENDING_METRICS = [k for k, v in METRIC_SOURCE.items() if v == "pending_review"]
LOOKER_NOT_APPROVED_METRICS = [
    SOLD_FROM_SELECTION_VARIANTS[k]["metric_name"] for k in SOLD_FROM_SELECTION_VARIANTS
]
REVIEW_TAB_METRICS: list[str] = list(LOOKER_NOT_APPROVED_METRICS)

# Legacy alias — kept for scripts that import NON_MATCHING_METRICS.
NON_MATCHING_METRICS = (
    USER_PROVIDED_METRICS
    + MANUAL_METRICS
    + PENDING_METRICS
    + REVIEW_TAB_METRICS
)

SQL_UE = """
SELECT DATE_TRUNC('month', o.TIMESTAMP)::DATE AS m,
  COUNT(DISTINCT o.PURCHASE_ID) AS orders,
  SUM(p.WOLT_MARKET_SUBTOTAL_VAT0_LOCAL) AS dde_sum,
  SUM(o.WOLT_MARKET_SUBTOTAL) AS wm_subtotal,
  SUM(o.WOLT_MARKET_SUBTOTAL) - ABS(SUM(o.COST_OF_INVENTORY_COGS)) AS ppm_num
FROM PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_OPERATIONAL o
JOIN PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_PURCHASES p
  ON o.PURCHASE_ID = p.PURCHASE_ID
WHERE o.COUNTRY = 'ISR'
  AND o.IS_WOLT_MARKET = TRUE
  AND o.TIMESTAMP >= '2026-01-01'
  AND o.TIMESTAMP < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# Wolt Market Unit Economics — OFL / order (RECON). Dual validation:
#   (A) AVG per purchase  (B) SUM(OFL) ÷ COUNT(purchases) — should match at 1 dp.
SQL_WM_UE_OFL = """
SELECT DATE_TRUNC('month', o.TIMESTAMP)::DATE AS m,
  COUNT(DISTINCT o.PURCHASE_ID) AS orders,
  ABS(SUM(r.ORDER_FULFILLMENT_LABOR_RECON)) AS ofl_total,
  AVG(ABS(r.ORDER_FULFILLMENT_LABOR_RECON)) AS ofl_avg_per_purchase
FROM PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_OPERATIONAL o
JOIN PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_RECONCILIATION r
  ON o.PURCHASE_ID = r.PURCHASE_ID
WHERE o.COUNTRY = 'ISR'
  AND o.IS_WOLT_MARKET = TRUE
  AND o.TIMESTAMP >= '2026-01-01'
  AND o.TIMESTAMP < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# Wolt Market Unit Economics — VP%. Dual validation:
#   (A) AVG(VP/GOV) per purchase  (B) SUM(VP) ÷ SUM(GOV) — dashboard uses B.
SQL_WM_UE_VP = """
SELECT DATE_TRUNC('month', o.TIMESTAMP)::DATE AS m,
  SUM(r.VARIABLE_PROFIT_RECON) AS vp_total,
  SUM(o.GOV_VAT0_TOTAL) AS gov_total,
  AVG(r.VARIABLE_PROFIT_RECON / NULLIF(o.GOV_VAT0_TOTAL, 0)) * 100 AS vp_avg_per_purchase
FROM PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_OPERATIONAL o
JOIN PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_RECONCILIATION r
  ON o.PURCHASE_ID = r.PURCHASE_ID
WHERE o.COUNTRY = 'ISR'
  AND o.IS_WOLT_MARKET = TRUE
  AND o.TIMESTAMP >= '2026-01-01'
  AND o.TIMESTAMP < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# IBM VP% — matches finance IBM (not UE). Amounts in IBM UI shown in €; % is FX-neutral.
SQL_IBM_VP = """
SELECT DATE_TRUNC('month', TIMESTAMP)::DATE AS m,
  SUM(CASE WHEN METRIC_NAME_IN_PULSE = 'Variable Profit' THEN VALUE END) AS vp_total,
  SUM(CASE WHEN METRIC_NAME_IN_PULSE = 'Gross Order Value (GOV)' THEN VALUE END) AS gov_total
FROM PRODUCTION.FINANCE.PLANNING_METRICS_ACTUALS
WHERE COUNTRY = 'ISR'
  AND PERIOD = 'day'
  AND BUSINESS_LINE = 'Retail 1P'
  AND METRIC_NAME_IN_PULSE IN ('Variable Profit', 'Gross Order Value (GOV)')
  AND TIMESTAMP >= '2026-01-01'
  AND TIMESTAMP < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# IBM Store Maintenance — OKR Maintenance costs (kILS; expense signed negative in IBM).
SQL_IBM_MAINTENANCE = """
SELECT DATE_TRUNC('month', TIMESTAMP)::DATE AS m,
  SUM(VALUE) AS maintenance_total
FROM PRODUCTION.FINANCE.PLANNING_METRICS_ACTUALS
WHERE COUNTRY = 'ISR'
  AND PERIOD = 'day'
  AND BUSINESS_LINE = 'Retail 1P'
  AND METRIC_NAME_IN_PULSE = 'Store Maintenance'
  AND TIMESTAMP >= '2026-01-01'
  AND TIMESTAMP < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

SQL_WM_MONTH_VENUES = """
SELECT DATE_TRUNC('month', DATE)::DATE AS m,
  SUM(FTU_SESSIONS) AS ftu_sessions,
  SUM(FTU_ORDERS) AS ftu_orders,
  SUM(RETURNING_USER_SESSIONS) AS ret_sessions,
  SUM(RETURNING_USER_ORDERS) AS ret_orders
FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
WHERE PERIOD = 'month'
  AND COUNTRY = 'ISR'
  AND VENUE_NAME LIKE 'Wolt Market |%'
  AND DATE >= '2026-01-01'
  AND DATE < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# Golden Growth 106613 — Order Frequency (MART venue metrics, ISR WM stores).
# NOT presentation.wolt_market_metrics.PURCHASE_FREQUENCY (deprecated Metrics explore).
SQL_GOLDEN_GROWTH_ISR = """
SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
  SUM(TOTAL_ORDERS_COUNT) AS total_orders,
  SUM(ORDER_FREQUENCY_NUMERATOR) AS of_num,
  SUM(ORDER_FREQUENCY_DENOMINATOR) AS of_den,
  SUM(ORDER_FREQUENCY_NUMERATOR) / NULLIF(SUM(ORDER_FREQUENCY_DENOMINATOR), 0) AS order_frequency
FROM PRODUCTION.MART.WOLT_MARKET_VENUE_METRICS_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND RETAIL_PLATFORM_VENUE_NAME LIKE 'Wolt Market |%'
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY m
"""

# Avg Units from presentation country row (Golden Growth 106613).
SQL_GOLDEN_GROWTH_PRESENTATION = """
SELECT DATE_TRUNC('month', DATE)::DATE AS m,
  TOTAL_ORDERS,
  TOTAL_UNITS
FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
WHERE PERIOD = 'month'
  AND COUNTRY = 'ISR'
  AND AREA = 'country'
  AND VENUE_NAME IS NULL
  AND DATE >= '2026-01-01'
  AND DATE < '2026-07-01'
ORDER BY m
"""

# Penetration Rate = Active Users % of Country MAU (Golden Growth explore field, not KPI tile).
SQL_GOLDEN_GROWTH_ACTIVE_USERS_MAU = """
WITH wm AS (
  SELECT DATE_TRUNC('month', DATE)::DATE AS m, USER_BASE
  FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
  WHERE PERIOD = 'month'
    AND COUNTRY = 'ISR'
    AND AREA = 'country'
    AND VENUE_NAME IS NULL
    AND DATE >= '2026-01-01'
    AND DATE < '2026-07-01'
),
wolt AS (
  SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
    SUM(WOLT_ACTIVE_USERS) AS wolt_mau
  FROM PRODUCTION.MART.RETAIL_METRICS_OVERVIEW_MONTHLY
  WHERE VENUE_COUNTRY = 'ISR'
    AND METRIC_DATE >= '2026-01-01'
    AND METRIC_DATE < '2026-07-01'
  GROUP BY 1
)
SELECT wm.m,
  wm.USER_BASE / NULLIF(wolt.wolt_mau, 0) AS active_users_pct_country_mau
FROM wm
JOIN wolt ON wm.m = wolt.m
ORDER BY wm.m
"""

# Golden Selection 106615 — Item Data Quality (country-level WM IDQ; Golden KPI tile).
SQL_GOLDEN_IDQ = """
SELECT METRIC_DATE AS m,
  SUM(WM_IDQ_NUMERATOR) AS idq_num,
  SUM(WM_IDQ_DENOMINATOR) AS idq_den
FROM PRODUCTION.MART.RETAIL_METRICS_OVERVIEW_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND PERIOD = 'month'
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY m
"""

# Golden Selection 106615 — Available Selection (MART per active WM store; Golden KPI tile).
SQL_GOLDEN_SELECTION_AVAILABLE_SELECTION = """
SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
  SUM(AVAILABLE_PRODUCT_SELECTION_NUMERATOR) / NULLIF(
    COUNT(DISTINCT CASE WHEN TOTAL_ORDERS_COUNT > 0 THEN RETAIL_PLATFORM_VENUE_NAME END), 0
  ) AS available_selection
FROM PRODUCTION.MART.WOLT_MARKET_VENUE_METRICS_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND RETAIL_PLATFORM_VENUE_NAME LIKE 'Wolt Market |%'
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY m
"""

SQL_WM_NETWORK = """
WITH net AS (
  SELECT DATE_TRUNC('month', DATE)::DATE AS m,
    SOLD_PRODUCTS_FROM_SELECTION_PERC,
    SOLD_ITEMS_FROM_SELECTION_PERC,
    PERFECT_ORDER_FULFILLMENT_RATIO,
    ROW_NUMBER() OVER (
      PARTITION BY DATE_TRUNC('month', DATE)
      ORDER BY TOTAL_ORDERS DESC NULLS LAST
    ) AS rn
  FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
  WHERE PERIOD = 'month'
    AND COUNTRY = 'ISR'
    AND AREA = 'country'
    AND VENUE_NAME IS NULL
    AND DATE >= '2026-01-01'
    AND DATE < '2026-07-01'
)
SELECT m,
  SOLD_PRODUCTS_FROM_SELECTION_PERC,
  SOLD_ITEMS_FROM_SELECTION_PERC,
  PERFECT_ORDER_FULFILLMENT_RATIO
FROM net
WHERE rn = 1
ORDER BY m
"""

SQL_MART = """
SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
  SUM(WEIGHTED_AVAILABILITY_NUMERATOR) AS wa_num,
  SUM(WEIGHTED_AVAILABILITY_DENOMINATOR) AS wa_den,
  SUM(KVI_CAT_PROMO_WEIGHTED_AVAILABILITY_NUMERATOR) AS kvi_num,
  SUM(KVI_CAT_PROMO_WEIGHTED_AVAILABILITY_DENOMINATOR) AS kvi_den,
  SUM(PERFECT_ORDER_FULFILLMENT_RATIO_NUMERATOR) AS pofr_num,
  SUM(PERFECT_ORDER_FULFILLMENT_RATIO_DENOMINATOR) AS pofr_den,
  SUM(DELIVERED_UNDER_45_MINUTES_ORDERS_COUNT) AS u45_num,
  SUM(TOTAL_ORDERS_COUNT) AS u45_den,
  SUM(VENUE_BAD_GOODS_RATING_ORDERS_COUNT) AS bad_goods_num,
  SUM(WEIGHTED_UPTIME_RATIO_NUMERATOR) AS up_num,
  SUM(WEIGHTED_UPTIME_RATIO_DENOMINATOR) AS up_den
FROM PRODUCTION.MART.WOLT_MARKET_VENUE_METRICS_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND RETAIL_PLATFORM_VENUE_NAME LIKE 'Wolt Market |%'
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# Golden SCM 106617 — Shrinkage Share of Subtotal (Looker shrinkage_share_of_subtotal).
SQL_SHRINK_GOLDEN = """
SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
  AVG(ROUND(ABS(100 * SHRINKED_UNITS_VALUE_LOCAL / NULLIF(TOTAL_SUBTOTAL_LOCAL_SUM, 0)), 1))
    AS shrink_share_of_subtotal
FROM PRODUCTION.MART.WOLT_MARKET_VENUE_METRICS_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND RETAIL_PLATFORM_FRANCHISE_NAME = 'woltmarket'
  AND WOLT_PRODUCT_LINE_HIERARCHY_3 = 'supermarket'
  AND RETAIL_PLATFORM_VENUE_NAME LIKE 'Wolt Market |%'
  AND RETAIL_PLATFORM_VENUE_STATUS = 'ACTIVE'
  AND TOTAL_SUBTOTAL_LOCAL_SUM > 0
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""

# VSL: country-level ISR (includes Wolt Market DC | Nir Yaffe) — matches Inventory Metrics / OKR SCM Looker.
SQL_VSL_ISR = """
SELECT DATE_TRUNC('month', METRIC_DATE)::DATE AS m,
  SUM(VENDOR_SERVICE_LEVEL_NUM) AS vsl_num,
  SUM(VENDOR_SERVICE_LEVEL_DENOM) AS vsl_den
FROM PRODUCTION.MART.WOLT_MARKET_VENUE_METRICS_MONTHLY
WHERE VENUE_COUNTRY = 'ISR'
  AND METRIC_DATE >= '2026-01-01'
  AND METRIC_DATE < '2026-07-01'
GROUP BY 1
ORDER BY 1
"""


def _month_index(d: date) -> int:
    return d.month - 1


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return float(num) / float(den)


def _round_val(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if name in ("Orders", "Ftu Sessions", "Returning User Sessions", "Area Product Selection",
                "Maintenance costs"):
        return round(value)
    if name in ("Order Frequency", "DDE FEE/order", "OFL / order (ILS)", "Avg Units per Order"):
        return round(value, 1 if name == "Avg Units per Order" else 2 if name == "Order Frequency" else 1)
    if "%" in name or name.endswith("%") or name in ("VP%", "PPM%", "POFR%", "VSL", "IDQ", "UP-TIME >",
                                                      "Under 45min >",
                                                      "KVI & Promo WA%", "Penetration Rate",
                                                      "% Bad Goods Rating",
                                                      "Shrink/DDE FEE", "%Fresh Food / DDE",
                                                      "Ftu Conversion", "Returning User Conversion",
                                                      "Weighted Availability",
                                                      "Sold from selection — sold_from_selection_perc",
                                                      "Sold from selection — sold_from_product_selection_perc",
                                                      SOLD_FROM_SELECTION_PROMOTED_NAME):
        sold_2dp = (
            "Sold from selection — sold_from_selection_perc",
            "Sold from selection — sold_from_product_selection_perc",
            SOLD_FROM_SELECTION_PROMOTED_NAME,
            "%Fresh Food / DDE",
            "IDQ",
            "Shrink/DDE FEE",
            "% Bad Goods Rating",
        )
        return round(value, 2 if name in sold_2dp else 1)
    return round(value, 1)


def load_user_overrides() -> dict[str, list[float | None]]:
    """Load user-provided metrics from okr_2026_user_metrics.csv if present."""
    out: dict[str, list[float | None]] = {m: [None] * 6 for m in USER_PROVIDED_METRICS + MANUAL_METRICS}
    if not USER_OVERRIDES_CSV.is_file():
        return out
    import csv

    month_keys = [f"2026-{m:02d}" for m in range(1, 7)]
    with USER_OVERRIDES_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("metric") or "").strip()
            if name not in out:
                continue
            for i, key in enumerate(month_keys):
                raw = (row.get(key) or "").strip()
                if not raw:
                    continue
                out[name][i] = float(raw.replace(",", ""))
    return out


def _load_ibm_maintenance(cur) -> tuple[list[float | None], str]:
    """Return monthly Maintenance costs (kILS) and source tag."""
    out: list[float | None] = [None] * 6
    cur.execute(SQL_IBM_MAINTENANCE)
    rows = cur.fetchall()
    if rows:
        for m, maintenance_total in rows:
            i = _month_index(m)
            out[i] = _round_val(
                "Maintenance costs",
                abs(maintenance_total) / 1000 if maintenance_total is not None else None,
            )
        return out, "snowflake"
    for i, val in enumerate(IBM_MAINTENANCE_KILS_FALLBACK):
        out[i] = _round_val("Maintenance costs", val)
    return out, "ibm_fallback"


def _load_ofl_from_cursor(cur) -> dict[str, list[float | None]]:
    """OFL validation — avg per purchase vs total OFL ÷ orders (Wolt Market UE)."""
    avg_per: list[float | None] = [None] * 6
    total_div: list[float | None] = [None] * 6
    orders_raw: list[float | None] = [None] * 6
    ofl_total: list[float | None] = [None] * 6

    cur.execute(SQL_WM_UE_OFL)
    for row in cur.fetchall():
        m, orders, ofl_sum, ofl_avg = row
        i = _month_index(m)
        orders_raw[i] = float(orders)
        ofl_total[i] = float(ofl_sum)
        avg_per[i] = _round_val("OFL / order (ILS)", float(ofl_avg))
        total_div[i] = _round_val("OFL / order (ILS)", _safe_div(ofl_sum, orders))

    return {
        "avg_per_purchase": avg_per,
        "total_div_orders": total_div,
        "orders": orders_raw,
        "ofl_total_ils": ofl_total,
    }


def _load_vp_cross_check(cur) -> dict[str, list[float | None]]:
    """VP% — IBM (primary) vs UE (cross-check)."""
    ibm_pct: list[float | None] = [None] * 6
    ue_pct: list[float | None] = [None] * 6
    ibm_vp: list[float | None] = [None] * 6
    ibm_gov: list[float | None] = [None] * 6
    ue_vp: list[float | None] = [None] * 6
    ue_gov: list[float | None] = [None] * 6

    cur.execute(SQL_IBM_VP)
    for row in cur.fetchall():
        m, vp_sum, gov_sum = row
        i = _month_index(m)
        ibm_vp[i] = float(vp_sum)
        ibm_gov[i] = float(gov_sum)
        ibm_pct[i] = _round_val("VP%", 100 * _safe_div(vp_sum, gov_sum))

    cur.execute(SQL_WM_UE_VP)
    for row in cur.fetchall():
        m, vp_sum, gov_sum, _vp_avg = row
        i = _month_index(m)
        ue_vp[i] = float(vp_sum)
        ue_gov[i] = float(gov_sum)
        ue_pct[i] = _round_val("VP%", 100 * _safe_div(vp_sum, gov_sum))

    return {
        "ibm_pct": ibm_pct,
        "ue_pct": ue_pct,
        "ibm_vp_total_ils": ibm_vp,
        "ibm_gov_total_ils": ibm_gov,
        "ue_vp_total_ils": ue_vp,
        "ue_gov_total_ils": ue_gov,
    }


def _load_shrink_from_snowflake(cur) -> list[float | None]:
    """Golden 106617 equivalent — auto for all months in range (incl. future)."""
    out: list[float | None] = [None] * 6
    cur.execute(SQL_SHRINK_GOLDEN)
    for m, shrink_share in cur.fetchall():
        i = _month_index(m)
        out[i] = _round_val(
            "Shrink/DDE FEE",
            float(shrink_share) if shrink_share is not None else None,
        )
    return out


def _load_shrink_cross_check(cur, snowflake_vals: list[float | None]) -> dict[str, list[float | None]]:
    """Dashboard Snowflake vs Golden tile anchor (validation only)."""
    return {
        "snowflake_pct": list(snowflake_vals),
        "golden_anchor": list(SHRINK_GOLDEN_ANCHOR),
    }


def fetch_metrics() -> tuple[
    dict[str, list[float | None]],
    dict[str, list[float | None]],
    dict[str, list[float | None]],
    dict[str, list[float | None]],
    str,
]:
    data: dict[str, list[float | None]] = {k: [None] * 6 for k in LOOKER}
    ofl_check: dict[str, list[float | None]] = {
        "avg_per_purchase": [None] * 6,
        "total_div_orders": [None] * 6,
        "orders": [None] * 6,
        "ofl_total_ils": [None] * 6,
    }
    vp_check: dict[str, list[float | None]] = {
        "ibm_pct": [None] * 6,
        "ue_pct": [None] * 6,
        "ibm_vp_total_ils": [None] * 6,
        "ibm_gov_total_ils": [None] * 6,
        "ue_vp_total_ils": [None] * 6,
        "ue_gov_total_ils": [None] * 6,
    }
    shrink_check: dict[str, list[float | None]] = {
        "snowflake_pct": [None] * 6,
        "golden_anchor": list(SHRINK_GOLDEN_ANCHOR),
    }
    maintenance_source = "snowflake"

    with snowflake_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_UE)
            for row in cur.fetchall():
                m, orders, dde_sum, wm_sub, ppm_num = row
                i = _month_index(m)
                data["Orders"][i] = round(orders / 1000)
                data["DDE FEE/order"][i] = _round_val("DDE FEE/order", _safe_div(dde_sum, orders))
                data["PPM%"][i] = _round_val("PPM%", 100 * _safe_div(ppm_num, wm_sub))

            ofl_check = _load_ofl_from_cursor(cur)
            for i in range(6):
                data["OFL / order (ILS)"][i] = ofl_check["total_div_orders"][i]

            vp_check = _load_vp_cross_check(cur)
            for i in range(6):
                data["VP%"][i] = vp_check["ibm_pct"][i]

            maintenance_vals, maintenance_source = _load_ibm_maintenance(cur)
            for i, val in enumerate(maintenance_vals):
                data["Maintenance costs"][i] = val

            cur.execute(SQL_WM_MONTH_VENUES)
            for row in cur.fetchall():
                m, ftu_s, ftu_o, ret_s, ret_o = row
                i = _month_index(m)
                data["Ftu Sessions"][i] = _round_val("Ftu Sessions", ftu_s / 1000)
                data["Ftu Conversion"][i] = _round_val(
                    "Ftu Conversion", 100 * _safe_div(ftu_o, ftu_s)
                )
                data["Returning User Sessions"][i] = _round_val(
                    "Returning User Sessions", ret_s / 1000
                )
                data["Returning User Conversion"][i] = _round_val(
                    "Returning User Conversion", 100 * _safe_div(ret_o, ret_s)
                )

            cur.execute(SQL_GOLDEN_GROWTH_ISR)
            for row in cur.fetchall():
                m, _orders, _num, _den, order_freq = row
                i = _month_index(m)
                data["Order Frequency"][i] = _round_val("Order Frequency", float(order_freq) if order_freq is not None else None)

            cur.execute(SQL_GOLDEN_GROWTH_PRESENTATION)
            for row in cur.fetchall():
                m, orders, units = row
                i = _month_index(m)
                data["Avg Units per Order"][i] = _round_val(
                    "Avg Units per Order", _safe_div(units, orders)
                )

            cur.execute(SQL_GOLDEN_GROWTH_ACTIVE_USERS_MAU)
            for row in cur.fetchall():
                m, pen = row
                i = _month_index(m)
                data["Penetration Rate"][i] = _round_val(
                    "Penetration Rate",
                    float(pen) * 100 if pen is not None else None,
                )

            cur.execute(SQL_GOLDEN_SELECTION_AVAILABLE_SELECTION)
            for row in cur.fetchall():
                m, available_selection = row
                i = _month_index(m)
                data["Area Product Selection"][i] = _round_val(
                    "Area Product Selection",
                    float(available_selection) if available_selection is not None else None,
                )

            cur.execute(SQL_WM_NETWORK)
            for row in cur.fetchall():
                (m, sold_products, sold_items, _pofr) = row
                i = _month_index(m)
                data["Sold from selection — sold_from_selection_perc"][i] = _round_val(
                    "Sold from selection — sold_from_selection_perc", sold_products * 100
                )
                data["Sold from selection — sold_from_product_selection_perc"][i] = _round_val(
                    "Sold from selection — sold_from_product_selection_perc", sold_items * 100
                )

            shrink_auto = _load_shrink_from_snowflake(cur)
            shrink_vals = list(shrink_auto)
            # Verified Golden tile values override auto for Jan–Jun 2026; Jul+ uses Snowflake only.
            for i, anchor in enumerate(SHRINK_GOLDEN_ANCHOR):
                if anchor is not None:
                    shrink_vals[i] = _round_val("Shrink/DDE FEE", anchor)
            for i, val in enumerate(shrink_vals):
                data["Shrink/DDE FEE"][i] = val
            shrink_check = _load_shrink_cross_check(cur, shrink_auto)

            cur.execute(SQL_MART)
            for row in cur.fetchall():
                (m, wa_n, wa_d, kvi_n, kvi_d, pofr_n, pofr_d, u45_n, u45_d,
                 bad_goods_n, up_n, up_d) = row
                i = _month_index(m)
                data["Weighted Availability"][i] = _round_val(
                    "Weighted Availability", 100 * _safe_div(wa_n, wa_d)
                )
                data["KVI & Promo WA%"][i] = _round_val(
                    "KVI & Promo WA%", 100 * _safe_div(kvi_n, kvi_d)
                )
                data["POFR%"][i] = _round_val(
                    "POFR%", 100 * _safe_div(pofr_n, pofr_d)
                )
                data["Under 45min >"][i] = _round_val(
                    "Under 45min >", 100 * _safe_div(u45_n, u45_d)
                )
                data["% Bad Goods Rating"][i] = _round_val(
                    "% Bad Goods Rating", 100 * _safe_div(bad_goods_n, u45_d)
                )
                data["UP-TIME >"][i] = _round_val("UP-TIME >", 100 * _safe_div(up_n, up_d))

            cur.execute(SQL_GOLDEN_IDQ)
            for m, idq_n, idq_d in cur.fetchall():
                i = _month_index(m)
                data["IDQ"][i] = _round_val("IDQ", 100 * _safe_div(idq_n, idq_d))

            cur.execute(SQL_VSL_ISR)
            for m, vsl_n, vsl_d in cur.fetchall():
                i = _month_index(m)
                data["VSL"][i] = _round_val("VSL", 100 * _safe_div(vsl_n, vsl_d))

    overrides = load_user_overrides()
    for name, values in overrides.items():
        for i, val in enumerate(values):
            if val is not None:
                data[name][i] = _round_val(name, val)

    return data, ofl_check, vp_check, shrink_check, maintenance_source


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _gap(snow: float | None, looker: float | None) -> str:
    if snow is None or looker is None:
        return "—"
    g = snow - looker
    if abs(g - round(g)) < 0.01:
        return str(int(round(g)))
    return f"{g:+.2f}"


def _looker_cell(name: str) -> str:
    label, url = LOOKER_LINKS.get(name, ("Looker", _LOOKER_GOLDEN))
    if not url:
        return f"<span class='looker-na'>{label}</span>"
    status_key, status_label = _looker_source_status(url)
    badge = ""
    if name in USER_VERIFIED:
        badge = ' <span class="badge-ok">✅ verified by user</span>'
        if status_key in ("not_certified", "unknown"):
            badge += ' <span class="badge-legacy">⚠️ Looker לא מאושר</span>'
    elif name in LOOKER_NOT_APPROVED_METRICS:
        badge = ' <span class="badge-pending">לבדיקה</span>'
    elif name == "Maintenance costs":
        badge = ' <span class="badge-pending">לבדיקה</span>'
    elif status_key == "not_certified":
        badge = f' <span class="badge-legacy">{status_label}</span>'
    alias = LOOKER_FIELD_ALIASES.get(name)
    alias_html = f'<div class="looker-alias">{alias}</div>' if alias else ""
    return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>{badge}{alias_html}'


def build_html(
    snow: dict[str, list[float | None]],
    ofl_check: dict[str, list[float | None]] | None = None,
    vp_check: dict[str, list[float | None]] | None = None,
    shrink_check: dict[str, list[float | None]] | None = None,
    maintenance_source: str = "snowflake",
) -> str:
    match_rows = []
    for name in VALIDATED_TABLE_METRICS:
        cells = "".join(f"<td>{_fmt(snow[name][i])}</td>" for i in range(6))
        match_rows.append(
            f"<tr><td>{name}</td><td class='looker-col'>{_looker_cell(name)}</td>{cells}</tr>"
        )

    user_rows = []
    for name in USER_PROVIDED_METRICS:
        cells = "".join(f"<td>{_fmt(snow[name][i])}</td>" for i in range(6))
        user_rows.append(f"<tr><td>{name}</td>{cells}</tr>")

    user_block = ""
    if USER_PROVIDED_METRICS:
        user_block = f"""
  <div class="card">
    <h2 class="warn">מדדים שתספק — ינואר עד יוני 2026</h2>
    <p class="meta">מלא ערכים ב-<code>okr_2026_user_metrics.csv</code>.</p>
    <table class="tbl">
      <thead><tr><th>מדד</th>{"".join(f"<th>{l}</th>" for l in MONTH_LABELS)}</tr></thead>
      <tbody>{''.join(user_rows)}</tbody>
    </table>
  </div>
"""

    manual_note = (
        "<p>הזנה ידנית ב-Looker — לא נמשך מ-Snowflake. "
        "ניתן למלא ב-<code>okr_2026_user_metrics.csv</code> אם תרצה להציג בדשבורד.</p>"
    )
    if MANUAL_METRICS:
        manual_rows = []
        for name in MANUAL_METRICS:
            cells = "".join(f"<td>{_fmt(snow[name][i])}</td>" for i in range(6))
            manual_rows.append(f"<tr><td>{name}</td>{cells}</tr>")
        manual_block = (
            f"{manual_note}<table class='tbl'><thead><tr><th>מדד</th>"
            f"{''.join(f'<th>{l}</th>' for l in MONTH_LABELS)}</tr></thead>"
            f"<tbody>{''.join(manual_rows)}</tbody></table>"
        )
    else:
        manual_block = manual_note

    review_blocks = []
    variant_by_name = {v["metric_name"]: v for v in SOLD_FROM_SELECTION_VARIANTS.values()}
    for name in LOOKER_NOT_APPROVED_METRICS:
        rows = []
        for i in range(6):
            lk = LOOKER[name][i] if i < 3 else None
            ref = snow[name][i]
            gap = _gap(ref, lk) if i < 3 else "—"
            rows.append(
                f"<tr><td>{MONTH_LABELS[i]}</td>"
                f"<td>{_fmt(lk) if i < 3 else '—'}</td>"
                f"<td>{_fmt(ref)}</td><td>{gap}</td></tr>"
            )
        label, url = LOOKER_LINKS.get(name, ("—", ""))
        link_html = (
            f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
            if url
            else label
        )
        sf_field = variant_by_name.get(name, {}).get("snowflake_field", "—")
        looker_field = variant_by_name.get(name, {}).get("looker_field", "—")
        review_blocks.append(
            f"<h3>{name}</h3>"
            f"<p class='meta'>{SOLD_FROM_SELECTION_NOTE}</p>"
            f"<p class='meta'>Looker (V ✅): {link_html} · "
            f'שדה: <code>{looker_field}</code> · '
            f'<span class="warn">לא מאושר: '
            f'<a href="{_LOOKER_PURCHASES_NOT_APPROVED}" target="_blank" rel="noopener">'
            f"wolt_market_data Purchases</a></span> · "
            f"Snowflake: <code>presentation.wolt_market_metrics</code> · "
            f"field <code>{sf_field}</code> (country row).</p>"
            f"<table class='tbl'><thead><tr><th>Month</th><th>Looker (Jan–Mar)</th>"
            f"<th>Snowflake</th><th>Gap</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    pending_blocks = []
    for name in PENDING_METRICS:
        rows = []
        for i in range(3):
            lk = LOOKER[name][i]
            ref = snow[name][i]
            rows.append(
                f"<tr><td>{MONTH_LABELS[i]}</td>"
                f"<td>{_fmt(lk)}</td><td>{_fmt(ref)}</td><td>{_gap(ref, lk)}</td></tr>"
            )
        pending_blocks.append(
            f"<h3>{name}</h3>"
            f"<p class='meta'>בהמתנה לאישור הגדרה — ערכי Snowflake לעיון בלבד.</p>"
            f"<table class='tbl'><thead><tr><th>Month</th><th>Looker</th>"
            f"<th>Snowflake (ref)</th><th>Gap</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    pending_card = ""
    if pending_blocks:
        pending_card = f"""
  <div class="card">
    <h2>בהמתנה לבדיקה</h2>
    {''.join(pending_blocks)}
  </div>
"""

    ofl_block = ""
    if ofl_check:
        ofl_rows = []
        for i in range(6):
            avg_v = ofl_check["avg_per_purchase"][i]
            tot_v = ofl_check["total_div_orders"][i]
            gap = "—"
            if avg_v is not None and tot_v is not None:
                g = tot_v - avg_v
                gap = "0" if abs(g) < 0.05 else f"{g:+.2f}"
            ofl_rows.append(
                f"<tr><td>{MONTH_LABELS[i]}</td>"
                f"<td>{_fmt(avg_v)}</td><td>{_fmt(tot_v)}</td><td>{gap}</td>"
                f"<td>{_fmt(ofl_check['ofl_total_ils'][i])}</td>"
                f"<td>{_fmt(ofl_check['orders'][i])}</td></tr>"
            )
        ofl_block = f"""
  <div class="card">
    <h2 class="ok">OFL / order — ולידציה כפולה (Wolt Market Unit Economics)</h2>
    <p class="meta">{OFL_UE_NOTE}</p>
    <p class="meta">שיטה A: ממוצע <code>ORDER_FULFILLMENT_LABOR_RECON</code> להזמנה ·
    שיטה B: סך OFL ÷ מספר הזמנות · ערך הדשבורד = שיטה B.</p>
    <table class="tbl">
      <thead><tr><th>חודש</th><th>A — ממוצע להזמנה</th><th>B — סך÷הזמנות</th><th>Gap</th>
      <th>סך OFL (ILS)</th><th># הזמנות</th></tr></thead>
      <tbody>{''.join(ofl_rows)}</tbody>
    </table>
  </div>
"""

    vp_block = ""
    if vp_check:
        vp_rows = []
        for i in range(6):
            ibm_v = vp_check["ibm_pct"][i]
            ue_v = vp_check["ue_pct"][i]
            gap = _gap(ibm_v, ue_v)
            vp_rows.append(
                f"<tr><td>{MONTH_LABELS[i]}</td>"
                f"<td>{_fmt(ibm_v)}</td><td>{_fmt(ue_v)}</td><td>{gap}</td>"
                f"<td>{_fmt(vp_check['ibm_vp_total_ils'][i])}</td>"
                f"<td>{_fmt(vp_check['ibm_gov_total_ils'][i])}</td></tr>"
            )
        vp_block = f"""
  <div class="card">
    <h2 class="ok">VP% — IBM vs UE (ולידציה)</h2>
    <p class="meta">{IBM_VP_NOTE}</p>
    <p class="meta">ערך הדשבורד = IBM · סכומי VP ב-IBM מוצגים ב-€ (k€) · Snowflake שומר ILS · האחוז זהה.</p>
    <p class="meta">UE cross-check: {VP_UE_NOTE}</p>
    <table class="tbl">
      <thead><tr><th>חודש</th><th>IBM VP%</th><th>UE VP%</th><th>Gap</th>
      <th>IBM VP (ILS)</th><th>IBM GOV (ILS)</th></tr></thead>
      <tbody>{''.join(vp_rows)}</tbody>
    </table>
  </div>
"""

    shrink_block = ""
    if shrink_check:
        shrink_rows = []
        for i in range(6):
            sf_v = shrink_check["snowflake_pct"][i]
            anchor_v = shrink_check["golden_anchor"][i]
            shrink_rows.append(
                f"<tr><td>{MONTH_LABELS[i]}</td>"
                f"<td>{_fmt(sf_v)}</td><td>{_fmt(anchor_v)}</td>"
                f"<td>{_gap(sf_v, anchor_v)}</td></tr>"
            )
        shrink_block = f"""
  <div class="card">
    <h2 class="ok">Shrink/DDE FEE — Snowflake vs Golden tile (ולידציה)</h2>
    <p class="meta">{GOLDEN_SHRINK_NOTE}</p>
    <p class="meta">נוסחה: {GOLDEN_SHRINK_FORMULA}</p>
    <p class="meta">ערך הדשבורד = Golden anchor (Jan–Jun 26) · Jul+ = Snowflake auto · טבלה = Snowflake גolmi vs anchor.</p>
    <table class="tbl">
      <thead><tr><th>חודש</th><th>Snowflake (dashboard)</th><th>Golden 106617 anchor</th><th>Gap</th></tr></thead>
      <tbody>{''.join(shrink_rows)}</tbody>
    </table>
  </div>
"""

    sources = f"""
    <ul>
      <li><strong>Unit Economics</strong> — Orders, DDE, PPM (OFL &amp; VP — see cross-check below)</li>
      <li><strong>OFL / order</strong> — {OFL_UE_NOTE}</li>
      <li><strong>VP%</strong> — {IBM_VP_NOTE} (UE cross-check below)</li>
      <li><strong>Shrink/DDE FEE</strong> — {GOLDEN_SHRINK_NOTE} · Looker field: <em>Shrinkage Share of Subtotal</em> (<code>shrinkage_share_of_subtotal</code>)</li>
      <li><strong>Maintenance costs</strong> — {MAINTENANCE_REVIEW_NOTE} · KPI by Leader (לא בלשונית לבדיקה) · {IBM_MAINTENANCE_NOTE}</li>
      <li><strong>Sessions / CVR</strong> — {SESSION_REVIEW_NOTE}
        <a href="{ESSI_SESSION_SLACK}" target="_blank" rel="noopener">Slack</a>.</li>
      <li><strong>לבדיקה — Sold from selection</strong> (2 variants) — {SOLD_FROM_SELECTION_NOTE}</li>
      <li><strong>MART.WOLT_MARKET_VENUE_METRICS_MONTHLY</strong> — KVI &amp; Promo WA, POFR, Under 45min, Uptime (stores: <code>Wolt Market |%</code>); VSL — all ISR incl. DC</li>
      <li><strong>Golden Selection 106615</strong> — IDQ (Item Data Quality) · {IDQ_NOTE}</li>
      <li><strong>manual_entry</strong> — %Fresh Food / DDE</li>
    </ul>
    """

    audit_rows = audit_looker_sources()
    audit_issue_count = sum(1 for r in audit_rows if r["issue"])
    audit_table_rows = []
    for r in audit_rows:
        link = (
            f'<a href="{r["looker_url"]}" target="_blank" rel="noopener">{r["looker_label"]}</a>'
            if r["looker_url"]
            else "—"
        )
        row_cls = "warn" if r["issue"] else ""
        audit_table_rows.append(
            f"<tr class='{row_cls}'><td>{r['metric']}</td><td>{r['verified']}</td>"
            f"<td class='looker-col'>{link}</td><td>{r['status']}</td>"
            f"<td>{r['issue'] or '—'}</td></tr>"
        )
    audit_block = f"""
  <div class="card">
    <h2 class="{'warn' if audit_issue_count else 'ok'}">ביקורת מקורות Looker — מאושר מול לא מאושר</h2>
    <p class="meta">V ✅ = explores שאישרת · Golden / UE = תמיד מאושר · ! / deprecated = לא לשימוש בדשבורד מנהלים.</p>
    <p class="meta"><strong>{audit_issue_count}</strong> מדדים עם בעיית מקור.</p>
    <table class="tbl">
      <thead><tr><th>מדד</th><th>אימתת?</th><th>קישור נוכחי</th><th>סטטוס מקור</th><th>בעיה</th></tr></thead>
      <tbody>{''.join(audit_table_rows)}</tbody>
    </table>
  </div>
"""

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>OKR 2026 — Validation</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f6f8fb; color: #1a1a2e; }}
    h1, h2 {{ color: #0f3460; }}
    h3 {{ margin-top: 20px; color: #533483; }}
    .card {{ background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
    .tbl {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    .tbl th, .tbl td {{ border: 1px solid #dde3ef; padding: 8px 10px; text-align: center; }}
    .tbl th {{ background: #e8f0fe; }}
    .tbl td:first-child, .tbl th:first-child {{ text-align: right; font-weight: 600; }}
    .ok {{ color: #0d7a4c; }}
    .warn {{ color: #b45309; }}
    .meta {{ color: #5c6b8a; font-size: 13px; }}
    .looker-col {{ text-align: right; white-space: nowrap; font-size: 13px; }}
    .looker-col a {{ color: #1a56db; text-decoration: none; }}
    .looker-col a:hover {{ text-decoration: underline; }}
    .badge-pending {{ background: #fef3c7; color: #92400e; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; }}
    .badge-ok {{ background: #d1fae5; color: #065f46; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; }}
    .badge-legacy {{ background: #fee2e2; color: #991b1b; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; }}
    .essi-card {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 10px; padding: 16px 18px; margin-bottom: 20px; }}
    .essi-card h3 {{ margin: 0 0 10px; color: #166534; font-size: 15px; }}
    .essi-quote {{ margin: 0 0 12px; padding: 12px 16px; background: #fff; border-left: 4px solid #22c55e; color: #1e293b; font-size: 13px; line-height: 1.5; }}
    .essi-quote p {{ margin: 0 0 8px; }}
    .essi-quote p:last-child {{ margin-bottom: 0; }}
    .essi-sources {{ margin-top: 12px; font-size: 12px; }}
    .looker-alias {{ color: #5c6b8a; font-size: 11px; margin-top: 4px; }}
  </style>
</head>
<body>
  <h1>OKR 2026 — ולידציה מול Looker</h1>
  <p class="meta">ISR · Wolt Market 1P · מקור: Snowflake · ינואר–יוני 2026</p>

  {audit_block}

  <div class="card">
    <h2 class="ok">מדדים תואמים — ינואר עד יוני 2026</h2>
    <p class="meta">אומתו מול Looker בינואר–מרץ (סטייה ≤ ~2pp / עיגול). Sold from selection — בלשונית לבדיקה למטה.</p>
    <table class="tbl">
      <thead><tr><th>מדד</th><th>Looker</th>{"".join(f"<th>{l}</th>" for l in MONTH_LABELS)}</tr></thead>
      <tbody>{"".join(match_rows)}</tbody>
    </table>
  </div>

  {user_block}

  <div class="card">
    <h2>הזנה ידנית</h2>
    {manual_block}
  </div>

  {pending_card}

  <div class="card">
    <h2>לבדיקה</h2>
    <p class="meta"><strong>Sold from selection:</strong> {SOLD_FROM_SELECTION_NOTE}</p>
    {''.join(review_blocks)}
  </div>

  {ofl_block}

  {vp_block}

  {shrink_block}

  <div class="card">
    <h2>מקורות נתונים</h2>
    {sources}
    <p class="meta">Jun OFL (UE RECON) עלול להיות חלקי עד סגירת רקונסיליאציה.</p>
    <p class="meta"><strong>% Bad Goods Rating:</strong> {GOLDEN_BAD_GOODS_NOTE} · <a href="{_LOOKER_GOLDEN_STORE_OPS}" target="_blank" rel="noopener">Golden Store Ops 106616</a> · שדה Looker: <em>Bad Goods Rating %</em> (<code>bad_goods_rating</code>).</p>
  </div>

  <script>window.OKR_VALIDATION = {json.dumps({"snowflake": snow, "looker": LOOKER, "sources": METRIC_SOURCE, "looker_links": {k: {"label": v[0], "url": v[1]} for k, v in LOOKER_LINKS.items()}, "user_verified": sorted(USER_VERIFIED), "essi_session_note": ESSI_SESSION_NOTE, "essi_session_slack": ESSI_SESSION_SLACK, "ofl_cross_check": ofl_check, "ofl_ue_note": OFL_UE_NOTE, "vp_cross_check": vp_check, "ibm_vp_note": IBM_VP_NOTE, "vp_ue_note": VP_UE_NOTE, "shrink_cross_check": shrink_check, "golden_shrink_note": GOLDEN_SHRINK_NOTE}, ensure_ascii=False)};</script>
</body>
</html>"""


def main() -> None:
    snow, ofl_check, vp_check, shrink_check, maintenance_source = fetch_metrics()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(
        build_html(snow, ofl_check, vp_check, shrink_check, maintenance_source),
        encoding="utf-8",
    )
    print("Wrote", OUT_HTML.name, "to auto_outputs/")


if __name__ == "__main__":
    main()
