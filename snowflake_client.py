"""Secure Snowflake client: load credentials from .env, run queries, return pandas DataFrames.

Setup
-----
  pip install snowflake-connector-python pandas pyarrow

Credentials live in ``snowflake_secrets.env`` (gitignored) or any file you pass via
``--env`` / ``SNOWFLAKE_ENV_FILE``. Required keys:

  SNOWFLAKE_ACCOUNT=org-account.region
  SNOWFLAKE_USER=you@company.com
  SNOWFLAKE_PAT=your_programmatic_access_token

Optional: SNOWFLAKE_WAREHOUSE, SNOWFLAKE_ROLE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Usage as a library
------------------
  from snowflake_client import query_df, execute_sql, snowflake_connection

  df = query_df("SELECT CURRENT_TIMESTAMP() AS ts")
  with snowflake_connection() as conn:
      df = query_df("SELECT * FROM my_table LIMIT 10", connection=conn)

Usage from the command line
---------------------------
  python snowflake_client.py
  python snowflake_client.py "SELECT COUNT(*) FROM orders"
  python snowflake_client.py --file sql_templates/april_sales_template.sql
  python snowflake_client.py --env path/to/other.env "SELECT 1"
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_ENV_FILE = Path(__file__).resolve().parent / "snowflake_secrets.env"

_REQUIRED_KEYS = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER")
_TOKEN_KEYS = ("SNOWFLAKE_PAT", "SNOWFLAKE_TOKEN")


def load_env_file(path: Path | str | None = None, *, override: bool = False) -> Path | None:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``.

  Returns the path that was loaded, or ``None`` if the file does not exist.
  By default, existing environment variables are not overwritten.
    """
    env_path = Path(path or os.environ.get("SNOWFLAKE_ENV_FILE", DEFAULT_ENV_FILE))
    if not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value

    return env_path


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def get_config(*, env_file: Path | str | None = None) -> dict[str, str | None]:
    """Read Snowflake connection settings from the environment (loading .env first)."""
    load_env_file(env_file)

    token = ""
    for key in _TOKEN_KEYS:
        token = os.environ.get(key, "").strip()
        if token:
            break

    config = {
        "account": os.environ.get("SNOWFLAKE_ACCOUNT", "").strip(),
        "user": os.environ.get("SNOWFLAKE_USER", "").strip(),
        "token": token,
        "warehouse": _optional(os.environ.get("SNOWFLAKE_WAREHOUSE")),
        "role": _optional(os.environ.get("SNOWFLAKE_ROLE")),
        "database": _optional(os.environ.get("SNOWFLAKE_DATABASE")),
        "schema": _optional(os.environ.get("SNOWFLAKE_SCHEMA")),
    }

    missing = [name for name in _REQUIRED_KEYS if not os.environ.get(name, "").strip()]
    if not token:
        missing.append("SNOWFLAKE_PAT or SNOWFLAKE_TOKEN")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return config


def _connect_kwargs(config: dict[str, str | None]) -> dict[str, Any]:
    """Build kwargs for ``snowflake.connector.connect`` (PAT via password field)."""
    kwargs: dict[str, Any] = {
        "user": config["user"],
        "account": config["account"],
        "password": config["token"],
    }
    for key in ("warehouse", "role", "database", "schema"):
        if config.get(key):
            kwargs[key] = config[key]
    return kwargs


@contextmanager
def snowflake_connection(
    *,
    env_file: Path | str | None = None,
    **overrides: str | None,
) -> Iterator[Any]:
    """Open a Snowflake connection; closes automatically on exit."""
    try:
        import snowflake.connector
    except ImportError as exc:
        raise ImportError(
            "Install dependencies: pip install snowflake-connector-python pandas pyarrow"
        ) from exc

    config = get_config(env_file=env_file)
    for key, value in overrides.items():
        if value is not None:
            config[key] = value.strip() if isinstance(value, str) else value

    conn = snowflake.connector.connect(**_connect_kwargs(config))
    try:
        yield conn
    finally:
        conn.close()


def query_df(
    sql: str,
    params: dict[str, Any] | tuple[Any, ...] | list[Any] | None = None,
    *,
    connection: Any | None = None,
    env_file: Path | str | None = None,
) -> "Any":
    """Execute a SELECT (or any query with a result set) and return a pandas DataFrame."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("Install pandas: pip install pandas") from exc

    if connection is None:
        with snowflake_connection(env_file=env_file) as conn:
            return query_df(sql, params, connection=conn)

    with connection.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return pd.DataFrame()
        try:
            return cur.fetch_pandas_all()
        except Exception:
            cols = [col[0] for col in cur.description]
            rows = cur.fetchall()
            return pd.DataFrame(rows, columns=cols)


def execute_sql(
    sql: str,
    params: dict[str, Any] | tuple[Any, ...] | list[Any] | None = None,
    *,
    connection: Any | None = None,
    env_file: Path | str | None = None,
) -> int:
    """Execute DDL/DML without fetching rows. Returns ``cursor.rowcount`` when available."""
    if connection is None:
        with snowflake_connection(env_file=env_file) as conn:
            return execute_sql(sql, params, connection=conn)

    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount if cur.rowcount is not None else -1


def _read_sql_arg(sql_arg: str | None, file_arg: Path | None) -> str:
    if file_arg is not None:
        return file_arg.read_text(encoding="utf-8").strip()
    if sql_arg:
        return sql_arg.strip()
    return (
        "SELECT CURRENT_TIMESTAMP() AS ts, "
        "CURRENT_USER() AS user_name, "
        "CURRENT_ROLE() AS role_name"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Snowflake query and print results.")
    parser.add_argument("sql", nargs="?", help="SQL to execute (default: connection test query)")
    parser.add_argument("--file", "-f", type=Path, help="Read SQL from a file")
    parser.add_argument(
        "--env",
        type=Path,
        default=None,
        help=f"Path to .env credentials (default: {DEFAULT_ENV_FILE.name})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run as DDL/DML (no DataFrame); print rows affected",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Print CSV to stdout instead of a formatted table",
    )
    args = parser.parse_args(argv)

    sql = _read_sql_arg(args.sql, args.file)

    try:
        if args.execute:
            rowcount = execute_sql(sql, env_file=args.env)
            print(f"OK (rowcount={rowcount})")
            return 0

        df = query_df(sql, env_file=args.env)
        if args.csv:
            df.to_csv(sys.stdout, index=False)
        else:
            with pd_option_context():
                print(df.to_string(index=False))
        print(f"\n({len(df)} rows)", file=sys.stderr)
        return 0
    except (ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Snowflake error: {exc}", file=sys.stderr)
        return 1


def pd_option_context():
    """Widen pandas display for terminal output."""
    import pandas as pd

    return pd.option_context(
        "display.max_columns",
        None,
        "display.width",
        None,
        "display.max_colwidth",
        80,
    )


if __name__ == "__main__":
    raise SystemExit(main())
