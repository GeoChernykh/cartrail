"""Task 6: known traps. 2022-split overlap, exact duplicate rows, KOATUU vs
KATOTTG, territorial coverage (Crimea/Donetsk/Luhansk), year-of-manufacture
outliers. Writes reports/06_known_traps.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

DATA_COLS = ", ".join(c.CANONICAL_COLUMNS)  # exact-row identity, excludes derived cols


def main():
    con = c.connect()
    r = c.Reporter()

    # --- 2022 split: overlap with 2021 ------------------------------------
    r.print("### 2022 split archives: overlap with reestrTZ2021.zip\n")
    for label in ["2021", "2022_part1", "2022_part2", "2022_part3"]:
        view = c.register_canonical_view(con, label, 0)
        n, mn, mx = con.execute(f"SELECT COUNT(*), MIN(D_REG_DATE), MAX(D_REG_DATE) FROM {view}").fetchone()
        r.print(f"- {label}: {n:,} rows, D_REG_DATE range {mn} .. {mx}")
    r.print("")
    for part in ["2022_part1", "2022_part2"]:
        overlap = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {DATA_COLS} FROM canon_2021
                INTERSECT SELECT {DATA_COLS} FROM canon_{part}
            )
        """).fetchone()[0]
        total = con.execute(f"SELECT COUNT(*) FROM canon_{part}").fetchone()[0]
        r.print(f"- {part}: {overlap:,}/{total:,} rows ({overlap/total:.1%}) are exact-row matches "
                f"against reestrTZ2021.zip -> confirms these are (almost entirely) 2021 data republished "
                f"under a 2022 filename, not genuine 2022 registrations. reestrTZ2022_part3.zip is the "
                f"only real 2022 resource; part1/part2 are excluded from all other analyses in this report.")
    r.print("")

    # --- exact duplicate rows within each year ----------------------------
    r.print("### Exact-duplicate rows within each year\n")
    r.print("| year | total rows | duplicate rows (extra copies beyond first) | % |")
    r.print("|---|---|---|---|")
    for zf, label, year in c.SOURCES:
        view = c.register_canonical_view(con, label, year)
        total = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        dup_extra = con.execute(f"""
            SELECT SUM(cnt - 1) FROM (
                SELECT COUNT(*) AS cnt FROM {view} GROUP BY {DATA_COLS} HAVING COUNT(*) > 1
            )
        """).fetchone()[0] or 0
        r.print(f"| {label} | {total:,} | {dup_extra:,} | {dup_extra/total:.2%} |")
    r.print("")

    # --- KOATUU vs KATOTTG -------------------------------------------------
    r.print("### KOATUU vs KATOTTG codifier, by year\n")
    r.print("| year | 10-digit numeric (KOATUU-style) | UA-prefixed (KATOTTG-style) | other/null | n |")
    r.print("|---|---|---|---|---|")
    for zf, label, year in c.SOURCES:
        view = c.register_canonical_view(con, label, year)
        row = con.execute(f"""
            SELECT
                SUM(CASE WHEN REGEXP_MATCHES(REG_ADDR_KOATUU, '^[0-9]{{10}}$') THEN 1 ELSE 0 END),
                SUM(CASE WHEN REG_ADDR_KOATUU LIKE 'UA%' THEN 1 ELSE 0 END),
                SUM(CASE WHEN REG_ADDR_KOATUU IS NULL
                          OR (NOT REGEXP_MATCHES(REG_ADDR_KOATUU, '^[0-9]{{10}}$') AND REG_ADDR_KOATUU NOT LIKE 'UA%')
                     THEN 1 ELSE 0 END),
                COUNT(*)
            FROM {view}
        """).fetchone()
        koatuu, katottg, other, n = row
        r.print(f"| {label} | {koatuu:,} ({koatuu/n:.1%}) | {katottg:,} ({katottg/n:.1%}) | {other:,} ({other/n:.1%}) | {n:,} |")
    r.print("")

    # --- territorial coverage: Crimea/Donetsk/Luhansk ---------------------
    r.print("### Territorial coverage: Crimea (01, 85=Sevastopol), Donetsk (14), Luhansk (44) KOATUU prefixes\n")
    r.print("Note: REG_ADDR_KOATUU is the *owner's registered address*, not the vehicle's current "
            "location or where it was serviced -- a displaced owner can keep an old-oblast code. "
            "DEP_CODE geography is a separate, more direct signal of where service actually happened.\n")
    r.print("| year | Crimea (01/85) | Donetsk (14) | Luhansk (44) | n |")
    r.print("|---|---|---|---|---|")
    for zf, label, year in c.SOURCES:
        view = c.register_canonical_view(con, label, year)
        row = con.execute(f"""
            SELECT
                SUM(CASE WHEN LEFT(REG_ADDR_KOATUU,2) IN ('01','85') THEN 1 ELSE 0 END),
                SUM(CASE WHEN LEFT(REG_ADDR_KOATUU,2) = '14' THEN 1 ELSE 0 END),
                SUM(CASE WHEN LEFT(REG_ADDR_KOATUU,2) = '44' THEN 1 ELSE 0 END),
                COUNT(*)
            FROM {view} WHERE LENGTH(REG_ADDR_KOATUU) = 10
        """).fetchone()
        cr, dn, lg, n = row
        if n:
            r.print(f"| {label} | {cr:,} ({cr/n:.2%}) | {dn:,} ({dn/n:.2%}) | {lg:,} ({lg/n:.2%}) | {n:,} |")
        else:
            r.print(f"| {label} | n/a | n/a | n/a | 0 (no 10-digit KOATUU values this year) |")
    r.print("")

    # --- year-of-manufacture outliers --------------------------------------
    r.print("### MAKE_YEAR outliers\n")
    r.print("| year | null | < 1900 | > current_year+1 | total | n |")
    r.print("|---|---|---|---|---|---|")
    for zf, label, year in c.SOURCES:
        view = c.register_canonical_view(con, label, year)
        row = con.execute(f"""
            SELECT
                SUM(CASE WHEN MAKE_YEAR IS NULL OR TRIM(UPPER(MAKE_YEAR)) IN ('','NULL') THEN 1 ELSE 0 END),
                SUM(CASE WHEN TRY_CAST(MAKE_YEAR AS INT) IS NOT NULL AND TRY_CAST(MAKE_YEAR AS INT) < 1900 THEN 1 ELSE 0 END),
                SUM(CASE WHEN TRY_CAST(MAKE_YEAR AS INT) IS NOT NULL AND TRY_CAST(MAKE_YEAR AS INT) > 2027 THEN 1 ELSE 0 END),
                COUNT(*)
            FROM {view}
        """).fetchone()
        null_n, low_n, high_n, n = row
        r.print(f"| {label} | {null_n:,} | {low_n:,} | {high_n:,} | {n:,} | |")

    out = r.save("06_known_traps.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
