"""
Merge all reestrTZ*.zip vehicle-registration archives in this folder into
one CSV, straight from the zips (no extraction to disk).

Handles the schema drift across years: column casing, VIN/POWER_KWT only
present in some years, and 2026's combined "code - name" operation column.

reestrTZ2022_part1.zip / part2.zip are skipped: their D_REG dates are
actually Jan-Mar 2021 (already covered by reestrTZ2021.zip), not 2022 as
their names claim. Only part3.zip is real 2022 data.

Usage: py merge_data.py
"""

from pathlib import Path

import pandas as pd
import zipfile

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "merged_registrations.csv"

SOURCES = [
    ("reestrTZ2013.zip", 2013),
    ("reestrTZ2014.zip", 2014),
    ("reestrTZ2015.zip", 2015),
    ("reestrTZ2016.zip", 2016),
    ("reestrTZ2017.zip", 2017),
    ("reestrTZ2018.zip", 2018),
    ("reestrTZ2019.zip", 2019),
    ("reestrTZ2020.zip", 2020),
    ("reestrTZ2021.zip", 2021),
    ("reestrTZ2022_part3.zip", 2022),
    ("reestrTZ2023.zip", 2023),
    ("reestrTZ2024.zip", 2024),
    ("reestrTZ2025.zip", 2025),
    ("reestrTZ2026.zip", 2026),
]

CANONICAL_COLUMNS = [
    "PERSON", "REG_ADDR_KOATUU", "OPER_CODE", "OPER_NAME", "D_REG",
    "DEP_CODE", "DEP", "BRAND", "MODEL", "VIN", "MAKE_YEAR", "COLOR",
    "KIND", "BODY", "PURPOSE", "FUEL", "CAPACITY", "OWN_WEIGHT",
    "TOTAL_WEIGHT", "N_REG_NEW", "POWER_KWT",
]

# Cyrillic look-alikes that sometimes stand in for Latin letters in a
# ".csv" extension (e.g. a Cyrillic "с" in "2019...сsv").
_HOMOGLYPHS = str.maketrans("асеорху" "АСЕОРХУ", "aceopxy" "ACEOPXY")


def looks_like_csv(filename: str) -> bool:
    return filename.translate(_HOMOGLYPHS).lower().endswith(".csv")


def fix_mojibake(name: str) -> str:
    # Zip entries with no UTF-8 flag are decoded as cp437 by Python; these
    # archives were built with cp866 names, so re-encode to bytes via
    # cp437 and decode as cp866 to recover the original text.
    try:
        return name.encode("cp437").decode("cp866")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name


def find_csv_member(zf: zipfile.ZipFile) -> str:
    names = [i.filename for i in zf.infolist() if not i.is_dir()]
    candidates = [
        n for n in names if looks_like_csv(n) or looks_like_csv(fix_mojibake(n))
    ]
    return max(candidates, key=lambda n: zf.getinfo(n).file_size)


def normalize_frame(df: pd.DataFrame, zip_name: str, year: int) -> pd.DataFrame:
    df.columns = [c.strip().upper() for c in df.columns]

    combined_col = next((c for c in df.columns if "CD.OPER_CODE" in c), None)
    if combined_col:
        split = df[combined_col].str.split(" - ", n=1, expand=True)
        df["OPER_CODE"] = split[0]
        df["OPER_NAME"] = split[1] if split.shape[1] > 1 else pd.NA
        df = df.drop(columns=[combined_col])

    df = df.reindex(columns=CANONICAL_COLUMNS)
    df["SOURCE_FILE"] = zip_name
    df["SOURCE_YEAR"] = year
    return df


def main() -> None:
    first = True
    for zip_name, year in SOURCES:
        zip_path = HERE / zip_name
        with zipfile.ZipFile(zip_path) as zf:
            member = find_csv_member(zf)
            with zf.open(member) as f:
                df = pd.read_csv(f, sep=";", dtype=str, encoding="utf-8")
        df = normalize_frame(df, zip_name, year)
        df.to_csv(
            OUT_PATH,
            sep=";",
            index=False,
            mode="w" if first else "a",
            header=first,
            encoding="utf-8",
        )
        print(f"{zip_name}: {len(df)} rows -> {OUT_PATH.name}", flush=True)
        first = False


if __name__ == "__main__":
    main()
