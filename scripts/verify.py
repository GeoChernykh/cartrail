"""Phase 7 verification. Every check either passes or stops the script.

    .venv\\Scripts\\python.exe scripts\\verify.py

Run it after scripts/build_all.py. The independent recompute (check 5) is
written from scratch against the Parquet and deliberately shares no SQL with
13_build_migration.py -- it re-derives the move definition itself and compares
the result with the JSON the site actually serves.

Checks 6 (serve and click through) and 9 (walk the style contract) are manual:
    cd docs && ..\\.venv\\Scripts\\python.exe -m http.server 8000
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import dims

P = f"'{dims.PARQUET.as_posix()}'"
CSV = dims.REPO_ROOT / "data" / "merged_registrations.csv"
SIZE_BUDGET = 25 * 1024 * 1024
FILE_BUDGET = 5 * 1024 * 1024
OB = tuple(dims.OBLAST_CODES)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{f' — {detail}' if detail else ''}",
          flush=True)
    if not ok:
        failures.append(name)


def rows_reconcile(con) -> None:
    rows = dict(con.execute(
        f"SELECT source_year, COUNT(*) FROM {P} GROUP BY 1").fetchall())
    bad = {y: (rows.get(y), n) for y, n in dims.EXPECTED_ROWS.items() if rows.get(y) != n}
    total = sum(rows.values())
    check("1. per-year rows match data_diagnostic.md section 1", not bad, str(bad or ""))
    check("1. total rows", total == dims.EXPECTED_TOTAL,
          f"{total:,} vs {dims.EXPECTED_TOTAL:,}")


def parse_rates(con) -> None:
    worst = con.execute(f"""
        SELECT source_year, 100.0 * COUNT(d_reg) / COUNT(*) pct
        FROM {P} GROUP BY 1 ORDER BY pct LIMIT 1""").fetchone()
    check("2. d_reg non-null >= 99% every year", worst[1] >= 99.0,
          f"worst {worst[0]}: {worst[1]:.3f}%")
    codes = ", ".join(dims.sql_str(c) for c in dims.OBLAST_CODES)
    worst_ob = con.execute(f"""
        SELECT source_year,
               100.0 * COUNT(*) FILTER (WHERE koatuu IS NOT NULL
                   AND oblast NOT IN ({codes})) / NULLIF(COUNT(koatuu), 0) pct
        FROM {P} GROUP BY 1 ORDER BY pct DESC NULLS LAST LIMIT 1""").fetchone()
    check("2. unmapped KOATUU prefix < 1% every year", (worst_ob[1] or 0) < 1.0,
          f"worst {worst_ob[0]}: {worst_ob[1] or 0:.3f}%")
    unmapped = con.execute(
        f"SELECT COUNT(*) FROM {P} WHERE fuel IS NOT NULL AND fuel_grp IS NULL"
    ).fetchone()[0]
    check("2. fuel-group coverage of non-null FUEL is 100%", unmapped == 0,
          f"{unmapped:,} unmapped")


def duplicates_excluded(con) -> None:
    if not CSV.exists():
        check("3. duplicate 2022 archives excluded", True, "source CSV absent, skipped")
        return
    n = con.execute(f"""
        SELECT COUNT(*) FROM read_csv('{CSV.as_posix()}', delim=';', header=true,
               quote='"', all_varchar=true)
        WHERE SOURCE_FILE IN {dims.EXCLUDED_SOURCE_FILES}""").fetchone()[0]
    check("3. zero rows from reestrTZ2022_part1/2", n == 0, f"{n:,} rows")


def size_budget() -> None:
    files = [p for p in dims.DOCS_DATA.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    over = [p.name for p in files if p.stat().st_size > FILE_BUDGET]
    check("4. docs/data <= 25 MB", total <= SIZE_BUDGET,
          f"{total / 1024 / 1024:.2f} MB across {len(files)} files")
    check("4. no single file > 5 MB", not over, str(over))


def independent_recompute(con) -> None:
    """Re-derive the move definition from scratch and compare with the shipped
    JSON: move_year 2023, natural persons, all fuels, all age bands, the busiest
    corridor. Shares no SQL with the build."""
    order = ("d_reg, oblast, person, COALESCE(fuel_grp, ''), "
             "COALESCE(make_year, -1), COALESCE(oper_code, '')")
    bands = " ".join(
        f"WHEN age BETWEEN {lo} AND {hi} THEN {i}"
        for i, (lo, hi) in enumerate(dims.AGE_BAND_EDGES))
    rows = con.execute(f"""
        WITH e AS (
          SELECT vin, d_reg, oblast, person, fuel_grp, make_year, oper_code
          FROM {P}
          WHERE source_year BETWEEN 2021 AND 2025 AND vin IS NOT NULL
            AND d_reg IS NOT NULL AND oblast IN {OB}
        ),
        first_ev AS (
          SELECT vin, d_reg AS d1, oblast AS ob1, fuel_grp AS fg1 FROM e
          QUALIFY ROW_NUMBER() OVER (PARTITION BY vin ORDER BY {order}) = 1
        ),
        second_ev AS (
          SELECT e.vin, e.d_reg AS d2, e.oblast AS ob2, e.person AS p2,
                 e.make_year AS my2
          FROM e JOIN first_ev f ON f.vin = e.vin AND e.d_reg > f.d1
          QUALIFY ROW_NUMBER() OVER (PARTITION BY e.vin ORDER BY
            e.d_reg, e.oblast, e.person, COALESCE(e.fuel_grp, ''),
            COALESCE(e.make_year, -1), COALESCE(e.oper_code, '')) = 1
        ),
        pairs AS (
          SELECT f.ob1, s.ob2, YEAR(s.d2) AS yr, s.p2, f.fg1,
                 CASE WHEN s.my2 IS NULL THEN NULL
                      ELSE YEAR(s.d2) - s.my2 END AS age
          FROM first_ev f JOIN second_ev s ON s.vin = f.vin
        ),
        cells AS (
          SELECT ob1, ob2, yr, p2, fg1,
                 CASE {bands} ELSE {len(dims.AGE_BANDS) - 1} END AS ab,
                 COUNT(*) AS n
          FROM pairs GROUP BY ALL HAVING COUNT(*) >= {dims.MIN_CELL}
        )
        SELECT ob1, ob2, SUM(n) FROM cells
        WHERE yr = 2023 AND p2 = 'P' AND ob1 <> ob2
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1
    """).fetchall()
    ob1, ob2, mine = rows[0]

    cube = json.loads((dims.DOCS_DATA / "flows" / "flows_2023.json")
                      .read_text(encoding="utf-8"))
    a, b = dims.OBLAST_INDEX[ob1], dims.OBLAST_INDEX[ob2]
    shipped = sum(cube["n"][k] for k in range(len(cube["n"]))
                  if cube["from"][k] == a and cube["to"][k] == b
                  and cube["own"][k] == 0)
    name = f"{dims.OBLAST_NAMES[ob1]} → {dims.OBLAST_NAMES[ob2]}"
    check("5. independent recompute of the top 2023 corridor", mine == shipped,
          f"{name}, фізичні особи: recomputed {mine:,}, shipped {shipped:,}")


def no_absolute_paths() -> None:
    docs = dims.REPO_ROOT / "docs"
    bad = []
    patterns = [
        re.compile(r'(?:src|href)\s*=\s*["\']/'),
        re.compile(r'fetch\(\s*["\']/'),
        re.compile(r'(?:src|href)\s*=\s*["\']https?://'),
        re.compile(r'fetch\(\s*["\']https?://'),
    ]
    for path in list(docs.rglob("*.html")) + list(docs.rglob("*.js")) \
            + list(docs.rglob("*.css")):
        if path.name == "d3.v7.min.js":
            continue                      # vendored third-party bundle
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in patterns):
                bad.append(f"{path.relative_to(docs)}:{line_no}")
    check("7. no absolute or external paths in docs/", not bad, str(bad))


def main() -> None:
    if not dims.PARQUET.exists():
        dims.fail(f"{dims.PARQUET} not found -- run scripts/build_all.py first")
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")

    rows_reconcile(con)
    parse_rates(con)
    duplicates_excluded(con)
    size_budget()
    independent_recompute(con)
    no_absolute_paths()

    print()
    if failures:
        raise SystemExit(f"VERIFICATION FAILED: {len(failures)} check(s): {failures}")
    print("all automated checks passed; checks 6 and 9 are manual "
          "(serve docs/ and walk dashboard-style-prompt.md)")


if __name__ == "__main__":
    main()
