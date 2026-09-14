"""Task 2: candidate vehicle-identifying columns -- null rate, cardinality,
masked example formats, and whether the column exists in the raw schema at
all (vs. exists but happens to be empty). Writes reports/02_candidate_keys.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

CANDIDATES = ["VIN", "N_REG_NEW", "PERSON", "DEP_CODE"]
MASKERS = {"VIN": c.mask_vin, "N_REG_NEW": c.mask_plate}


def null_cond(col: str) -> str:
    return f"({col} IS NULL OR TRIM(UPPER({col})) IN ('', 'NULL'))"


def raw_presence(label: str) -> set[str]:
    zip_name = next(zf for zf, lbl, _ in c.SOURCES if lbl == label)
    csv_path, _, _ = c.extract_csv(zip_name, label)
    return {h.strip().strip('"').upper() for h in c.read_header(csv_path)}


def main():
    con = c.connect()
    r = c.Reporter()
    r.print("### Candidate vehicle-identifying columns\n")

    for cand in CANDIDATES:
        r.print(f"#### {cand}\n")
        r.print("| year | in raw schema? | rows | null rate | distinct (non-null) | example (masked) |")
        r.print("|---|---|---|---|---|---|")
        for zf, label, year in c.SOURCES:
            view = c.register_canonical_view(con, label, year)
            present = cand in raw_presence(label)
            total = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            nulls = con.execute(
                f"SELECT SUM(CASE WHEN {null_cond(cand)} THEN 1 ELSE 0 END) FROM {view}"
            ).fetchone()[0] or 0
            distinct = con.execute(
                f"SELECT COUNT(DISTINCT CASE WHEN NOT {null_cond(cand)} THEN {cand} END) FROM {view}"
            ).fetchone()[0]
            example_row = con.execute(
                f"SELECT {cand} FROM {view} WHERE NOT {null_cond(cand)} LIMIT 1"
            ).fetchone()
            example = example_row[0] if example_row else None
            masker = MASKERS.get(cand)
            example_disp = masker(example) if masker else (example if example is not None else "<null>")
            null_rate = nulls / total if total else 0.0
            r.print(
                f"| {label} | {'yes' if present else 'no'} | {total:,} | {null_rate:.1%} | "
                f"{distinct:,} | {example_disp} |"
            )
        r.print("")

    r.print("### Notes\n")
    r.print("- `PERSON` is a single-char owner-type flag (`P`=physical, `J`=juridical), cardinality 2 -- "
            "not a vehicle (or owner) identifier, listed here only because the task asked every column "
            "that could identify a vehicle to be checked; it cannot.")
    r.print("- `DEP_CODE` identifies the *servicing department*, not the vehicle; included as context for "
            "the 2016 registration-anywhere rule check in task 3, not as a candidate key.")
    r.print("- `VIN` and `N_REG_NEW` (plate) are the only real vehicle-identifying candidates; their "
            "year-coverage is disjoint (see task 1 matrix) -- this is the central constraint for task 3.")

    out = r.save("02_candidate_keys.md")
    print(f"\n[saved: {out}]")


if __name__ == "__main__":
    main()
