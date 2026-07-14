"""OKR 2026 ISR Wolt Market — production dashboard table (Jan–Jun 2026).

Single consolidated table for WBR / manager reporting. Reuses Snowflake pulls
from okr_2026_validation.py.

Usage:
  python okr_2026_dashboard.py
  python okr_2026_dashboard.py --skip-fetch   # reuse last validation JSON in HTML
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from okr_2026_validation import (
    ESSI_SESSION_NOTE,
    ESSI_SESSION_SLACK,
    IBM_MAINTENANCE_NOTE,
    GOLDEN_SHRINK_NOTE,
    GOLDEN_GROWTH_CLIENTS_NOTE,
    MAINTENANCE_REVIEW_NOTE,
    GOLDEN_KVI_NOTE,
    GOLDEN_POFR_NOTE,
    GOLDEN_WA_NOTE,
    IBM_VP_NOTE,
    OFL_UE_NOTE,
    VP_UE_NOTE,
    LOOKER_FIELD_ALIASES,
    LOOKER_LINKS,
    LOOKER_NOT_APPROVED_METRICS,
    REVIEW_TAB_METRICS,
    SESSION_REVIEW_NOTE,
    METRIC_SOURCE,
    MONTH_LABELS,
    SOLD_FROM_SELECTION_NOTE,
    USER_VERIFIED,
    _fmt,
    fetch_metrics,
)

ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "auto_outputs" / "okr_2026_dashboard.html"
OUT_CSV = ROOT / "auto_outputs" / "okr_2026_dashboard.csv"
OUT_REVIEW_CSV = ROOT / "auto_outputs" / "okr_2026_for_review_kpis.csv"
VALIDATION_HTML = ROOT / "auto_outputs" / "okr_2026_validation.html"

# WBR / OKR sheet row order.
DASHBOARD_METRICS: list[str] = [
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
    "Avg Units per Order",
    "Order Frequency",
    "Penetration Rate",
    "Area Product Selection",
    "%Fresh Food / DDE",
    "IDQ",
    "VSL",
    "UP-TIME >",
    "% Bad Goods Rating",
]

# KPIs on לבדיקה sheet — sold from selection variants only.
REVIEW_DASHBOARD_METRICS: list[str] = list(REVIEW_TAB_METRICS)

SOURCE_BADGE: dict[str, tuple[str, str]] = {
    "snowflake_validated": ("Snowflake", "badge-ok"),
    "golden_canonical": ("Golden", "badge-ok"),
    "user_provided": ("User CSV", "badge-user"),
    "manual_entry": ("Manual", "badge-manual"),
    "pending_review": ("Review", "badge-pending"),
    "for_review": ("לבדיקה", "badge-review"),
    "looker_not_approved": ("לבדיקה", "badge-review"),
}

# Slack / SC evidence for managers (approved sources published in Slack).
SC_APPROVAL: dict[str, str] = {
    "Orders": "✅ verified by user · #ask-finance-analytics · UE ISR Look 47217 (Ziwei)",
    "DDE FEE/order": "✅ verified by user · #ask-finance-analytics · UE ISR Look 47217",
    "FTU": (
        f"✅ Golden Growth 106613 · {GOLDEN_GROWTH_CLIENTS_NOTE}"
    ),
    "FTU Conversion": (
        f"✅ Golden Growth 106613 · FTU Conversion / New Client Conversion (country dedup)"
    ),
    "Returning Clients": (
        f"✅ Golden Growth 106613 · {GOLDEN_GROWTH_CLIENTS_NOTE}"
    ),
    "Returning Client Conversion": (
        f"✅ Golden Growth 106613 · Returning Client Conversion (country dedup)"
    ),
    "PPM%": "✅ verified by user · #ask-finance-analytics · UE ISR Look 47217 · Product Profit Margin %",
    "Shrink/DDE FEE": f"Golden SCM 106617 — Snowflake auto · {GOLDEN_SHRINK_NOTE}",
    "OFL / order (ILS)": f"✅ verified by user · Wolt Market UE · {OFL_UE_NOTE}",
    "VP%": f"✅ verified by user · {IBM_VP_NOTE}",
    "Weighted Availability": f"✅ verified by user · {GOLDEN_WA_NOTE}",
    "KVI & Promo WA%": f"✅ verified by user · {GOLDEN_KVI_NOTE}",
    "Sold from selection — sold_from_selection_perc": (
        f"ממתין לאימות · exploration Purchases V ✅ · {SOLD_FROM_SELECTION_NOTE}"
    ),
    "Sold from selection — sold_from_product_selection_perc": (
        f"ממתין לאימות · exploration Purchases V ✅ · {SOLD_FROM_SELECTION_NOTE}"
    ),
    "POFR%": f"✅ verified by user · {GOLDEN_POFR_NOTE}",
    "Under 45min >": "✅ verified by user · WM Store Ops reporting V ✅ · MART delivered_under_45_minutes_orders_rate",
    "Avg Units per Order": "✅ verified by user · Golden Growth 106613 · TOTAL_UNITS ÷ TOTAL_ORDERS (ISR network row)",
    "Maintenance costs": f"לבדיקה · {MAINTENANCE_REVIEW_NOTE}",
    "Avg Units per Order": "✅ verified by user · Golden Growth 106613 · TOTAL_UNITS ÷ TOTAL_ORDERS (ISR network row)",
    "Order Frequency": "✅ verified by user · Golden Growth 106613 · MART ORDER_FREQUENCY (purchases ÷ distinct retail users)",
    "Penetration Rate": "✅ verified by user · Golden Growth 106613 · Active Users % of Country MAU",
    "Area Product Selection": "✅ verified by user · Golden Selection 106615 · Available Selection (MART per active WM store)",
    "%Fresh Food / DDE": "Manual entry in Looker OKR sheet",
    "IDQ": "Golden Selection 106615 — Item Data Quality ✅ verified by user",
    "VSL": "Golden SCM 106617 — Vendor Service Level ✅ verified by user",
    "UP-TIME >": "Golden Store Ops 106616 — Weighted Uptime ✅ verified by user",
    "% Bad Goods Rating": "✅ verified by user · Golden Store Ops 106616 — Bad Goods Rating % (Period=month, ISR)",
}

NOTES = [
    "Orders, FTU & Returning Clients are in thousands (K).",
    "VSL = country ISR in MART, includes Wolt Market DC | Nir Yaffe.",
    f"New / Returning clients: {GOLDEN_GROWTH_CLIENTS_NOTE}",
    f"Shrink/DDE FEE: {GOLDEN_SHRINK_NOTE} — נמשך אוטומטית מ-Snowflake (אותה לוגיקה כמו Golden tile).",
    f"VP%: {IBM_VP_NOTE} (IBM UI amounts in €; % matches Snowflake).",
    f"Weighted Availability: {GOLDEN_WA_NOTE} (not WA/OOS Dashboard 75053).",
    f"Maintenance: {MAINTENANCE_REVIEW_NOTE} — KPI by Leader בלבד.",
    "Jun OFL (UE RECON) may be partial until reconciliation closes.",
]


def _load_cached_metrics() -> dict[str, list[float | None]] | None:
    if not VALIDATION_HTML.is_file():
        return None
    text = VALIDATION_HTML.read_text(encoding="utf-8")
    match = re.search(r"window\.OKR_VALIDATION = (\{.*?\});</script>", text, re.S)
    if not match:
        return None
    payload = json.loads(match.group(1))
    return payload.get("snowflake")


def _looker_link(name: str) -> str:
    label, url = LOOKER_LINKS.get(name, ("Looker", ""))
    if not url:
        return f"<span class='muted'>{label}</span>"
    return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'


def _source_cell(name: str) -> str:
    kind = METRIC_SOURCE.get(name, "snowflake_validated")
    label, css = SOURCE_BADGE.get(kind, ("?", "badge-pending"))
    extra = ""
    if kind == "looker_not_approved":
        extra = ' <span class="badge-review">לבדיקה</span>'
    return f'<span class="{css}">{label}</span>{extra}'


def _metric_row(name: str, data: dict[str, list[float | None]]) -> str:
    cells = "".join(f"<td>{_fmt(data[name][i])}</td>" for i in range(6))
    alias = LOOKER_FIELD_ALIASES.get(name, "")
    alias_html = f'<div class="alias">{alias}</div>' if alias else ""
    sc = SC_APPROVAL.get(name, "—")
    verified = ' <span class="badge-ok">verified</span>' if name in USER_VERIFIED else ""
    return (
        f"<tr>"
        f"<td class='metric'>{name}{alias_html}</td>"
        f"<td>{_source_cell(name)}</td>"
        f"<td class='looker'>{_looker_link(name)}</td>"
        f"<td class='sc'>{sc}{verified}</td>"
        f"{cells}"
        f"</tr>"
    )


def build_html(data: dict[str, list[float | None]]) -> str:
    rows = [_metric_row(name, data) for name in DASHBOARD_METRICS]
    review_rows = [_metric_row(name, data) for name in REVIEW_DASHBOARD_METRICS]

    notes_html = "".join(f"<li>{n}</li>" for n in NOTES)
    month_headers = "".join(f"<th>{l}</th>" for l in MONTH_LABELS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>OKR 2026 — ISR Wolt Market Dashboard</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f0f4fa; color: #1a1a2e; }}
    h1 {{ color: #0f3460; margin-bottom: 4px; }}
    .meta {{ color: #5c6b8a; font-size: 13px; margin: 0 0 20px; }}
    .card {{ background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.06); overflow-x: auto; }}
    .tbl {{ border-collapse: collapse; width: 100%; font-size: 13px; min-width: 1100px; }}
    .tbl th, .tbl td {{ border: 1px solid #dde3ef; padding: 8px 10px; text-align: center; vertical-align: top; }}
    .tbl th {{ background: #0f3460; color: #fff; font-weight: 600; position: sticky; top: 0; }}
    .tbl td.metric {{ text-align: left; font-weight: 600; min-width: 200px; }}
    .tbl td.looker, .tbl td.sc {{ text-align: left; font-size: 12px; max-width: 220px; }}
    .tbl td.sc {{ color: #374151; }}
    .tbl a {{ color: #1a56db; text-decoration: none; }}
    .tbl a:hover {{ text-decoration: underline; }}
    .alias {{ color: #6b7280; font-size: 11px; font-weight: 400; margin-top: 4px; }}
    .badge-ok {{ background: #d1fae5; color: #065f46; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
    .badge-user {{ background: #dbeafe; color: #1e40af; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
    .badge-manual {{ background: #f3e8ff; color: #6b21a8; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
    .badge-pending {{ background: #fef3c7; color: #92400e; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
    .badge-review {{ background: #fef3c7; color: #92400e; font-size: 11px; padding: 2px 8px; border-radius: 4px; }}
    .muted {{ color: #9ca3af; }}
    .warn-title {{ color: #b45309; }}
    .card-warn {{ margin-top: 24px; border: 1px solid #fcd34d; }}
    .essi-card {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 10px; padding: 16px 18px; margin-bottom: 20px; }}
    .essi-card h3 {{ margin: 0 0 10px; color: #166534; font-size: 15px; }}
    .essi-quote {{ margin: 0 0 12px; padding: 12px 16px; background: #fff; border-left: 4px solid #22c55e; color: #1e293b; font-size: 13px; line-height: 1.5; }}
    .essi-quote p {{ margin: 0 0 8px; }}
    .essi-sources {{ margin-top: 12px; font-size: 12px; }}
    .notes {{ margin-top: 20px; font-size: 13px; color: #5c6b8a; }}
    .notes ul {{ margin: 8px 0 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <h1>OKR 2026 — ISR Wolt Market 1P</h1>
  <p class="meta">Jan–Jun 2026 · consolidated production table · generated from Snowflake + user CSV</p>

  <div class="card">
    <table class="tbl">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Source</th>
          <th>Looker</th>
          <th>SC / approval</th>
          {month_headers}
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    <div class="notes">
      <strong>Notes</strong>
      <ul>{notes_html}</ul>
    </div>
  </div>

  <div class="card card-warn">
    <h2 class="warn-title">לבדיקה</h2>
    <p class="meta"><strong>Sold from selection</strong> — ממתין לאימות · exploration Purchases V ✅.</p>
    <table class="tbl">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Source</th>
          <th>Looker</th>
          <th>SC / approval</th>
          {month_headers}
        </tr>
      </thead>
      <tbody>{"".join(review_rows)}</tbody>
    </table>
  </div>

  <script>window.OKR_DASHBOARD = {json.dumps(data, ensure_ascii=False)};</script>
</body>
</html>"""


def write_csv(data: dict[str, list[float | None]]) -> None:
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["metric", "source", "looker_label", "sc_approval", *MONTH_LABELS]
        )
        for name in DASHBOARD_METRICS:
            label, _url = LOOKER_LINKS.get(name, ("", ""))
            writer.writerow(
                [
                    name,
                    METRIC_SOURCE.get(name, ""),
                    label,
                    SC_APPROVAL.get(name, ""),
                    *[_fmt(data[name][i]) for i in range(6)],
                ]
            )

    with OUT_REVIEW_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["metric", "source", "looker_label", "sc_approval", *MONTH_LABELS]
        )
        for name in REVIEW_DASHBOARD_METRICS:
            label, _url = LOOKER_LINKS.get(name, ("", ""))
            writer.writerow(
                [
                    name,
                    METRIC_SOURCE.get(name, ""),
                    label,
                    SC_APPROVAL.get(name, ""),
                    *[_fmt(data[name][i]) for i in range(6)],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Reuse metrics embedded in okr_2026_validation.html",
    )
    args = parser.parse_args()

    if args.skip_fetch:
        data = _load_cached_metrics()
        if data is None:
            raise SystemExit("No cached metrics — run okr_2026_validation.py first.")
    else:
        data, _ofl_check, _vp_check, _shrink_check, _maint = fetch_metrics()

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(build_html(data), encoding="utf-8")
    write_csv(data)
    print(
        "Wrote",
        OUT_HTML.name,
        ",",
        OUT_CSV.name,
        "and",
        OUT_REVIEW_CSV.name,
        "to auto_outputs/",
    )


if __name__ == "__main__":
    main()
