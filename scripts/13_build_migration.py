"""Phase 4 -- Screen 1 data: the VIN-keyed migration cube.

Move definition (PLAN.md Phase 4). Per VIN, over source_year 2021-2025 rows
that carry a VALID oblast, ordered by d_reg:

    e1 = the first such event
    e2 = the first such event with d_reg > e1.d_reg

    from_ob = e1.oblast   to_ob = e2.oblast   move_year = year(e2.d_reg)
    days    = e2.d_reg - e1.d_reg
    person  = e2.person (owner type at the destination)
    fuel    = e1.fuel_grp
    age_band from e2.reg_year - make_year

This never touches the operation vocabulary. data_diagnostic.md section 4 shows
codes 40/70/71/50/80 are high-volume and not confidently classifiable, so
defining a move as first-observed -> next-observed sidesteps classification
entirely. For the same reason the phrase "перша реєстрація" never appears:
the window is left-censored and the UI says
«перша зафіксована реєстрація у вікні 2021–2025».

Correctness rules enforced below:

* The diagonal (from_ob == to_ob) STAYS in the cube -- retention needs it. Only
  the arc layer drops it, at render time.
* A VIN whose later events all lack a valid oblast -- including every 2026
  event, since 2026 has no KOATUU column at all -- is dropped from the
  denominator entirely. Counting it as "stayed" would silently inflate the
  headline retention figure. The dropped count and share go into meta.
* Ordering is fully deterministic (d_reg, then oblast, then the remaining
  attributes) so a rebuild reproduces the same cube.
* The definition filters to valid-oblast rows FIRST, so a VIN with
  e1(valid) -> x(invalid) -> e3(valid) links e1->e3. That share is measured and
  recorded rather than left silent.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import dims

P = f"'{dims.PARQUET.as_posix()}'"
OUT_DIR = dims.DOCS_DATA / "flows"
MIG_META = dims.BUILD_DIR / "migration_meta.json"

def order_by(p: str = "") -> str:
    """Deterministic ordering for rows sharing the same d_reg, so a rebuild
    picks the same e1/e2 every time. `p` is an optional table alias prefix."""
    return (f"{p}d_reg, {p}oblast, {p}person, COALESCE({p}fuel_grp, ''), "
            f"COALESCE({p}make_year, -1), COALESCE({p}oper_code, '')")


def build_events(con: duckdb.DuckDBPyConnection, say) -> None:
    codes = ", ".join(dims.sql_str(c) for c in dims.OBLAST_CODES)
    y0, y1 = dims.MIGRATION_YEARS[0], dims.MIGRATION_YEARS[-1]

    # Every VIN event in 2021-2026, valid oblast or not. The 2026 rows exist
    # here only to answer "did anything happen after e1?" -- they can never be
    # an e2 because they have no oblast.
    con.execute(f"""
        CREATE TABLE ev AS
        SELECT vin, d_reg, oblast, person, fuel_grp, make_year, oper_code, source_year
        FROM {P}
        WHERE source_year BETWEEN {y0} AND {dims.VIN_YEARS[-1]}
          AND vin IS NOT NULL AND d_reg IS NOT NULL
    """)
    con.execute(f"""
        CREATE TABLE evv AS SELECT * FROM ev
        WHERE source_year BETWEEN {y0} AND {y1} AND oblast IN ({codes})
    """)
    con.execute(f"""
        CREATE TABLE e1 AS SELECT * FROM evv
        QUALIFY ROW_NUMBER() OVER (PARTITION BY vin ORDER BY {order_by()}) = 1
    """)
    con.execute(f"""
        CREATE TABLE e2 AS
        SELECT v.* FROM evv v JOIN e1 ON e1.vin = v.vin AND v.d_reg > e1.d_reg
        QUALIFY ROW_NUMBER() OVER (PARTITION BY v.vin ORDER BY {order_by('v.')}) = 1
    """)
    # First event of any kind after e1 -- the denominator test.
    con.execute("""
        CREATE TABLE nxt AS
        SELECT e1.vin, MIN(ev.d_reg) AS d_next
        FROM ev JOIN e1 ON e1.vin = ev.vin AND ev.d_reg > e1.d_reg
        GROUP BY 1
    """)
    say(f"- VIN events 2021–2026: {con.execute('SELECT COUNT(*) FROM ev').fetchone()[0]:,}")
    say(f"- with a valid oblast (2021–2025): "
        f"{con.execute('SELECT COUNT(*) FROM evv').fetchone()[0]:,}")


def denominator(con: duckdb.DuckDBPyConnection, say) -> dict:
    n_e1 = con.execute("SELECT COUNT(*) FROM e1").fetchone()[0]
    n_e2 = con.execute("SELECT COUNT(*) FROM e2").fetchone()[0]
    n_next = con.execute("SELECT COUNT(*) FROM nxt").fetchone()[0]
    dropped = n_next - n_e2
    no_later = n_e1 - n_next
    intermediate = con.execute("""
        SELECT COUNT(*) FROM e2 JOIN nxt ON nxt.vin = e2.vin
        WHERE nxt.d_next < e2.d_reg
    """).fetchone()[0]

    say(f"\n- VINs with a first valid-oblast event: **{n_e1:,}**")
    say(f"- of those, with any later event: {n_next:,} "
        f"({100 * n_next / n_e1:.2f}%)")
    say(f"- with an observable second valid-oblast event (the denominator): "
        f"**{n_e2:,}**")
    say(f"- dropped — later events exist but none carries a valid oblast "
        f"(2026 rows included): **{dropped:,}** "
        f"({100 * dropped / n_next:.2f}% of VINs with a later event)")
    say(f"- no later event at all in the window (right-censored, not dropped): "
        f"{no_later:,}")
    say(f"- pairs whose e1→e2 skips an invalid-oblast event in between: "
        f"{intermediate:,} ({100 * intermediate / n_e2:.2f}% of pairs)")
    return {
        "vins_with_first_event": n_e1,
        "vins_with_any_later_event": n_next,
        "observable_pairs": n_e2,
        "dropped_no_valid_destination": dropped,
        "dropped_share_of_later": round(100 * dropped / n_next, 3),
        "right_censored_no_later_event": no_later,
        "pairs_skipping_invalid_event": intermediate,
        "pairs_skipping_invalid_share": round(100 * intermediate / n_e2, 3),
    }


def build_moves(con: duckdb.DuckDBPyConnection, say) -> dict:
    age_cases = "\n".join(
        f"      WHEN age BETWEEN {lo} AND {hi} THEN {i}"
        for i, (lo, hi) in enumerate(dims.AGE_BAND_EDGES)
    )
    con.execute(f"""
        CREATE TABLE mv AS
        WITH pairs AS (
          SELECT e1.oblast AS from_ob, e2.oblast AS to_ob,
                 YEAR(e2.d_reg) AS move_year,
                 e2.person AS person,
                 e1.fuel_grp AS fg,
                 CASE WHEN e2.make_year IS NOT NULL
                      THEN YEAR(e2.d_reg) - e2.make_year END AS age,
                 DATE_DIFF('day', e1.d_reg, e2.d_reg) AS dgap
          FROM e1 JOIN e2 ON e1.vin = e2.vin
        )
        SELECT from_ob, to_ob, move_year, person, fg, dgap,
          CASE
{age_cases}
            ELSE {len(dims.AGE_BANDS) - 1}
          END AS ageb
        FROM pairs
    """)
    n, diag, med = con.execute("""
        SELECT COUNT(*), SUM(CASE WHEN from_ob = to_ob THEN 1 ELSE 0 END), MEDIAN(dgap)
        FROM mv
    """).fetchone()
    say(f"\n- pairs in the cube (diagonal kept): **{n:,}**")
    say(f"- retention — second event in the same oblast: **{100 * diag / n:.2f}%**")
    say(f"- exact median days between the two events: **{med:,.0f}**")

    nulls = con.execute("SELECT COUNT(*) FROM mv WHERE person IS NULL").fetchone()[0]
    if nulls:
        dims.fail(f"{nulls:,} pairs have a NULL owner type; PERSON is never null in this data")

    say("\n| move_year | pairs | retention | median days |")
    say("|---|---|---|---|")
    by_year = con.execute("""
        SELECT move_year, COUNT(*),
               100.0 * SUM(CASE WHEN from_ob = to_ob THEN 1 ELSE 0 END) / COUNT(*),
               MEDIAN(dgap)
        FROM mv GROUP BY 1 ORDER BY 1
    """).fetchall()
    for y, c, r, m in by_year:
        say(f"| {y} | {c:,} | {r:.2f}% | {m:,.0f} |")

    # National days histogram per year, on the same 8 bins as the cube. When the
    # overflow ladder drops the per-cell histogram the UI still needs a days
    # median it can compute exactly the same way for any selection of years;
    # pooling per-corridor medians instead would bias the figure upward.
    hist_cases = ",\n".join(
        f"  COUNT(*) FILTER (WHERE dgap BETWEEN {lo} AND {hi})"
        for lo, hi in dims.DAYS_BIN_EDGES[:-1])
    hist = con.execute(f"""
        SELECT move_year,
{hist_cases},
          COUNT(*) FILTER (WHERE dgap >= {dims.DAYS_BIN_EDGES[-1][0]})
        FROM mv GROUP BY 1 ORDER BY 1
    """).fetchall()
    return {"pairs": n, "retention_pct": round(100 * diag / n, 2),
            "median_days_exact": int(med),
            "by_year": {str(y): {"pairs": c, "retention_pct": round(r, 2),
                                 "median_days": int(m)} for y, c, r, m in by_year},
            "days_hist_by_year": {str(row[0]): list(row[1:]) for row in hist}}


def write_cube(con: duckdb.DuckDBPyConnection, say) -> dict:
    fuel_dim = dims.CUBE_FUEL_DIM
    group_fg = "fg" if fuel_dim else "NULL AS fg"
    raw_cells = con.execute(f"""
        SELECT COUNT(*) FROM (SELECT from_ob, to_ob, move_year, person,
                              {group_fg}, ageb FROM mv GROUP BY ALL)
    """).fetchone()[0]
    dh_cases = ",\n".join(
        f"  COUNT(*) FILTER (WHERE dgap BETWEEN {lo} AND {hi}) AS d{i}"
        for i, (lo, hi) in enumerate(dims.DAYS_BIN_EDGES[:-1])
    )
    last_lo = dims.DAYS_BIN_EDGES[-1][0]
    cells = con.execute(f"""
        SELECT from_ob, to_ob, move_year, person, {group_fg}, ageb, COUNT(*) AS n,
{dh_cases},
          COUNT(*) FILTER (WHERE dgap >= {last_lo}) AS d{len(dims.DAYS_BIN_EDGES) - 1}
        FROM mv GROUP BY 1, 2, 3, 4, 5, 6
        HAVING COUNT(*) >= {dims.MIN_CELL}
        ORDER BY move_year, from_ob, to_ob, person, 5, ageb
    """).fetchall()
    kept = len(cells)
    kept_rows = sum(c[6] for c in cells)
    total_rows = con.execute("SELECT COUNT(*) FROM mv").fetchone()[0]
    say(f"\n- distinct cells before the floor: **{raw_cells:,}**")
    say(f"- cells surviving n >= {dims.MIN_CELL}: **{kept:,}** "
        f"(limit {dims.CUBE_CELL_LIMIT:,})")
    say(f"- pairs suppressed by the floor: {total_rows - kept_rows:,} "
        f"({100 * (total_rows - kept_rows) / total_rows:.2f}%)")

    ship_dh = kept <= dims.CUBE_CELL_LIMIT
    say(f"- fuel dimension shipped with the cube: **{'yes' if fuel_dim else 'no'}**")
    say(f"- days histogram shipped with the cube: **{'yes' if ship_dh else 'no'}**")

    oi = dims.OBLAST_INDEX
    fi = {g: i for i, g in enumerate(dims.FUEL_GROUPS)}
    unknown_fuel = fi[dims.FUEL_UNKNOWN]
    owner_i = {o: i for i, o in enumerate(dims.OWNER_TYPES)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    per_year: dict[int, dict] = {y: {"from": [], "to": [], "own": [], "fuel": [],
                                     "ageb": [], "n": [], "dh": []}
                                 for y in dims.MIGRATION_YEARS}
    for row in cells:
        from_ob, to_ob, year, person, fg, ageb, n = row[:7]
        d = per_year[year]
        d["from"].append(oi[from_ob])
        d["to"].append(oi[to_ob])
        d["own"].append(owner_i[person])
        if fuel_dim:
            d["fuel"].append(fi.get(fg, unknown_fuel) if fg else unknown_fuel)
        d["ageb"].append(ageb)
        d["n"].append(n)
        if ship_dh:
            d["dh"].append(list(row[7:]))

    sizes = {}
    for year, d in per_year.items():
        if not ship_dh:
            d.pop("dh")
        if not fuel_dim:
            d.pop("fuel")
        payload = {"year": year, **d}
        path = OUT_DIR / f"flows_{year}.json"
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        sizes[year] = path.stat().st_size
        say(f"  flows_{year}.json — {len(d['n']):,} cells, {sizes[year] / 1024:,.0f} KB")

    if not ship_dh:
        write_exact_medians(con, say)

    return {
        "cells_raw": raw_cells, "cells_kept": kept,
        "min_cell": dims.MIN_CELL,
        "pairs_suppressed": total_rows - kept_rows,
        "pairs_suppressed_pct": round(100 * (total_rows - kept_rows) / total_rows, 3),
        "days_hist": ship_dh,
        "fuel_dim": fuel_dim,
        "bytes": sizes,
    }


def write_exact_medians(con: duckdb.DuckDBPyConnection, say) -> None:
    """Overflow branch: the cube got too big to carry an 8-bin histogram, so
    medians come from an exact table keyed (from, to, move_year) instead. Tiles
    reading it are labelled «усі типи власників, усе пальне»."""
    rows = con.execute("""
        SELECT from_ob, to_ob, move_year, COUNT(*) n, MEDIAN(dgap) md
        FROM mv GROUP BY 1, 2, 3 HAVING COUNT(*) >= 3 ORDER BY 3, 1, 2
    """).fetchall()
    oi = dims.OBLAST_INDEX
    payload = {
        "from": [oi[r[0]] for r in rows],
        "to": [oi[r[1]] for r in rows],
        "year": [r[2] for r in rows],
        "n": [r[3] for r in rows],
        "median_days": [int(r[4]) for r in rows],
    }
    path = OUT_DIR / "medians.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    say(f"  medians.json — {len(rows):,} rows, {path.stat().st_size / 1024:,.0f} KB")


def main() -> None:
    if not dims.PARQUET.exists():
        dims.fail(f"{dims.PARQUET} not found -- run 10_stage_parquet.py first")
    t0 = time.time()
    say = dims.Report("13_build_migration.md")
    say("# Phase 4 -- migration cube (VIN-keyed, 2021–2025)\n")
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")

    build_events(con, say)
    denom = denominator(con, say)
    moves = build_moves(con, say)
    cube = write_cube(con, say)

    MIG_META.write_text(json.dumps({**denom, **moves, **cube},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"\nelapsed: {time.time() - t0:,.1f}s")
    print(f"report: {say.save()}")


if __name__ == "__main__":
    main()
