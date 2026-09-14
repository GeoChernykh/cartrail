"""Task 5: lifecycle feasibility, using the plate key (the key that survived
task 3 for 2013-2025; 2026 has no plate at all -- see task 1/2). Runs on the
full plate series, same rationale as 03_plate_key_test.py (no row-sampling).
Writes reports/05_lifecycle.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

PLATE_LABELS = [lbl for _, lbl, _ in c.SOURCES if lbl not in ("2022_part1", "2022_part2", "2026")]

# Same rules as common.classify_operation, expressed in SQL for set-based aggregation.
EVENT_TYPE_SQL = """
    CASE
        WHEN REGEXP_MATCHES(OPER_NAME, 'ЗНЯТТ|ВИВЕЗ|УТИЛІЗ|ВИБРАКОВК|ЕКСПОРТ', 'i') THEN 'deregistration'
        WHEN REGEXP_MATCHES(OPER_NAME, 'ПЕРВИНН', 'i') THEN 'first_registration'
        WHEN REGEXP_MATCHES(OPER_NAME, 'ПЕРЕРЕЄСТРАЦ.{0,40}(НОВОГО ВЛАСН|НА НОВ|УСПАДКУВ)|ПЕРЕХІД ПРАВА|ДОГОВОР.{0,20}КУП', 'i') THEN 'transfer'
        WHEN REGEXP_MATCHES(OPER_NAME, 'ЗАМІН.{0,20}(НОМЕРН|СВІДОЦТВ|КУЗОВ|ДВИГУН)|ВТРАТ.{0,20}СВІДОЦТВ|ПЕРЕОБЛАДНАНН|ВИДАЧ|ДУБЛІКАТ|ТИМЧАС|ПОВЕРНЕНН.{0,20}ДОРУЧ|ДОРУЧ', 'i') THEN 'admin'
        ELSE 'unclassified'
    END
"""


def main():
    con = c.connect()
    r = c.Reporter()
    views = c.register_all(con, PLATE_LABELS)
    series = c.union_view(con, views, "plate_series")

    con.execute(f"""
        CREATE TEMP TABLE events AS
        SELECT NORM_PLATE, D_REG_DATE, {EVENT_TYPE_SQL} AS EVENT_TYPE
        FROM {series} WHERE NORM_PLATE IS NOT NULL
    """)

    con.execute("""
        CREATE TEMP TABLE plate_summary AS
        SELECT NORM_PLATE, COUNT(*) AS n_events,
               MAX(CASE WHEN EVENT_TYPE = 'deregistration' THEN 1 ELSE 0 END) AS has_terminal
        FROM events GROUP BY NORM_PLATE
    """)
    con.execute("""
        CREATE TEMP TABLE first_event AS
        SELECT NORM_PLATE, EVENT_TYPE FROM (
            SELECT NORM_PLATE, EVENT_TYPE, ROW_NUMBER() OVER (PARTITION BY NORM_PLATE ORDER BY D_REG_DATE) AS rn
            FROM events WHERE D_REG_DATE IS NOT NULL
        ) WHERE rn = 1
    """)

    n_plates = con.execute("SELECT COUNT(*) FROM plate_summary").fetchone()[0]
    r.print(f"### Lifecycle feasibility, plate key, {', '.join(PLATE_LABELS)} ({n_plates:,} distinct plates)\n")
    r.print("Caveat: the series starts 2013, so a plate first seen in 2013 whose first row is *not* a "
            "'first registration' event may simply be left-censored (the vehicle's real first "
            "registration predates the data), not evidence the key failed.\n")

    first_and_later = con.execute("""
        SELECT COUNT(*) FROM plate_summary p JOIN first_event f USING (NORM_PLATE)
        WHERE p.n_events >= 2 AND f.EVENT_TYPE = 'first_registration'
    """).fetchone()[0]
    r.print(f"- Plates with an observable first-registration event AND >=1 later event: "
            f"{first_and_later:,} / {n_plates:,} ({first_and_later/n_plates:.1%})")

    terminal = con.execute("SELECT SUM(has_terminal) FROM plate_summary").fetchone()[0]
    r.print(f"- Plates with an observable terminal (de-registration) event: "
            f"{terminal:,} / {n_plates:,} ({terminal/n_plates:.1%})\n")

    r.print("#### Events-per-vehicle distribution\n")
    dist = con.execute("""
        SELECT n_events, COUNT(*) AS n_plates FROM plate_summary
        GROUP BY n_events ORDER BY n_events LIMIT 15
    """).fetchall()
    r.print("| events | # plates | % |")
    r.print("|---|---|---|")
    for n_events, n_p in dist:
        r.print(f"| {n_events} | {n_p:,} | {n_p/n_plates:.2%} |")
    median_events = con.execute("SELECT MEDIAN(n_events) FROM plate_summary").fetchone()[0]
    r.print(f"\nMedian events per vehicle: {median_events}\n")

    r.print("#### Gap between consecutive events (plates with >=2 events)\n")
    con.execute("""
        CREATE TEMP TABLE gaps AS
        SELECT NORM_PLATE, D_REG_DATE - LAG(D_REG_DATE) OVER (PARTITION BY NORM_PLATE ORDER BY D_REG_DATE) AS gap_days
        FROM events WHERE D_REG_DATE IS NOT NULL
    """)
    med_gap, p25, p75 = con.execute(
        "SELECT MEDIAN(gap_days), QUANTILE_CONT(gap_days,0.25), QUANTILE_CONT(gap_days,0.75) "
        "FROM gaps WHERE gap_days IS NOT NULL"
    ).fetchone()
    r.print(f"Median gap: {med_gap} days (IQR {p25:.0f}-{p75:.0f} days).\n")

    out = r.save("05_lifecycle.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
