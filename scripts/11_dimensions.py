"""Phase 2 -- dimensions, normalization audit and vocabulary gates.

10_stage_parquet.py already applied the deterministic brand normalization
(uppercase, trim, collapse whitespace, strip a trailing " " + MODEL from BRAND,
then dims.BRAND_ALIASES). This script is the audit and the gate for it: it
re-measures the result against the staged Parquet, writes the reports a human
has to eyeball (build/reports/brands.md, build/reports/vocab.md), persists the
mapping to build/brand_map.json, and fails the build if any vocabulary gate
slips.

Nothing downstream may run if an assertion here fails -- a silently unmapped
vocabulary produces a confidently wrong product.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import dims

P = f"'{dims.PARQUET.as_posix()}'"
BRAND_MAP = dims.BUILD_DIR / "brand_map.json"
DIMENSIONS = dims.BUILD_DIR / "dimensions.json"


def brands(con: duckdb.DuckDBPyConnection, say) -> dict:
    say("## 2a. Brand normalization\n")
    raw_n = con.execute(f"""
        SELECT COUNT(DISTINCT NULLIF(REGEXP_REPLACE(TRIM(UPPER(brand_raw)), '\\s+', ' ', 'g'), ''))
        FROM {P}
    """).fetchone()[0]
    norm_n = con.execute(f"SELECT COUNT(DISTINCT brand) FROM {P}").fetchone()[0]
    say(f"- distinct BRAND, whitespace-collapsed only: **{raw_n:,}**")
    say(f"- distinct brand after suffix strip + aliases: **{norm_n:,}**")
    say(f"- reduction: {100 * (1 - norm_n / raw_n):.1f}%\n")
    if norm_n >= raw_n:
        dims.fail("brand normalization did not reduce the distinct-brand count")

    top = con.execute(f"""
        SELECT brand, COUNT(*) n, COUNT(DISTINCT brand_raw) variants
        FROM {P} WHERE brand IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 200
    """).fetchall()

    report = dims.Report("brands.md")
    report("# Top 200 brands after normalization\n")
    report("Eyeball this list. Anything that is the same marque under two "
           "spellings belongs in dims.BRAND_ALIASES.\n")
    report("| # | brand | registrations | distinct raw BRAND strings |")
    report("|---|---|---|---|")
    for i, (b, n, v) in enumerate(top, 1):
        report(f"| {i} | {b} | {n:,} | {v:,} |")
    report.save()
    say("- top-200 brand list written to build/reports/brands.md")
    say(f"- top 12: {', '.join(b for b, _, _ in top[:12])}\n")

    variants = con.execute(f"""
        WITH top300 AS (
          SELECT brand FROM {P} WHERE brand IS NOT NULL
          GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 300
        )
        SELECT brand, brand_raw, n FROM (
          SELECT brand, brand_raw, COUNT(*) n,
                 ROW_NUMBER() OVER (PARTITION BY brand ORDER BY COUNT(*) DESC) rn
          FROM {P} WHERE brand IN (SELECT brand FROM top300)
          GROUP BY 1, 2
        ) WHERE rn <= 5
    """).fetchall()
    per_brand: dict[str, list] = {}
    for b, raw, n in variants:
        per_brand.setdefault(b, []).append([raw, n])
    BRAND_MAP.write_text(json.dumps({
        "aliases": dims.BRAND_ALIASES,
        "distinct_raw": raw_n,
        "distinct_normalized": norm_n,
        "top_brands": [{"brand": b, "n": n, "raw_variants": v,
                        "top_raw": per_brand.get(b, [])} for b, n, v in top],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    say("- mapping persisted to build/brand_map.json\n")
    return {"distinct_raw": raw_n, "distinct_normalized": norm_n}


def vocab(con: duckdb.DuckDBPyConnection, say) -> dict:
    say("## 2b. Vocabularies\n")
    report = dims.Report("vocab.md")
    report("# Source vocabularies (as published)\n")

    out = {}
    for col in ("fuel", "color", "kind", "body"):
        rows = con.execute(f"""
            SELECT {col} v, COUNT(*) n FROM {P} WHERE {col} IS NOT NULL
            GROUP BY 1 ORDER BY n DESC
        """).fetchall()
        out[col] = rows
        report(f"\n## {col.upper()} -- {len(rows):,} distinct\n")
        report("| value | rows |")
        report("|---|---|")
        for v, n in rows[:60]:
            report(f"| {v} | {n:,} |")
        if len(rows) > 60:
            report(f"| … {len(rows) - 60:,} more | |")
        say(f"- {col.upper()}: {len(rows):,} distinct values")

    unmapped = con.execute(f"""
        SELECT COUNT(*) FROM {P} WHERE fuel IS NOT NULL AND fuel_grp IS NULL
    """).fetchone()[0]
    covered, total = con.execute(f"SELECT COUNT(fuel_grp), COUNT(fuel) FROM {P}").fetchone()
    pct = 100.0 * covered / total if total else 0.0
    say(f"- fuel-group coverage of non-null FUEL: **{pct:.4f}%** ({unmapped:,} unmapped)")
    if unmapped:
        dims.fail(f"{unmapped:,} rows have a FUEL value missing from dims.FUEL_GROUP_MAP")

    fg = con.execute(f"""
        SELECT fuel_grp, COUNT(*) n FROM {P} WHERE fuel_grp IS NOT NULL
        GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    report("\n## Fuel groups (derived)\n")
    report("| group | rows |")
    report("|---|---|")
    for g, n in fg:
        report(f"| {g} | {n:,} |")
    say(f"- fuel groups: {', '.join(f'{g} {n:,}' for g, n in fg)}")

    top_colors, seen = [], set()
    for v, _ in out["color"]:
        c = dims.COLOR_CANON.get(v, v)
        if c not in seen:
            seen.add(c)
            top_colors.append(c)
    top_colors = top_colors[:dims.COLOR_TOP_N]
    top_bodies = [v for v, _ in out["body"][:dims.BODY_TOP_N]]
    say(f"- colour cutoff: top {len(top_colors)} of {len(seen)} canonical")
    say(f"- body cutoff: top {len(top_bodies)} of {len(out['body']):,}\n")
    report.save()
    return {"colors": top_colors, "bodies": top_bodies,
            "kinds": [v for v, _ in out["kind"]],
            "fuel_groups": [g for g, _ in fg]}


def oblasts(con: duckdb.DuckDBPyConnection, say) -> dict:
    say("## 2c. Oblast crosswalk\n")
    codes = ", ".join(dims.sql_str(c) for c in dims.OBLAST_CODES)
    rows = con.execute(f"""
        SELECT source_year,
               COUNT(*) AS n_rows,
               COUNT(koatuu) AS n_valid,
               COUNT(*) FILTER (WHERE koatuu IS NOT NULL
                                AND oblast NOT IN ({codes})) AS n_unmapped
        FROM {P} GROUP BY 1 ORDER BY 1
    """).fetchall()
    say("| source_year | rows | valid KOATUU | valid share | unmapped prefix | share of valid |")
    say("|---|---|---|---|---|---|")
    bad = []
    for y, total, valid, unmapped in rows:
        share = 100.0 * unmapped / valid if valid else 0.0
        if share >= 1.0:
            bad.append((y, round(share, 3)))
        say(f"| {y} | {total:,} | {valid:,} | {100.0 * valid / total:.2f}% | "
            f"{unmapped:,} | {share:.3f}% |")
    if bad:
        top = con.execute(f"""
            SELECT oblast, COUNT(*) n FROM {P}
            WHERE koatuu IS NOT NULL AND oblast NOT IN ({codes})
            GROUP BY 1 ORDER BY n DESC LIMIT 15
        """).fetchall()
        say(f"\ntop unmapped prefixes: {top}")
        dims.fail(f"unmapped KOATUU prefix share >= 1% for {bad}")
    say("\n- 27 oblast codes in dims.OBLASTS; unmapped share < 1% every year\n")
    return {str(y): {"rows": t, "valid": v, "unmapped": u} for y, t, v, u in rows}


def main() -> None:
    if not dims.PARQUET.exists():
        dims.fail(f"{dims.PARQUET} not found -- run 10_stage_parquet.py first")
    say = dims.Report("11_dimensions.md")
    say("# Phase 2 -- dimensions\n")
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")

    b = brands(con, say)
    v = vocab(con, say)
    o = oblasts(con, say)

    DIMENSIONS.write_text(json.dumps({
        "oblasts": [{"code": c, "name": n} for c, n in dims.OBLASTS],
        "fuel_groups": dims.FUEL_GROUPS,
        "age_bands": dims.AGE_BANDS,
        "days_bins": dims.DAYS_BINS,
        "owner_types": dims.OWNER_TYPES,
        "owner_labels": dims.OWNER_LABELS,
        "colors": v["colors"],
        "bodies": v["bodies"],
        "kinds": v["kinds"],
        "brand_counts": b,
        "koatuu_by_year": o,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    say("dimensions written to build/dimensions.json")
    print(f"report: {say.save()}")


if __name__ == "__main__":
    main()
