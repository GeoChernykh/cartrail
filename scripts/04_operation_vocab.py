"""Task 4: operation-type vocabulary. Distinct (OPER_CODE, OPER_NAME) pairs per
year with counts, classified into lifecycle categories. Writes
reports/04_operation_vocab.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

classify = c.classify_operation


def main():
    con = c.connect()
    r = c.Reporter()
    r.print("### Operation-type vocabulary per year\n")

    all_unclassified = set()
    for zf, label, year in c.SOURCES:
        view = c.register_canonical_view(con, label, year)
        rows = con.execute(f"""
            SELECT OPER_CODE, OPER_NAME, COUNT(*) AS n
            FROM {view}
            GROUP BY OPER_CODE, OPER_NAME
            ORDER BY n DESC
        """).fetchall()
        r.print(f"#### {label} ({len(rows)} distinct (code, name) pairs)\n")
        r.print("| code | classification | count | name |")
        r.print("|---|---|---|---|")
        for code, name, n in rows[:40]:
            cls = classify(name)
            if cls.startswith("UNCLASSIFIED"):
                all_unclassified.add((label, code, name))
            r.print(f"| {code} | {cls} | {n:,} | {name} |")
        if len(rows) > 40:
            r.print(f"| ... | | | ({len(rows)-40} more, long tail) |")
        r.print("")

    r.print("### Unclassified values (need manual review)\n")
    if all_unclassified:
        r.print("| year | code | name |")
        r.print("|---|---|---|")
        for label, code, name in sorted(all_unclassified):
            r.print(f"| {label} | {code} | {name} |")
    else:
        r.print("None -- every distinct operation name matched one of the four classification rules.")

    out = r.save("04_operation_vocab.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
