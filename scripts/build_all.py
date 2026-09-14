"""Run the whole offline pipeline, 10 -> 15, and stop at the first failure.

    .venv\\Scripts\\python.exe scripts\\build_all.py

Every stage asserts its own gates and exits non-zero when one fails, so no
stage can quietly produce half-valid JSON for the next one to build on.

Pass --skip-stage to start from a later stage when only the tail changed, e.g.
`--skip-stage 10 11` to reuse an existing build/registrations.parquet.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dims

HERE = Path(__file__).resolve().parent
STAGES = [
    ("10", "10_stage_parquet.py", "stage typed Parquet"),
    ("11", "11_dimensions.py", "dimensions and vocabulary gates"),
    ("12", "12_build_geo.py", "oblast polygons"),
    ("13", "13_build_migration.py", "migration cube"),
    ("14", "14_build_models.py", "model scorecards"),
    ("15", "15_build_meta.py", "meta.json"),
]

SIZE_BUDGET = 25 * 1024 * 1024
FILE_BUDGET = 5 * 1024 * 1024


def size_report() -> int:
    files = sorted(dims.DOCS_DATA.rglob("*"), key=lambda p: -p.stat().st_size
                   if p.is_file() else 0)
    total = sum(p.stat().st_size for p in files if p.is_file())
    print(f"\ndocs/data total: {total / 1024 / 1024:,.2f} MB "
          f"(budget {SIZE_BUDGET / 1024 / 1024:.0f} MB)")
    print("largest files:")
    over = []
    for p in [f for f in files if f.is_file()][:8]:
        print(f"  {p.relative_to(dims.DOCS_DATA)}  {p.stat().st_size / 1024:,.0f} KB")
    for p in files:
        if p.is_file() and p.stat().st_size > FILE_BUDGET:
            over.append(p)
    if total > SIZE_BUDGET:
        dims.fail(f"docs/data is {total / 1024 / 1024:,.1f} MB, over the 25 MB budget. "
                  "Raise MODEL_MIN_ROWS, then drop fuel from the cube, then drop days_hist.")
    if over:
        dims.fail(f"files over the 5 MB per-file budget: {[p.name for p in over]}")
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-stage", nargs="*", default=[],
                    help="stage numbers to skip, e.g. 10 11")
    args = ap.parse_args()

    t0 = time.time()
    for num, script, what in STAGES:
        if num in args.skip_stage:
            print(f"\n=== {num} {what} — skipped ===", flush=True)
            continue
        print(f"\n=== {num} {what} ===", flush=True)
        t = time.time()
        r = subprocess.run([sys.executable, str(HERE / script)])
        if r.returncode != 0:
            raise SystemExit(f"\nBUILD FAILED at stage {num} ({script}), "
                             f"exit {r.returncode}")
        print(f"--- {num} ok in {time.time() - t:,.1f}s", flush=True)

    size_report()
    print(f"\nbuild complete in {time.time() - t0:,.1f}s")


if __name__ == "__main__":
    main()
