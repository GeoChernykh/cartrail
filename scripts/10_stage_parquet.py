"""Phase 1 -- stage one typed Parquet that every later phase reads.

All aggregation runs off build/registrations.parquet, never off repeated scans
of the 8.6 GB merged CSV. The merged CSV carries raw D_REG strings in three
formats (data/merge_data.py never parsed dates), so parsing happens here, per
source year, and the per-year non-null rate is asserted.

Source gate: the per-year row counts must reconcile against
data_diagnostic.md section 1 (total 24,787,233) before anything is staged. On a
mismatch the merged CSV is discarded and the ZIPs are staged instead through
common.register_all() + common.union_view(), which already handle every
documented schema quirk -- the merged CSV is never patched.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import common
import dims

CSV_PATH = dims.REPO_ROOT / "data" / "merged_registrations.csv"
OUT = dims.PARQUET

RAW_READ = (
    f"read_csv('{CSV_PATH.as_posix()}', delim=';', header=true, quote='\"', "
    "all_varchar=true)"
)


def connect() -> duckdb.DuckDBPyConnection:
    dims.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dims.BUILD_DIR / "duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    return con


def source_gate(con: duckdb.DuckDBPyConnection, say) -> None:
    rows = con.execute(f"""
        SELECT CAST(SOURCE_YEAR AS INT) y, COUNT(*) n
        FROM {RAW_READ} GROUP BY 1 ORDER BY 1
    """).fetchall()
    actual = {y: n for y, n in rows}
    say("| source_year | rows | expected | ok |")
    say("|---|---|---|---|")
    bad = []
    for y in sorted(set(actual) | set(dims.EXPECTED_ROWS)):
        got, exp = actual.get(y, 0), dims.EXPECTED_ROWS.get(y, 0)
        ok = got == exp
        if not ok:
            bad.append((y, got, exp))
        say(f"| {y} | {got:,} | {exp:,} | {'yes' if ok else 'NO'} |")
    total = sum(actual.values())
    say(f"| **total** | **{total:,}** | **{dims.EXPECTED_TOTAL:,}** | "
        f"**{'yes' if total == dims.EXPECTED_TOTAL else 'NO'}** |")
    if bad or total != dims.EXPECTED_TOTAL:
        dims.fail(
            "merged CSV does not reconcile against data_diagnostic.md section 1 "
            f"(mismatched years: {bad}). Stage from the ZIPs via "
            "common.register_all() + common.union_view() instead; do not patch the CSV."
        )

    dupes = con.execute(f"""
        SELECT COUNT(*) FROM {RAW_READ}
        WHERE SOURCE_FILE IN {dims.EXCLUDED_SOURCE_FILES}
    """).fetchone()[0]
    say(f"\nrows from the duplicate 2022 archives: {dupes} (must be 0)")
    if dupes:
        dims.fail(f"{dupes:,} rows trace to {dims.EXCLUDED_SOURCE_FILES}")


def check_date_formats(con: duckdb.DuckDBPyConnection, say) -> None:
    """Detect each year's D_REG format from the data and confirm it matches the
    table in dims -- TRY_STRPTIME turns any surprise into a silent NULL."""
    say("\n| source_year | sample D_REG | detected | expected |")
    say("|---|---|---|---|")
    for y in sorted(dims.EXPECTED_ROWS):
        sample = con.execute(f"""
            SELECT D_REG FROM {RAW_READ}
            WHERE CAST(SOURCE_YEAR AS INT) = {y} AND D_REG IS NOT NULL LIMIT 1
        """).fetchone()
        got = common.detect_date_format(sample[0]) if sample else None
        exp = dims.DATE_FORMATS[y]
        say(f"| {y} | {sample[0] if sample else '-'} | {got} | {exp} |")
        if got != exp:
            dims.fail(f"{y}: D_REG format is {got!r}, dims expects {exp!r}")


def staging_sql() -> str:
    date_cases = "\n".join(
        f"      WHEN {y} THEN TRY_STRPTIME(D_REG, {dims.sql_str(f)})"
        for y, f in sorted(dims.DATE_FORMATS.items())
    )
    fuel_cases = "\n".join(
        f"      WHEN {dims.sql_str(k)} THEN {dims.sql_str(v)}"
        for k, v in dims.FUEL_GROUP_MAP.items()
    )
    brand_cases = "\n".join(
        f"      WHEN {dims.sql_str(k)} THEN {dims.sql_str(v)}"
        for k, v in dims.BRAND_ALIASES.items()
    )
    return f"""
WITH src AS (
  SELECT *,
    CAST(SOURCE_YEAR AS INT) AS sy,
    CAST(CASE CAST(SOURCE_YEAR AS INT)
{date_cases}
    END AS DATE) AS d_reg_p,
    NULLIF(REGEXP_REPLACE(TRIM(UPPER(BRAND)), '\\s+', ' ', 'g'), '') AS brand_ws,
    NULLIF(REGEXP_REPLACE(TRIM(UPPER(MODEL)), '\\s+', ' ', 'g'), '') AS model_ws,
    NULLIF(TRIM(UPPER(FUEL)), '') AS fuel_u,
    CASE WHEN REGEXP_MATCHES(TRIM(REG_ADDR_KOATUU), '^[0-9]{{10}}$')
         THEN TRIM(REG_ADDR_KOATUU) END AS koatuu
  FROM {RAW_READ}
),
stripped AS (
  SELECT *,
    -- BRAND often carries brand + model ("SSANG YONG  REXTON" / MODEL "REXTON").
    -- Stripping that suffix takes distinct brands from 36,515 to 4,267.
    CASE WHEN brand_ws IS NOT NULL AND model_ws IS NOT NULL
              AND ENDS_WITH(brand_ws, ' ' || model_ws)
              AND LENGTH(brand_ws) > LENGTH(model_ws) + 1
         THEN NULLIF(TRIM(SUBSTR(brand_ws, 1, LENGTH(brand_ws) - LENGTH(model_ws) - 1)), '')
         ELSE brand_ws END AS brand_s
  FROM src
)
SELECT
  CAST(sy AS SMALLINT) AS source_year,
  d_reg_p AS d_reg,
  CAST(YEAR(d_reg_p) AS SMALLINT) AS reg_year,
  CASE WHEN TRIM(UPPER(PERSON)) IN ('P', 'J') THEN TRIM(UPPER(PERSON)) END AS person,
  koatuu,
  SUBSTR(koatuu, 1, 2) AS oblast,
  NULLIF(TRIM(OPER_CODE), '') AS oper_code,
  COALESCE(CASE brand_s
{brand_cases}
  END, brand_s) AS brand,
  model_ws AS model,
  NULLIF(TRIM(BRAND), '') AS brand_raw,
  NULLIF(TRIM(MODEL), '') AS model_raw,
  CASE WHEN TRIM(UPPER(VIN)) IN ('', 'NULL') THEN NULL ELSE TRIM(UPPER(VIN)) END AS vin,
  {common.norm_plate_sql()} AS plate,
  CAST(CASE WHEN TRY_CAST(MAKE_YEAR AS INT) BETWEEN 1900 AND 2027
            THEN TRY_CAST(MAKE_YEAR AS INT) END AS SMALLINT) AS make_year,
  CAST(CASE WHEN TRY_CAST(MAKE_YEAR AS INT) BETWEEN 1900 AND 2027
                 AND YEAR(d_reg_p) - TRY_CAST(MAKE_YEAR AS INT) BETWEEN 0 AND 60
            THEN YEAR(d_reg_p) - TRY_CAST(MAKE_YEAR AS INT) END AS SMALLINT) AS age_at_reg,
  NULLIF(TRIM(UPPER(COLOR)), '') AS color,
  NULLIF(TRIM(UPPER(KIND)), '') AS kind,
  NULLIF(TRIM(UPPER(BODY)), '') AS body,
  fuel_u AS fuel,
  CASE fuel_u
{fuel_cases}
  END AS fuel_grp,
  CAST(CASE WHEN TRY_CAST(CAPACITY AS INT) BETWEEN 1 AND 30000
            THEN TRY_CAST(CAPACITY AS INT) END AS INTEGER) AS capacity
FROM stripped
"""


def verify(con: duckdb.DuckDBPyConnection, say) -> None:
    say("\n### Staged Parquet reconciliation\n")
    say("| source_year | rows | expected | d_reg non-null | koatuu valid | vin non-null |")
    say("|---|---|---|---|---|---|")
    rows = con.execute(f"""
        SELECT source_year,
               COUNT(*) n,
               100.0 * COUNT(d_reg) / COUNT(*) date_pct,
               100.0 * COUNT(koatuu) / COUNT(*) koatuu_pct,
               100.0 * COUNT(vin) / COUNT(*) vin_pct
        FROM '{OUT.as_posix()}' GROUP BY 1 ORDER BY 1
    """).fetchall()
    bad_dates = []
    total = 0
    for y, n, dpct, kpct, vpct in rows:
        total += n
        if n != dims.EXPECTED_ROWS[y]:
            dims.fail(f"{y}: staged {n:,} rows, expected {dims.EXPECTED_ROWS[y]:,}")
        if dpct < 99.0:
            bad_dates.append((y, round(dpct, 3)))
        say(f"| {y} | {n:,} | {dims.EXPECTED_ROWS[y]:,} | {dpct:.3f}% | "
            f"{kpct:.2f}% | {vpct:.2f}% |")
    say(f"| **total** | **{total:,}** | **{dims.EXPECTED_TOTAL:,}** | | | |")
    if total != dims.EXPECTED_TOTAL:
        dims.fail(f"staged total {total:,} != {dims.EXPECTED_TOTAL:,}")
    if bad_dates:
        dims.fail(f"d_reg non-null rate below 99% for {bad_dates}")

    unmapped = con.execute(f"""
        SELECT COUNT(*) FROM '{OUT.as_posix()}'
        WHERE fuel IS NOT NULL AND fuel_grp IS NULL
    """).fetchone()[0]
    say(f"\nunmapped FUEL values: {unmapped} (must be 0 -- the vocabulary has "
        "14 distinct values, so dims.FUEL_GROUP_MAP is exhaustive)")
    if unmapped:
        sample = con.execute(f"""
            SELECT fuel, COUNT(*) n FROM '{OUT.as_posix()}'
            WHERE fuel IS NOT NULL AND fuel_grp IS NULL
            GROUP BY 1 ORDER BY n DESC LIMIT 10
        """).fetchall()
        dims.fail(f"FUEL values missing from dims.FUEL_GROUP_MAP: {sample}")

    size_mb = OUT.stat().st_size / 1e6
    say(f"\nbuild/registrations.parquet: {size_mb:,.1f} MB")


def main() -> None:
    t0 = time.time()
    say = dims.Report("10_stage_parquet.md")
    say("# Phase 1 -- stage typed Parquet\n")
    if not CSV_PATH.exists():
        dims.fail(f"{CSV_PATH} not found -- run data/merge_data.py first")

    con = connect()
    say("### Source gate\n")
    source_gate(con, say)
    check_date_formats(con, say)

    say(f"\nwriting {OUT} ...")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"COPY ({staging_sql()}) TO '{OUT.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    verify(con, say)
    say(f"\nelapsed: {time.time() - t0:,.1f}s")
    print(f"report: {say.save()}")


if __name__ == "__main__":
    main()
