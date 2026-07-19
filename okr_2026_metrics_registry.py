"""OKR 2026 metric master list — leader, partner, data source (from OKR spreadsheet)."""

from __future__ import annotations

from typing import TypedDict


class MetricRow(TypedDict):
    name: str
    leader: str
    partner: str
    source: str  # snowflake | user | manual
    workflow: str  # auto | manual | pending_send | cancelled | pending_impl | yearly


# Main dashboard sheet — blue-highlighted rows in OKR spreadsheet.
MAIN_SHEET_METRICS: list[str] = [
    "Orders",
    "DDE FEE/order",
    "PPM%",
    "Shrink/DDE FEE",
    "OFL / order (ILS)",
    "VP%",
    "Weighted Availability",
    "KVI & Promo WA%",
    "POFR%",
    "Under 45min >",
]

# Leader filter order on KPI BY LEADER tab (no standalone "CAT" — use CAT & Content).
LEADER_ORDER: list[str] = [
    "OPS",
    "CAT & Content",
    "MKT",
    "General",
    "SC",
    "Exp",
    "Marketing",
    "HR",
]

# Leader chip "CAT & Content" includes legacy spreadsheet label "CAT".
LEADER_FILTER_GROUPS: dict[str, list[str]] = {
    "CAT & Content": ["CAT", "CAT & Content"],
}


# Order matches OKR spreadsheet (leader / partner / section).
OKR_METRICS: list[MetricRow] = [
    {"name": "Orders", "leader": "OPS", "partner": "CAT/MKT", "source": "snowflake", "workflow": "auto"},
    {"name": "DDE FEE/order", "leader": "CAT", "partner": "MKT", "source": "snowflake", "workflow": "auto"},
    {"name": "FTU", "leader": "MKT", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "FTU Conversion", "leader": "CAT", "partner": "SC", "source": "snowflake", "workflow": "auto"},
    {"name": "Returning Clients", "leader": "MKT", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Returning Client Conversion", "leader": "CAT", "partner": "SC", "source": "snowflake", "workflow": "auto"},
    {"name": "PPM%", "leader": "CAT", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Shrink/DDE FEE", "leader": "SC", "partner": "CAT/OPS", "source": "snowflake", "workflow": "auto"},
    {"name": "OFL / order (ILS)", "leader": "OPS", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "VP%", "leader": "General", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Weighted Availability", "leader": "SC", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "KVI & Promo WA%", "leader": "SC", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Sold from selection — sold_from_selection_perc", "leader": "CAT & Content", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Sold from selection — sold_from_product_selection_perc", "leader": "CAT & Content", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "POFR%", "leader": "OPS", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Under 45min >", "leader": "OPS", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "New Stores", "leader": "Exp", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Expansion", "leader": "Exp", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Relocation", "leader": "Exp", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Maintenance costs", "leader": "Exp", "partner": "", "source": "manual", "workflow": "pending_send"},
    {"name": "Utilities costs reduce", "leader": "Exp", "partner": "", "source": "manual", "workflow": "yearly"},
    {"name": "Fulfillment & Drive partner", "leader": "Exp", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "3PFL GOV (yearly)", "leader": "Exp", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Robotic store", "leader": "Exp", "partner": "", "source": "manual", "workflow": "cancelled"},
    {"name": "Turning B stores to A", "leader": "Exp", "partner": "OPS", "source": "manual", "workflow": "manual"},
    {"name": "Avg Units per Order", "leader": "Marketing", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Order Frequency", "leader": "Marketing", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Penetration Rate", "leader": "Marketing", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "Awareness", "leader": "Marketing", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "New special vendors or categories", "leader": "CAT & Content", "partner": "", "source": "manual", "workflow": "yearly"},
    {"name": "Area Product Selection", "leader": "CAT & Content", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "%Fresh Food / DDE", "leader": "CAT & Content", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "IDQ", "leader": "CAT & Content", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "VSL", "leader": "CAT & Content", "partner": "SC", "source": "snowflake", "workflow": "auto"},
    {"name": "DC", "leader": "SC", "partner": "", "source": "manual", "workflow": "yearly"},
    {"name": "Forecast accuracy +/-", "leader": "SC", "partner": "", "source": "manual", "workflow": "pending_impl"},
    {"name": "UP-TIME >", "leader": "OPS", "partner": "", "source": "snowflake", "workflow": "auto"},
    {"name": "UPH >", "leader": "OPS", "partner": "SC", "source": "manual", "workflow": "pending_impl"},
    {"name": "% Bad Goods Rating", "leader": "OPS", "partner": "Marketing", "source": "snowflake", "workflow": "auto"},
    {"name": "Average Goods Rating", "leader": "OPS", "partner": "Marketing", "source": "snowflake", "workflow": "auto"},
    {"name": "Attrition (monthly) <", "leader": "OPS", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "IDP & HQ training", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Internal Mobility", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "OPS Training", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Store employees absence <", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Early Attrition (0-3) <", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Engagme >1 (HV)", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "Engagme >1 (HQ)", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
    {"name": "EngagMe growth", "leader": "HR", "partner": "", "source": "manual", "workflow": "manual"},
]

ALL_METRIC_NAMES = [r["name"] for r in OKR_METRICS]
DEFAULT_OWNERS = {r["name"]: {"leader": r["leader"], "partner": r["partner"]} for r in OKR_METRICS}
METRIC_DATA_SOURCE = {r["name"]: r["source"] for r in OKR_METRICS}
METRIC_WORKFLOW = {r["name"]: r["workflow"] for r in OKR_METRICS}

# Sold-from-selection variants live on the review tab only; promoted name goes on main sheet.
_REVIEW_ONLY_METRICS = {
    "FTU",
    "FTU Conversion",
    "Returning Clients",
    "Returning Client Conversion",
    "Sold from selection — sold_from_selection_perc",
    "Sold from selection — sold_from_product_selection_perc",
}

# Legacy WM Metrics — dashboard TO DELETE tab only.
_TO_DELETE_METRICS = {
    "Average Goods Rating",
}

LEADER_SHEET_METRICS: list[str] = [
    r["name"]
    for r in OKR_METRICS
    if r["name"] not in MAIN_SHEET_METRICS
    and r["name"] not in _REVIEW_ONLY_METRICS
    and r["name"] not in _TO_DELETE_METRICS
]
