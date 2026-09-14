"""Shared helpers for the vehicle-registration linkage diagnostic.

Nothing here transforms registration data values. Column aliasing exists only
to give cross-year SQL a stable name for the same field when the raw header
casing/wording differs by year (documented per-year in 01_schema_inventory).
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import sys
import zipfile
from pathlib import Path

import duckdb

# This console's stdout encoding can't represent every Cyrillic codepoint
# (homoglyph characters in some source filenames, etc.); never let a print()
# crash the run -- the saved UTF-8 report files are the authoritative record.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

_job_dir = os.environ.get("CLAUDE_JOB_DIR")
SCRATCH_DIR = (Path(_job_dir) / "tmp" if _job_dir else REPO_ROOT / "_scratch") / "extracted"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

# (zip filename, label, calendar year the resource is published under)
SOURCES = [
    ("reestrTZ2013.zip", "2013", 2013),
    ("reestrTZ2014.zip", "2014", 2014),
    ("reestrTZ2015.zip", "2015", 2015),
    ("reestrTZ2016.zip", "2016", 2016),
    ("reestrTZ2017.zip", "2017", 2017),
    ("reestrTZ2018.zip", "2018", 2018),
    ("reestrTZ2019.zip", "2019", 2019),
    ("reestrTZ2020.zip", "2020", 2020),
    ("reestrTZ2021.zip", "2021", 2021),
    ("reestrTZ2022_part1.zip", "2022_part1", 2022),
    ("reestrTZ2022_part2.zip", "2022_part2", 2022),
    ("reestrTZ2022_part3.zip", "2022_part3", 2022),
    ("reestrTZ2023.zip", "2023", 2023),
    ("reestrTZ2024.zip", "2024", 2024),
    ("reestrTZ2025.zip", "2025", 2025),
    ("reestrTZ2026.zip", "2026", 2026),
]

SAMPLE_LABELS = ["2014", "2018", "2022_part3", "2025"]  # user's stratified-sample years (2022 -> the genuine part)

CANONICAL_COLUMNS = [
    "PERSON", "REG_ADDR_KOATUU", "OPER_CODE", "OPER_NAME", "D_REG",
    "DEP_CODE", "DEP", "BRAND", "MODEL", "VIN", "MAKE_YEAR", "COLOR",
    "KIND", "BODY", "PURPOSE", "FUEL", "CAPACITY", "OWN_WEIGHT",
    "TOTAL_WEIGHT", "N_REG_NEW", "POWER_KWT",
]

# Cyrillic look-alike -> Latin. Covers the 9 pairs the task calls out, plus H
# (Н/H) and I (Ukrainian І/I) which empirically also appear in plate text.
HOMOGLYPH_MAP = str.maketrans(
    "АВЕКМНОРСТХІ",
    "ABEKMHOPCTXI",
)


# --------------------------------------------------------------------------
# Zip member access / encoding
# --------------------------------------------------------------------------

def find_csv_member(zf: zipfile.ZipFile) -> str:
    """Pick the largest non-directory entry -- every archive here holds exactly one CSV."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    return max(infos, key=lambda i: i.file_size).filename


def peek_bytes(zip_filename: str, n: int = 65536) -> tuple[str, bytes]:
    """Return (member_name, first n raw bytes) without extracting."""
    with zipfile.ZipFile(DATA_DIR / zip_filename) as zf:
        member = find_csv_member(zf)
        with zf.open(member) as f:
            raw = f.read(n)
    return member, raw


def detect_encoding(raw: bytes) -> str:
    """Try utf-8, then cp1251; require the decode to actually succeed on a
    line boundary (trim to the last newline to avoid truncation artifacts)."""
    cut = raw.rfind(b"\n")
    sample = raw[:cut] if cut > 0 else raw
    for enc in ("utf-8", "cp1251"):
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "unknown"


def extract_csv(zip_filename: str, label: str) -> tuple[Path, str, str]:
    """Extract the CSV member to SCRATCH_DIR, transcoding to utf-8 if needed.
    Returns (path, member_name, detected_encoding). Cached across calls."""
    out_path = SCRATCH_DIR / f"{label}.csv"
    with zipfile.ZipFile(DATA_DIR / zip_filename) as zf:
        member = find_csv_member(zf)
        with zf.open(member) as f:
            header_bytes = f.read(65536)
        encoding = detect_encoding(header_bytes)
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path, member, encoding
        with zf.open(member) as f:
            if encoding == "utf-8":
                with open(out_path, "wb") as out:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        out.write(chunk)
            else:
                src_enc = encoding if encoding != "unknown" else "cp1251"
                with io.TextIOWrapper(f, encoding=src_enc, errors="replace") as tin, \
                        open(out_path, "w", encoding="utf-8", newline="") as tout:
                    for line in tin:
                        tout.write(line)
    return out_path, member, encoding


# --------------------------------------------------------------------------
# DuckDB view construction
# --------------------------------------------------------------------------

def read_header(csv_path: Path, delim: str = ";") -> list[str]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        first_line = f.readline()
    reader = csv.reader(io.StringIO(first_line), delimiter=delim, quotechar='"')
    return next(reader)


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


# D_REG drifts format across years: 2013-2018 ISO, 2019-2022 DD.MM.YYYY,
# 2023-2026 DD.MM.YY (2-digit year). Detected per-year, not assumed.
_DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "%d.%m.%Y"),
    (re.compile(r"^\d{2}\.\d{2}\.\d{2}$"), "%d.%m.%y"),
]


def norm_plate_sql(column: str = "N_REG_NEW") -> str:
    """SQL that normalizes a plate column the same way normalize_plate() does:
    strip whitespace/dashes, uppercase, fold the Cyrillic look-alikes, NULL out
    the empty and literal-'NULL' values."""
    return (
        f"CASE WHEN {column} IS NULL OR TRIM(UPPER({column})) IN ('', 'NULL') THEN NULL "
        f"ELSE NULLIF(TRANSLATE(UPPER(TRIM(REGEXP_REPLACE({column}, '[\\s\\-]', '', 'g'))), "
        "'АВЕКМНОРСТХ', 'ABEKMHOPCTX'), '') END"
    )


def detect_date_format(sample: str) -> str | None:
    s = (sample or "").strip()
    for pattern, fmt in _DATE_PATTERNS:
        if pattern.match(s):
            return fmt
    return None


def register_canonical_view(con: duckdb.DuckDBPyConnection, label: str, year: int) -> str:
    """Extract+create a view `canon_{label}` exposing CANONICAL_COLUMNS plus
    SOURCE_LABEL/SOURCE_YEAR/D_REG_DATE, aliased from whatever this year's
    real header is (D_REG_DATE is D_REG parsed per that year's detected
    date-string format -- see _DATE_PATTERNS)."""
    zip_filename = next(zf for zf, lbl, _ in SOURCES if lbl == label)
    csv_path, member, encoding = extract_csv(zip_filename, label)
    raw_header = read_header(csv_path)
    cleaned = [h.strip().strip('"').upper() for h in raw_header]

    view_name = f"raw_{label}"
    con.execute(f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT * FROM read_csv(
            '{csv_path.as_posix()}',
            delim=';', header=true, quote='"', all_varchar=true,
            names={cleaned!r}
        )
    """)

    fused_idx = next((c for c in cleaned if "CD.OPER_CODE" in c), None)

    select_parts = []
    for canon in CANONICAL_COLUMNS:
        if canon in ("OPER_CODE", "OPER_NAME") and fused_idx:
            continue
        if canon in cleaned:
            select_parts.append(f'"{canon}" AS {canon}')
        else:
            select_parts.append(f"CAST(NULL AS VARCHAR) AS {canon}")

    if fused_idx:
        select_parts.append(
            f'TRIM(SPLIT_PART("{fused_idx}", \' - \', 1)) AS OPER_CODE'
        )
        select_parts.append(
            f'TRIM(SUBSTR("{fused_idx}", LENGTH(SPLIT_PART("{fused_idx}", \' - \', 1)) + 4)) AS OPER_NAME'
        )

    select_parts.append(f"'{label}' AS SOURCE_LABEL")
    select_parts.append(f"{year} AS SOURCE_YEAR")

    pre_view = f"pre_canon_{label}"
    con.execute(f"CREATE OR REPLACE VIEW {pre_view} AS SELECT {', '.join(select_parts)} FROM {view_name}")

    sample = con.execute(f"SELECT D_REG FROM {pre_view} WHERE D_REG IS NOT NULL LIMIT 1").fetchone()
    fmt = detect_date_format(sample[0]) if sample else None
    date_expr = f"TRY_STRPTIME(D_REG, '{fmt}')::DATE" if fmt else "CAST(NULL AS DATE)"

    norm_plate_expr = norm_plate_sql()

    canon_view = f"canon_{label}"
    con.execute(
        f"CREATE OR REPLACE VIEW {canon_view} AS "
        f"SELECT *, {date_expr} AS D_REG_DATE, {norm_plate_expr} AS NORM_PLATE FROM {pre_view}"
    )
    return canon_view


def register_all(con: duckdb.DuckDBPyConnection, labels: list[str] | None = None) -> list[str]:
    labels = labels or [lbl for _, lbl, _ in SOURCES]
    views = []
    for zf, lbl, year in SOURCES:
        if lbl in labels:
            views.append(register_canonical_view(con, lbl, year))
    return views


def union_view(con: duckdb.DuckDBPyConnection, views: list[str], name: str = "all_years") -> str:
    con.execute(f"CREATE OR REPLACE VIEW {name} AS " + " UNION ALL ".join(f"SELECT * FROM {v}" for v in views))
    return name


# --------------------------------------------------------------------------
# Plate/VIN normalization, hashing, masking (privacy)
# --------------------------------------------------------------------------

def normalize_plate(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip().upper().replace(" ", "").replace("-", "")
    if s in ("", "NULL"):
        return None
    return s.translate(HOMOGLYPH_MAP)


def key_bucket(s: str, buckets: int = 1000) -> int:
    """Deterministic hash bucket in [0, buckets) for key-space sampling."""
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()
    return int(h, 16) % buckets


def mask_plate(raw: str | None) -> str:
    if not raw:
        return "<null>"
    s = raw.strip()
    if len(s) <= 4:
        return s[0] + "•" * max(len(s) - 1, 0)
    return s[:2] + "•" * (len(s) - 4) + s[-2:]


def mask_vin(raw: str | None) -> str:
    if not raw:
        return "<null>"
    s = raw.strip()
    if len(s) <= 7:
        return s[0] + "•" * max(len(s) - 1, 0)
    return s[:3] + "•" * (len(s) - 7) + s[-4:]


def is_null_token(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().upper() in ("", "NULL"))


# --------------------------------------------------------------------------
# Operation-type classification (task 4), shared with the lifecycle check (5)
# --------------------------------------------------------------------------

CLASSIFY_RULES = [
    ("de-registration/export/scrapping", re.compile(r"ЗНЯТТ|ВИВЕЗ|УТИЛІЗ|ВИБРАКОВК|ЕКСПОРТ", re.I)),
    ("first registration", re.compile(r"ПЕРВИНН", re.I)),
    ("re-registration/ownership transfer", re.compile(
        r"ПЕРЕРЕЄСТРАЦ.{0,40}(НОВОГО ВЛАСН|НА НОВ|УСПАДКУВ)|ПЕРЕХІД ПРАВА|ДОГОВОР.{0,20}КУП", re.I)),
    ("administrative change", re.compile(
        r"ЗАМІН.{0,20}(НОМЕРН|СВІДОЦТВ|КУЗОВ|ДВИГУН)|ВТРАТ.{0,20}СВІДОЦТВ|ПЕРЕОБЛАДНАНН|"
        r"ВИДАЧ|ДУБЛІКАТ|ТИМЧАС|ПОВЕРНЕНН.{0,20}ДОРУЧ|ДОРУЧ", re.I)),
]


def classify_operation(name: str | None) -> str:
    if not name:
        return "UNCLASSIFIED (empty)"
    for label, pattern in CLASSIFY_RULES:
        if pattern.search(name):
            return label
    return "UNCLASSIFIED"


# --------------------------------------------------------------------------
# Reporting -- writes UTF-8 files directly so Cyrillic survives regardless of
# console codepage quirks when a script's stdout is relayed through a shell.
# --------------------------------------------------------------------------

REPORTS_DIR = SCRATCH_DIR.parent / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class Reporter:
    def __init__(self):
        self.lines: list[str] = []

    def print(self, *args):
        s = " ".join(str(a) for a in args)
        print(s)
        self.lines.append(s)

    def save(self, filename: str) -> Path:
        path = REPORTS_DIR / filename
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return path
