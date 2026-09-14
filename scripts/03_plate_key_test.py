"""Task 3 (core question): is the plate (N_REG_NEW) a usable vehicle key?

Runs on the FULL union of all years where a plate column exists (2013-2021,
2022_part3, 2023-2025 -- 2022_part1/part2 excluded as ~96% duplicates of 2021,
see 06_known_traps.py) rather than a row-sample: DuckDB's out-of-core engine
makes a full-series GROUP BY tractable, and a naive row-sample would distort
exactly the statistics this task asks for (a vehicle's two events would only
co-occur in a 200k/1.4M-row sample ~2% of the time, making plates look almost
all singleton by sampling artifact alone, not by data reality).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

PLATE_LABELS = [lbl for _, lbl, _ in c.SOURCES if lbl not in ("2022_part1", "2022_part2", "2026")]


def main():
    con = c.connect()
    r = c.Reporter()
    views = c.register_all(con, PLATE_LABELS)
    series = c.union_view(con, views, "plate_series")

    total_rows = con.execute(f"SELECT COUNT(*) FROM {series}").fetchone()[0]
    r.print(f"### Plate-key test, full series ({', '.join(PLATE_LABELS)}), {total_rows:,} rows\n")

    # --- per-plate aggregate (normalized key) ---------------------------------
    con.execute(f"""
        CREATE TEMP TABLE plate_agg AS
        SELECT NORM_PLATE, COUNT(*) AS n,
               COUNT(DISTINCT BRAND) AS n_brand,
               COUNT(DISTINCT MAKE_YEAR) AS n_myear,
               MIN(D_REG_DATE) AS first_dt, MAX(D_REG_DATE) AS last_dt
        FROM {series}
        WHERE NORM_PLATE IS NOT NULL
        GROUP BY NORM_PLATE
    """)
    n_plates = con.execute("SELECT COUNT(*) FROM plate_agg").fetchone()[0]
    r.print(f"Distinct normalized plates: {n_plates:,}\n")

    r.print("#### Rows-per-plate distribution\n")
    dist = con.execute("""
        SELECT CASE WHEN n = 1 THEN '1' WHEN n = 2 THEN '2' WHEN n BETWEEN 3 AND 5 THEN '3-5'
                    WHEN n BETWEEN 6 AND 10 THEN '6-10' ELSE '11+' END AS bucket,
               COUNT(*) AS n_plates, SUM(n) AS n_rows
        FROM plate_agg GROUP BY bucket ORDER BY MIN(n)
    """).fetchall()
    r.print("| rows-per-plate | # plates | % of plates | # underlying rows |")
    r.print("|---|---|---|---|")
    for bucket, np_, nr in dist:
        r.print(f"| {bucket} | {np_:,} | {np_/n_plates:.1%} | {nr:,} |")

    multi = con.execute("SELECT COUNT(*) FROM plate_agg WHERE n >= 2").fetchone()[0]
    r.print(f"\nMulti-row plates: {multi:,} ({multi/n_plates:.1%} of all plates).\n")

    r.print("#### Brand+year-of-manufacture consistency within multi-row plates (normalized key)\n")
    const_n, changed_n = con.execute("""
        SELECT SUM(CASE WHEN n_brand = 1 AND n_myear = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN n_brand > 1 OR n_myear > 1 THEN 1 ELSE 0 END)
        FROM plate_agg WHERE n >= 2
    """).fetchone()
    r.print(f"- constant brand+year: {const_n:,} ({const_n/multi:.1%})")
    r.print(f"- brand or year changes: {changed_n:,} ({changed_n/multi:.1%})\n")

    # --- homoglyph/whitespace/case impact: raw-string key vs normalized key --
    r.print("#### How much of that inconsistency is normalization noise vs real reuse\n")
    con.execute(f"""
        CREATE TEMP TABLE raw_agg AS
        SELECT UPPER(TRIM(N_REG_NEW)) AS RAW_KEY, COUNT(*) AS n,
               COUNT(DISTINCT BRAND) AS n_brand, COUNT(DISTINCT MAKE_YEAR) AS n_myear
        FROM {series}
        WHERE N_REG_NEW IS NOT NULL AND TRIM(UPPER(N_REG_NEW)) NOT IN ('', 'NULL')
        GROUP BY RAW_KEY
    """)
    n_raw_keys = con.execute("SELECT COUNT(*) FROM raw_agg").fetchone()[0]
    collapse_pct = (n_raw_keys - n_plates) / n_raw_keys if n_raw_keys else 0
    r.print(f"- distinct raw (case/whitespace-trimmed only) keys: {n_raw_keys:,}")
    r.print(f"- distinct normalized (+ homoglyph-folded) keys: {n_plates:,}")
    r.print(f"- normalization collapses {collapse_pct:.1%} of raw-key variants into an existing key "
            f"(pure formatting noise, not new plates).\n")

    raw_multi, raw_const = con.execute("""
        SELECT SUM(CASE WHEN n >= 2 THEN 1 ELSE 0 END),
               SUM(CASE WHEN n >= 2 AND n_brand = 1 AND n_myear = 1 THEN 1 ELSE 0 END)
        FROM raw_agg
    """).fetchone()
    r.print(f"- brand+year constant among multi-row groups, RAW key: {raw_const/raw_multi:.1%} "
            f"(n={raw_multi:,}) vs NORMALIZED key: {const_n/multi:.1%} (n={multi:,}) "
            f"-> normalization raises apparent consistency by {(const_n/multi - raw_const/raw_multi)*100:.1f} pp.\n")

    # --- time-gap vs brand/year change -----------------------------------
    r.print("#### Time gap between events, constant vs changed multi-row plates\n")
    con.execute("""
        CREATE TEMP TABLE multi_rows AS
        SELECT s.NORM_PLATE, s.D_REG_DATE
        FROM plate_series s JOIN plate_agg a USING (NORM_PLATE)
        WHERE a.n >= 2 AND s.D_REG_DATE IS NOT NULL
    """)
    con.execute("""
        CREATE TEMP TABLE gaps AS
        SELECT NORM_PLATE, D_REG_DATE - LAG(D_REG_DATE) OVER (PARTITION BY NORM_PLATE ORDER BY D_REG_DATE) AS gap_days
        FROM multi_rows
    """)
    for label, cond in [("constant brand+year", "n_brand = 1 AND n_myear = 1"), ("brand or year changes", "n_brand > 1 OR n_myear > 1")]:
        med = con.execute(f"""
            SELECT MEDIAN(g.gap_days) FROM gaps g JOIN plate_agg a USING (NORM_PLATE)
            WHERE g.gap_days IS NOT NULL AND {cond}
        """).fetchone()[0]
        r.print(f"- median gap, {label}: {med} days")
    r.print("")

    # --- 2016 registration-anywhere rule: DEP_CODE vs REG_ADDR_KOATUU mismatch --
    r.print("#### Registering outside the owner's home region, by year (DEP_CODE vs REG_ADDR_KOATUU oblast prefix)\n")
    r.print("Restricted to years with 4-5 digit DEP_CODE (2016+); 2013-2015 use a 7-digit DEP_CODE whose "
            "first 2 digits are not a directly comparable oblast prefix (see 06_known_traps).\n")
    rows = con.execute(f"""
        SELECT SOURCE_YEAR,
               AVG(CASE WHEN LEFT(DEP_CODE,2) <> LEFT(REG_ADDR_KOATUU,2) THEN 1.0 ELSE 0.0 END) AS mismatch_rate,
               COUNT(*) AS n
        FROM {series}
        WHERE LENGTH(DEP_CODE) IN (4,5) AND LENGTH(REG_ADDR_KOATUU) = 10
        GROUP BY SOURCE_YEAR ORDER BY SOURCE_YEAR
    """).fetchall()
    r.print("| year | cross-region rate | n |")
    r.print("|---|---|---|")
    for year, rate, n in rows:
        r.print(f"| {year} | {rate:.1%} | {n:,} |")
    r.print("")

    # --- VIN cross-validation, 2021-2025 (only window with both keys) ------
    r.print("#### Ground-truth cross-validation: VIN vs plate, 2021-2025\n")
    con.execute(f"""
        CREATE TEMP TABLE dual AS
        SELECT VIN, NORM_PLATE, OPER_NAME
        FROM {series}
        WHERE SOURCE_YEAR BETWEEN 2021 AND 2025 AND VIN IS NOT NULL AND NORM_PLATE IS NOT NULL
    """)
    dual_n = con.execute("SELECT COUNT(*) FROM dual").fetchone()[0]
    r.print(f"Rows with both VIN and plate non-null, 2021-2025: {dual_n:,}\n")

    vin_multi_plate = con.execute("""
        SELECT COUNT(*) FROM (SELECT VIN FROM dual GROUP BY VIN HAVING COUNT(DISTINCT NORM_PLATE) > 1)
    """).fetchone()[0]
    vin_total = con.execute("SELECT COUNT(DISTINCT VIN) FROM dual").fetchone()[0]
    r.print(f"- VINs with >1 distinct plate (chain-break risk if keying by plate): "
            f"{vin_multi_plate:,} / {vin_total:,} ({vin_multi_plate/vin_total:.2%})")

    plate_multi_vin = con.execute("""
        SELECT COUNT(*) FROM (SELECT NORM_PLATE FROM dual GROUP BY NORM_PLATE HAVING COUNT(DISTINCT VIN) > 1)
    """).fetchone()[0]
    plate_total = con.execute("SELECT COUNT(DISTINCT NORM_PLATE) FROM dual").fetchone()[0]
    r.print(f"- Plates with >1 distinct VIN (false-merge risk if keying by plate): "
            f"{plate_multi_vin:,} / {plate_total:,} ({plate_multi_vin/plate_total:.2%})\n")

    explained = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT VIN FROM dual GROUP BY VIN HAVING COUNT(DISTINCT NORM_PLATE) > 1
        ) m
        WHERE EXISTS (
            SELECT 1 FROM dual d WHERE d.VIN = m.VIN AND d.OPER_NAME ILIKE '%НОМЕРН%ЗНАК%'
        )
    """).fetchone()[0]
    r.print(f"- Of the {vin_multi_plate:,} multi-plate VINs, {explained:,} ({explained/vin_multi_plate:.1%}) "
            f"have at least one row whose operation name mentions a plate/number-sign change "
            f"('...НОМЕРНОГО ЗНАКУ...') -- a real, explainable event rather than linkage noise.\n")

    out = r.save("03_plate_key_test.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
