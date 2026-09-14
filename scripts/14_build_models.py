"""Phase 5 -- Screen 2 data: model scorecards.

Two observation windows are mixed on this screen and the UI labels each tile
with its own window, so the two are never silently averaged together:

    registrations per year, median age at registration, owner split,
    fuel/colour/body mix, national rank        -> 2013-2026, row counts
    regional concentration                     -> 2013-2025, rows with a valid
                                                  KOATUU (2026 has no KOATUU)
    resale rate, median ownership duration     -> 2021-2026, VIN-keyed

Linkage is VIN-only. data_diagnostic.md section 3 measured a ~26% chain-break
rate for plate-keyed linkage, so no plate-keyed metric ships.

Output is sharded BY BRAND, not per model: a few hundred files, each small,
instead of thousands of tiny ones that bloat git and round-trip badly.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import dims

P = f"'{dims.PARQUET.as_posix()}'"
OUT_DIR = dims.DOCS_DATA / "models"
MODEL_META = dims.BUILD_DIR / "model_meta.json"
DIMENSIONS = dims.BUILD_DIR / "dimensions.json"

YEARS = dims.ALL_YEARS
YI = {y: i for i, y in enumerate(YEARS)}
OTHER = "Інше"


def load_dimensions() -> dict:
    if not DIMENSIONS.exists():
        dims.fail(f"{DIMENSIONS} not found -- run 11_dimensions.py first")
    return json.loads(DIMENSIONS.read_text(encoding="utf-8"))


def select_models(con: duckdb.DuckDBPyConnection, say) -> list[tuple]:
    con.execute(f"""
        CREATE TABLE sel AS
        SELECT brand, model, COUNT(*) AS n FROM {P}
        WHERE brand IS NOT NULL AND model IS NOT NULL
        GROUP BY 1, 2 HAVING COUNT(*) >= {dims.MODEL_MIN_ROWS}
    """)
    con.execute("""
        CREATE TABLE ids AS
        SELECT brand, model, n,
               CAST(ROW_NUMBER() OVER (ORDER BY brand, model) - 1 AS INT) AS mid
        FROM sel
    """)
    con.execute(f"""
        CREATE TABLE r AS
        SELECT ids.mid, p.* FROM {P} p JOIN ids
          ON ids.brand = p.brand AND ids.model = p.model
    """)
    rows = con.execute("SELECT mid, brand, model, n FROM ids ORDER BY mid").fetchall()
    covered = con.execute("SELECT COUNT(*) FROM r").fetchone()[0]
    brands = len({b for _, b, _, _ in rows})
    say(f"- threshold: **>= {dims.MODEL_MIN_ROWS:,}** registrations 2013–2026")
    say(f"- models included: **{len(rows):,}** across **{brands:,}** brands "
        f"(= shard files)")
    say(f"- rows covered: **{covered:,}** of {dims.EXPECTED_TOTAL:,} "
        f"({100 * covered / dims.EXPECTED_TOTAL:.1f}%)")
    excl_models, excl_rows = con.execute(f"""
        SELECT COUNT(*), COALESCE(SUM(n), 0) FROM (
          SELECT COUNT(*) n FROM {P}
          WHERE brand IS NOT NULL AND model IS NOT NULL
          GROUP BY brand, model HAVING COUNT(*) < {dims.MODEL_MIN_ROWS})
    """).fetchone()
    say(f"- models excluded by the threshold: {excl_models:,} "
        f"({excl_rows:,} rows, {100 * excl_rows / dims.EXPECTED_TOTAL:.1f}%)")
    return rows


def per_year(con, say) -> tuple[dict, dict, dict, dict]:
    counts: dict[int, list] = defaultdict(lambda: [0] * len(YEARS))
    for mid, y, n in con.execute(
            "SELECT mid, source_year, COUNT(*) FROM r GROUP BY 1, 2").fetchall():
        counts[mid][YI[y]] = n

    ages: dict[int, list] = defaultdict(lambda: [None] * len(YEARS))
    for mid, y, med in con.execute("""
            SELECT mid, source_year, MEDIAN(age_at_reg) FROM r
            WHERE age_at_reg IS NOT NULL GROUP BY 1, 2""").fetchall():
        ages[mid][YI[y]] = round(float(med), 1)

    # Whole-window median, not the mean of the per-year medians: a KPI that
    # averaged medians would not be a median of anything.
    age_all = {mid: round(float(m), 1) for mid, m in con.execute("""
        SELECT mid, MEDIAN(age_at_reg) FROM r WHERE age_at_reg IS NOT NULL
        GROUP BY 1""").fetchall()}

    own_p: dict[int, list] = defaultdict(lambda: [0] * len(YEARS))
    own_j: dict[int, list] = defaultdict(lambda: [0] * len(YEARS))
    for mid, y, person, n in con.execute("""
            SELECT mid, source_year, person, COUNT(*) FROM r
            WHERE person IS NOT NULL GROUP BY 1, 2, 3""").fetchall():
        (own_p if person == "P" else own_j)[mid][YI[y]] = n
    say(f"- per-year series built for {len(counts):,} models")
    return counts, ages, age_all, own_p, own_j


def mixes(con, dim, say) -> tuple[dict, dict, dict, list, list]:
    fuel_groups = dims.FUEL_GROUPS
    fi = {g: i for i, g in enumerate(fuel_groups)}
    fuel: dict[int, list] = defaultdict(lambda: [0] * len(fuel_groups))
    for mid, g, n in con.execute(
            "SELECT mid, fuel_grp, COUNT(*) FROM r GROUP BY 1, 2").fetchall():
        fuel[mid][fi.get(g, fi[dims.FUEL_UNKNOWN])] += n

    colors = list(dim["colors"]) + [OTHER]
    ci = {c: i for i, c in enumerate(colors)}
    canon = "CASE " + " ".join(
        f"WHEN color = {dims.sql_str(k)} THEN {dims.sql_str(v)}"
        for k, v in dims.COLOR_CANON.items()) + " ELSE color END"
    color: dict[int, list] = defaultdict(lambda: [0] * len(colors))
    for mid, c, n in con.execute(
            f"SELECT mid, {canon} c, COUNT(*) FROM r WHERE color IS NOT NULL "
            "GROUP BY 1, 2").fetchall():
        color[mid][ci.get(c, ci[OTHER])] += n

    bodies = list(dim["bodies"]) + [OTHER]
    bi = {b: i for i, b in enumerate(bodies)}
    body: dict[int, list] = defaultdict(lambda: [0] * len(bodies))
    for mid, b, n in con.execute(
            "SELECT mid, body, COUNT(*) FROM r WHERE body IS NOT NULL "
            "GROUP BY 1, 2").fetchall():
        body[mid][bi.get(b, bi[OTHER])] += n
    say(f"- mixes: {len(fuel_groups)} fuel groups, {len(colors)} colours, "
        f"{len(bodies)} body types")
    return fuel, color, body, colors, bodies


def regions(con, say) -> dict:
    codes = ", ".join(dims.sql_str(c) for c in dims.OBLAST_CODES)
    oi = dims.OBLAST_INDEX
    reg: dict[int, list] = defaultdict(lambda: [0] * len(dims.OBLAST_CODES))
    for mid, ob, n in con.execute(f"""
            SELECT mid, oblast, COUNT(*) FROM r
            WHERE source_year <= 2025 AND oblast IN ({codes})
            GROUP BY 1, 2""").fetchall():
        reg[mid][oi[ob]] = n
    say(f"- regional concentration (2013–2025, valid KOATUU) for {len(reg):,} models")
    return reg


def vin_metrics(con, say) -> tuple[dict, dict, dict]:
    """Resale rate and ownership duration, VIN-keyed over 2021-2026."""
    y0, y1 = dims.VIN_YEARS[0], dims.VIN_YEARS[-1]
    con.execute(f"""
        CREATE TABLE mv AS
        SELECT mid, vin, d_reg FROM r
        WHERE source_year BETWEEN {y0} AND {y1}
          AND vin IS NOT NULL AND d_reg IS NOT NULL
    """)
    vins, resold = {}, {}
    for mid, total, multi in con.execute("""
            SELECT mid, COUNT(*), COUNT(*) FILTER (WHERE ev >= 2) FROM (
              SELECT mid, vin, COUNT(*) ev FROM mv GROUP BY 1, 2
            ) GROUP BY 1""").fetchall():
        vins[mid] = total
        resold[mid] = round(100.0 * multi / total, 2) if total else None

    dur = {}
    for mid, med in con.execute("""
            SELECT mid, MEDIAN(gap) FROM (
              SELECT mid, DATE_DIFF('day', LAG(d_reg) OVER (
                       PARTITION BY mid, vin ORDER BY d_reg), d_reg) gap
              FROM mv
            ) WHERE gap IS NOT NULL AND gap > 0 GROUP BY 1""").fetchall():
        dur[mid] = int(med)
    say(f"- VIN metrics (2021–2026) for {len(vins):,} models")
    return vins, resold, dur


def ranks(counts: dict) -> dict:
    """National rank by registrations, per year, across every included model."""
    out: dict[int, list] = {mid: [None] * len(YEARS) for mid in counts}
    for i in range(len(YEARS)):
        ordered = sorted(((c[i], mid) for mid, c in counts.items() if c[i] > 0),
                         reverse=True)
        for pos, (_, mid) in enumerate(ordered, 1):
            out[mid][i] = pos
    return out


def main() -> None:
    if not dims.PARQUET.exists():
        dims.fail(f"{dims.PARQUET} not found -- run 10_stage_parquet.py first")
    t0 = time.time()
    say = dims.Report("14_build_models.md")
    say("# Phase 5 -- model scorecards\n")
    dim = load_dimensions()
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")

    ids = select_models(con, say)
    counts, ages, age_all, own_p, own_j = per_year(con, say)
    fuel, color, body, colors, bodies = mixes(con, dim, say)
    reg = regions(con, say)
    vins, resold, dur = vin_metrics(con, say)
    rank = ranks(counts)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()

    shards: dict[str, dict] = {}
    slugs: dict[str, str] = {}
    used: dict[str, str] = {}
    index_models = []
    brand_list = sorted({b for _, b, _, _ in ids})
    for b in brand_list:
        s = dims.slug(b)
        if s in used and used[s] != b:
            s = f"{s}-{dims.slug(str(len(used)))}"      # keep shard names unique
        used[s] = b
        slugs[b] = s
        shards[b] = {"brand": b, "slug": s, "models": {}}

    for mid, brand, model, n in ids:
        shards[brand]["models"][model] = {
            "n": n,
            "y": counts[mid],
            "a": ages[mid],
            "am": age_all.get(mid),
            "p": own_p[mid],
            "j": own_j[mid],
            "f": fuel[mid],
            "c": color[mid],
            "bd": body[mid],
            "r": reg[mid],
            "rk": rank[mid],
            "vn": vins.get(mid, 0),
            "rs": resold.get(mid),
            "od": dur.get(mid),
        }
        index_models.append({"b": brand_list.index(brand), "m": model,
                             "n": n, "s": slugs[brand]})

    biggest = 0
    for brand, shard in shards.items():
        path = OUT_DIR / f"{shard['slug']}.json"
        path.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        biggest = max(biggest, path.stat().st_size)

    index_models.sort(key=lambda m: -m["n"])
    index = {"brands": brand_list, "models": index_models,
             "colors": colors, "bodies": bodies,
             "fuel_groups": dims.FUEL_GROUPS, "years": YEARS}
    ipath = OUT_DIR / "index.json"
    ipath.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")

    say(f"\n- shards written: **{len(shards):,}**, largest "
        f"{biggest / 1024:,.0f} KB")
    say(f"- index.json: {ipath.stat().st_size / 1024:,.0f} KB "
        f"({len(index_models):,} models)")
    if ipath.stat().st_size > 600_000:
        say("  WARNING: index.json is over the 600 KB target")

    MODEL_META.write_text(json.dumps({
        "threshold": dims.MODEL_MIN_ROWS,
        "models_included": len(ids),
        "brands_included": len(shards),
        "colors": colors, "bodies": bodies,
        "index_bytes": ipath.stat().st_size,
        "largest_shard_bytes": biggest,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"\nelapsed: {time.time() - t0:,.1f}s")
    print(f"report: {say.save()}")


if __name__ == "__main__":
    main()
