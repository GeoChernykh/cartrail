"""Phase 6 -- docs/data/meta.json: every dictionary and every caveat figure.

The front-end resolves all integer codes in the flow cube against the
dictionaries here, and every data caveat it shows is driven by a number written
by this build -- notably the per-year KOATUU valid rate behind the 2020 flag.
No caveat in the UI is a hardcoded string.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import duckdb

import dims

P = f"'{dims.PARQUET.as_posix()}'"
OUT = dims.DOCS_DATA / "meta.json"

# Columns that define a duplicate row: everything the registry published, not
# the values this pipeline derived from them.
DUP_COLS = ("person, koatuu, oper_code, d_reg, brand_raw, model_raw, vin, "
            "make_year, color, kind, body, fuel, capacity, plate")


def read_json(path: Path, what: str) -> dict:
    if not path.exists():
        dims.fail(f"{path} not found -- run {what} first")
    return json.loads(path.read_text(encoding="utf-8"))


def per_year(con, say) -> list[dict]:
    rows = con.execute(f"""
        SELECT source_year, COUNT(*) AS n, COUNT(koatuu) AS k, COUNT(vin) AS v
        FROM {P} GROUP BY 1 ORDER BY 1
    """).fetchall()
    say("\n| year | rows | KOATUU valid | VIN present |")
    say("|---|---|---|---|")
    out = []
    for y, n, k, v in rows:
        out.append({"year": y, "rows": n,
                    "koatuu_valid_pct": round(100.0 * k / n, 2),
                    "vin_pct": round(100.0 * v / n, 2)})
        say(f"| {y} | {n:,} | {100.0 * k / n:.2f}% | {100.0 * v / n:.2f}% |")
    return out


def duplicate_rows(con, say) -> dict:
    """data_diagnostic.md section 6 flags 2025 for 1.43% exact-duplicate rows.
    Same-day events cannot become moves, so the migration cube is unaffected --
    but per-year registration counts on Screen 2 do include them, so the figure
    is measured here rather than quoted."""
    out = {}
    say("\n| year | exact-duplicate rows | share |")
    say("|---|---|---|")
    for y in dims.ALL_YEARS:
        n, d = con.execute(f"""
            SELECT COUNT(*), COUNT(*) - COUNT(DISTINCT ({DUP_COLS}))
            FROM {P} WHERE source_year = {y}
        """).fetchone()
        out[str(y)] = round(100.0 * d / n, 3)
        say(f"| {y} | {d:,} | {100.0 * d / n:.3f}% |")
    return out


def main() -> None:
    if not dims.PARQUET.exists():
        dims.fail(f"{dims.PARQUET} not found -- run 10_stage_parquet.py first")
    t0 = time.time()
    say = dims.Report("15_build_meta.md")
    say("# Phase 6 -- meta.json\n")

    dimensions = read_json(dims.BUILD_DIR / "dimensions.json", "11_dimensions.py")
    geo = read_json(dims.BUILD_DIR / "geo_meta.json", "12_build_geo.py")
    mig = read_json(dims.BUILD_DIR / "migration_meta.json", "13_build_migration.py")
    mod = read_json(dims.BUILD_DIR / "model_meta.json", "14_build_models.py")

    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    con.execute("SET preserve_insertion_order=false")
    years = per_year(con, say)
    dupes = duplicate_rows(con, say)

    meta = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name": "Відомості про транспортні засоби та їх власників",
            "publisher": "Міністерство внутрішніх справ України",
            "portal": "data.gov.ua",
            "dataset": "https://data.gov.ua/dataset/06779371-308f-42d7-895e-5a39833375f0",
            "rows": dims.EXPECTED_TOTAL,
            "years": [dims.ALL_YEARS[0], dims.ALL_YEARS[-1]],
            "excluded_archives": list(dims.EXCLUDED_SOURCE_FILES),
        },
        "geo": {k: geo.get(k) for k in
                ("source", "license", "license_detail", "source_url", "mode")},
        "centroids": geo.get("centroids", {}),
        "dict": {
            "oblasts": dimensions["oblasts"],
            "fuel_groups": dims.FUEL_GROUPS,
            "fuel_unknown": dims.FUEL_UNKNOWN,
            "age_bands": dims.AGE_BANDS,
            "age_band_edges": dims.AGE_BAND_EDGES,
            "age_unknown": dims.AGE_UNKNOWN,
            "days_bins": dims.DAYS_BINS,
            "days_bin_edges": dims.DAYS_BIN_EDGES,
            "owner_types": dims.OWNER_TYPES,
            "owner_labels": dims.OWNER_LABELS,
            "colors": mod["colors"],
            "bodies": mod["bodies"],
        },
        "windows": {
            "all": dims.ALL_YEARS,
            "migration": dims.MIGRATION_YEARS,
            "vin": dims.VIN_YEARS,
            "geography": [dims.ALL_YEARS[0], 2025],
        },
        "years": years,
        "duplicate_row_pct": dupes,
        "migration": mig,
        "models": {k: mod[k] for k in
                   ("threshold", "models_included", "brands_included")},
        "events": dims.EVENTS,
        "brands": dimensions["brand_counts"],
    }
    dims.DOCS_DATA.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    say(f"\nwrote {OUT} — {OUT.stat().st_size / 1024:,.0f} KB")
    say(f"elapsed: {time.time() - t0:,.1f}s")
    print(f"report: {say.save()}")


if __name__ == "__main__":
    main()
