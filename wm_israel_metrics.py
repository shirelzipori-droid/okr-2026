"""Wolt Market Israel metrics from Snowflake — always in local currency (ILS).

Data model (validated against reporting)
---------------------------------------
* **Orders** — ``PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS``
  ``TOTAL_ORDERS``, daily grain, ``VENUE_NAME LIKE 'Wolt Market |%'``, ``COUNTRY = 'ISR'``.
  This matches official venue reporting (e.g. 371,108 orders for Jun 2026).

* **Subtotal revenue VAT0 (local)** — ``PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_PURCHASES``
  ``WOLT_MARKET_SUBTOTAL_VAT0_LOCAL``, ``IS_WOLT_MARKET = TRUE``, ``COUNTRY = 'ISR'``.

* **Avg basket (local)** — ``subtotal_revenue_vat0_local / total_orders`` (weighted network average).

Auth
----
Prefers Snowflake ``externalbrowser`` (Okta) from ``~/.snowflake/connections.toml``.
Falls back to PAT in ``snowflake_secrets.env`` via ``snowflake_client``.

Setup
-----
  pip install -r requirements_snowflake.txt
  pip install "snowflake-connector-python[secure-local-storage]"

Examples
--------
  python wm_israel_metrics.py --quarter 2 --year 2026
  python wm_israel_metrics.py --month 2026-06
  python wm_israel_metrics.py --from 2026-04-01 --to 2026-07-01 --grain day
  python wm_israel_metrics.py --quarter 2 --year 2026 --by-store
  python wm_israel_metrics.py --quarter 2 --year 2026 --pivot
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Literal

import pandas as pd

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - py3.10
    import tomli as tomllib  # type: ignore[no-redef]

COUNTRY = "ISR"
VENUE_PREFIX = "Wolt Market |"
CURRENCY_LABEL = "ILS"
DEFAULT_WAREHOUSE = "EXPLORATION_XS"
CONNECTIONS_FILE = Path.home() / ".snowflake" / "connections.toml"
CONNECTION_NAME = "wolt_snowflake_prod"

Grain = Literal["month", "day"]
GroupBy = Literal["network", "store"]


def _parse_ymd(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    if quarter not in (1, 2, 3, 4):
        raise ValueError("quarter must be 1–4")
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    end_day = calendar.monthrange(year, end_month)[1]
    end_exclusive = _next_month(date(year, end_month, end_day))
    return start, end_exclusive


def month_range(ym: str) -> tuple[date, date]:
    year_s, month_s = ym.split("-", 1)
    start = date(int(year_s), int(month_s), 1)
    return start, _next_month(start)


def _load_connection_profile() -> dict[str, str]:
    if not CONNECTIONS_FILE.is_file():
        return {}
    data = tomllib.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
    profile = data.get(CONNECTION_NAME, {})
    return {str(k): str(v) for k, v in profile.items()}


def _has_pat_credentials() -> bool:
    env_file = Path(__file__).resolve().parent / "snowflake_secrets.env"
    if not env_file.is_file():
        return False
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("SNOWFLAKE_PAT=") or line.startswith("SNOWFLAKE_TOKEN="):
            _, _, val = line.partition("=")
            if val.strip():
                return True
    return False


@contextmanager
def snowflake_connection() -> Iterator[Any]:
    """Open Snowflake using browser SSO (preferred) or PAT fallback."""
    try:
        import snowflake.connector
    except ImportError as exc:
        raise ImportError(
            "Install: pip install -r requirements_snowflake.txt"
        ) from exc

    profile = _load_connection_profile()
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "").strip() or DEFAULT_WAREHOUSE

    connect_kwargs: dict[str, Any] = {
        "account": profile.get("account") or os.environ.get("SNOWFLAKE_ACCOUNT", ""),
        "user": profile.get("user") or os.environ.get("SNOWFLAKE_USER", ""),
        "role": profile.get("role") or os.environ.get("SNOWFLAKE_ROLE", "BASE_USER"),
        "warehouse": warehouse,
    }

    auth_mode = os.environ.get("SNOWFLAKE_AUTH", "").strip().lower()
    if auth_mode == "pat" or (not profile.get("authenticator") and _has_pat_credentials()):
        from snowflake_client import snowflake_connection as pat_connection

        with pat_connection() as conn:
            yield conn
        return

    if profile.get("authenticator"):
        connect_kwargs["authenticator"] = profile["authenticator"]
    else:
        from snowflake_client import snowflake_connection as pat_connection

        with pat_connection() as conn:
            yield conn
        return

    missing = [k for k in ("account", "user") if not connect_kwargs.get(k)]
    if missing:
        raise ValueError(
            f"Missing Snowflake connection settings: {', '.join(missing)}. "
            f"Check {CONNECTIONS_FILE} or snowflake_secrets.env."
        )

    conn = snowflake.connector.connect(**connect_kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(f"USE WAREHOUSE {warehouse}")
        yield conn
    finally:
        conn.close()


def _period_expr(grain: Grain, date_col: str) -> str:
    if grain == "month":
        return f"DATE_TRUNC('month', {date_col})::DATE"
    return f"{date_col}::DATE"


def fetch_orders(
    conn: Any,
    *,
    start: date,
    end_exclusive: date,
    grain: Grain = "month",
    group_by: GroupBy = "network",
) -> pd.DataFrame:
    period = _period_expr(grain, "DATE")
    group_cols = [period]
    select_cols = [f"{period} AS period"]
    if group_by == "store":
        group_cols.append("VENUE_NAME")
        select_cols.append("VENUE_NAME AS store")

    sql = f"""
        SELECT
            {", ".join(select_cols)},
            SUM(TOTAL_ORDERS) AS total_orders
        FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
        WHERE PERIOD = 'day'
          AND COUNTRY = %(country)s
          AND VENUE_NAME LIKE %(venue_prefix)s
          AND DATE >= %(start)s
          AND DATE < %(end)s
        GROUP BY {", ".join(group_cols)}
        ORDER BY {", ".join(group_cols)}
    """
    params = {
        "country": COUNTRY,
        "venue_prefix": f"{VENUE_PREFIX}%",
        "start": start.isoformat(),
        "end": end_exclusive.isoformat(),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        df = cur.fetch_pandas_all()
    df.columns = [str(c).lower() for c in df.columns]
    return df


def fetch_revenue_local(
    conn: Any,
    *,
    start: date,
    end_exclusive: date,
    grain: Grain = "month",
    group_by: GroupBy = "network",
) -> pd.DataFrame:
    period = _period_expr(grain, "TIME_RECEIVED")
    group_cols = [period]
    select_cols = [f"{period} AS period"]
    if group_by == "store":
        group_cols.extend(["VENUE_ID"])
        select_cols.append("VENUE_ID")

    sql = f"""
        SELECT
            {", ".join(select_cols)},
            SUM(WOLT_MARKET_SUBTOTAL_VAT0_LOCAL) AS subtotal_revenue_vat0_local
        FROM PRODUCTION.PRESENTATION.F_UNIT_ECONOMICS_PURCHASES
        WHERE COUNTRY = %(country)s
          AND IS_WOLT_MARKET = TRUE
          AND WOLT_MARKET_SUBTOTAL_VAT0_LOCAL > 0
          AND TIME_RECEIVED >= %(start)s
          AND TIME_RECEIVED < %(end)s
        GROUP BY {", ".join(group_cols)}
        ORDER BY {", ".join(group_cols)}
    """
    params = {
        "country": COUNTRY,
        "start": start.isoformat(),
        "end": end_exclusive.isoformat(),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        df = cur.fetch_pandas_all()
    df.columns = [str(c).lower() for c in df.columns]
    return df


def _store_names(conn: Any) -> pd.DataFrame:
    sql = """
        SELECT DISTINCT VENUE_ID, VENUE_NAME AS store
        FROM PRODUCTION.PRESENTATION.WOLT_MARKET_METRICS
        WHERE COUNTRY = %(country)s
          AND VENUE_NAME LIKE %(venue_prefix)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"country": COUNTRY, "venue_prefix": f"{VENUE_PREFIX}%"})
        df = cur.fetch_pandas_all()
    df.columns = [str(c).lower() for c in df.columns]
    return df


def build_metrics(
    conn: Any,
    *,
    start: date,
    end_exclusive: date,
    grain: Grain = "month",
    group_by: GroupBy = "network",
) -> pd.DataFrame:
    orders = fetch_orders(conn, start=start, end_exclusive=end_exclusive, grain=grain, group_by=group_by)
    revenue = fetch_revenue_local(
        conn, start=start, end_exclusive=end_exclusive, grain=grain, group_by=group_by
    )

    if group_by == "network":
        df = orders.merge(revenue, on="period", how="outer")
    else:
        names = _store_names(conn)
        revenue = revenue.merge(names, on="VENUE_ID", how="left")
        revenue = revenue.drop(columns=["VENUE_ID"])
        revenue = revenue.groupby(["period", "store"], as_index=False)["subtotal_revenue_vat0_local"].sum()
        df = orders.merge(revenue, on=["period", "store"], how="outer")

    df["total_orders"] = pd.to_numeric(df["total_orders"], errors="coerce")
    df["subtotal_revenue_vat0_local"] = pd.to_numeric(
        df["subtotal_revenue_vat0_local"], errors="coerce"
    )
    df["avg_basket_size_local"] = (
        df["subtotal_revenue_vat0_local"] / df["total_orders"].where(df["total_orders"] > 0)
    )
    df["currency"] = CURRENCY_LABEL
    return df.sort_values([c for c in df.columns if c in ("period", "store")]).reset_index(drop=True)


def pivot_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Rows = metric, columns = period (for network-level output)."""
    if "store" in df.columns:
        raise ValueError("Pivot is only supported for network-level metrics (omit --by-store).")

    work = df.copy()
    work["period"] = pd.to_datetime(work["period"]).dt.strftime("%Y-%m")

    rows: list[dict[str, Any]] = []
    for label, col in [
        ("Orders", "total_orders"),
        (f"Avg basket size ({CURRENCY_LABEL})", "avg_basket_size_local"),
        (f"Subtotal revenue VAT0 ({CURRENCY_LABEL})", "subtotal_revenue_vat0_local"),
    ]:
        row = {"metric": label}
        for _, rec in work.iterrows():
            val = rec[col]
            if pd.isna(val):
                row[rec["period"]] = None
            elif col == "total_orders":
                row[rec["period"]] = int(round(val))
            else:
                row[rec["period"]] = round(float(val), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _print_df(df: pd.DataFrame) -> None:
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Wolt Market Israel Snowflake metrics (local currency / ILS)."
    )
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], help="Calendar quarter (1–4)")
    parser.add_argument("--year", type=int, help="Year for --quarter")
    parser.add_argument("--month", help="Single month YYYY-MM")
    parser.add_argument("--from", dest="date_from", help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--to", dest="date_to", help="End date YYYY-MM-DD (exclusive)")
    parser.add_argument("--grain", choices=["month", "day"], default="month")
    parser.add_argument("--by-store", action="store_true", help="Break down by venue")
    parser.add_argument("--pivot", action="store_true", help="Pivot: metrics as rows, periods as columns")
    parser.add_argument("--csv", action="store_true", help="Print CSV")
    args = parser.parse_args(argv)

    if args.quarter is not None:
        if args.year is None:
            parser.error("--year is required with --quarter")
        start, end_exclusive = quarter_range(args.year, args.quarter)
    elif args.month:
        start, end_exclusive = month_range(args.month)
    elif args.date_from and args.date_to:
        start, end_exclusive = _parse_ymd(args.date_from), _parse_ymd(args.date_to)
    else:
        parser.error("Provide --quarter/--year, --month, or --from/--to")

    group_by: GroupBy = "store" if args.by_store else "network"

    try:
        with snowflake_connection() as conn:
            df = build_metrics(
                conn,
                start=start,
                end_exclusive=end_exclusive,
                grain=args.grain,
                group_by=group_by,
            )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.pivot:
        if group_by == "store":
            print("Error: --pivot cannot be combined with --by-store", file=sys.stderr)
            return 2
        out = pivot_metrics(df)
    else:
        out = df

    if args.csv:
        out.to_csv(sys.stdout, index=False)
    else:
        _print_df(out)
        print(
            f"\nSource: Wolt Market Israel | {start} .. {end_exclusive} (exclusive) | {CURRENCY_LABEL}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
