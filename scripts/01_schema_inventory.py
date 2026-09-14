"""Task 1: schema inventory. Per-year columns, row count, encoding, delimiter,
quoting; year x column presence matrix; flag renames. Writes reports/01_schema_inventory.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c


def main():
    con = c.connect()
    r = c.Reporter()
    rows = []
    presence = {}
    for zip_name, label, year in c.SOURCES:
        csv_path, member, encoding = c.extract_csv(zip_name, label)
        raw_header = c.read_header(csv_path)
        cleaned = [h.strip().strip('"').upper() for h in raw_header]
        quoted = raw_header[0].startswith('"') if raw_header else False
        cnt = con.execute(
            f"SELECT COUNT(*) FROM read_csv('{csv_path.as_posix()}', delim=';', header=true, quote='\"', all_varchar=true)"
        ).fetchone()[0]
        presence[label] = set(cleaned)
        rows.append({
            "label": label, "year": year, "zip": zip_name, "member": member,
            "encoding": encoding, "quoted": quoted, "rows": cnt,
            "n_cols": len(cleaned), "raw_header": raw_header,
        })
        r.print(f"{label}: {cnt:,} rows, {len(cleaned)} cols, encoding={encoding}, quoted_header={quoted}, member={member}")

    r.print("\n### Year x canonical-column presence matrix\n")
    header = "| column | " + " | ".join(row["label"] for row in rows) + " |"
    sep = "|---|" + "---|" * len(rows)
    r.print(header)
    r.print(sep)
    for col in c.CANONICAL_COLUMNS:
        cells = []
        for row in rows:
            has = col in presence[row["label"]] or (
                col in ("OPER_CODE", "OPER_NAME") and any("CD.OPER_CODE" in h for h in presence[row["label"]])
            )
            cells.append("x" if has else "")
        r.print(f"| {col} | " + " | ".join(cells) + " |")

    r.print("\n### Notable schema-drift flags\n")
    r.print("- 2013-2018: lowercase, unquoted header, no VIN, no POWER_KWT.")
    r.print("- 2019-2025: uppercase, quoted header; VIN appears from 2021 onward.")
    r.print("- 2026: fuses OPER_CODE+OPER_NAME into one column containing 'CD.OPER_CODE'; "
            "drops REG_ADDR_KOATUU, DEP_CODE, N_REG_NEW; adds POWER_KWT; date format changes to DD.MM.YY.")

    r.print("\n### Raw headers (verbatim, for the record)\n")
    for row in rows:
        r.print(f"- **{row['label']}**: `{';'.join(row['raw_header'])}`")

    out = r.save("01_schema_inventory.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
