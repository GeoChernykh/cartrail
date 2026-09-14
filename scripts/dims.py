"""Dimension tables shared by the whole build pipeline (10 -> 15).

Every value here is measured against the real series, not assumed -- see
`11_dimensions.py`, which re-derives the vocabularies from the staged Parquet
and fails the build if anything here stops matching the data.

Kept separate from `common.py` because `common.py` belongs to the diagnostic
pass and must keep working unchanged.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

# The console codepage cannot represent every Cyrillic codepoint; never let a
# print() kill a multi-minute build. The saved UTF-8 reports are authoritative.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / "build"
REPORTS_DIR = BUILD_DIR / "reports"
DOCS_DATA = REPO_ROOT / "docs" / "data"
PARQUET = BUILD_DIR / "registrations.parquet"

# --------------------------------------------------------------------------
# Series shape -- asserted by 10_stage_parquet.py against the merged CSV.
# Figures come from data_diagnostic.md section 1 and were re-verified directly.
# --------------------------------------------------------------------------

EXPECTED_ROWS = {
    2013: 1_935_496, 2014: 1_439_551, 2015: 1_296_256, 2016: 1_432_560,
    2017: 1_417_655, 2018: 1_547_418, 2019: 2_079_481, 2020: 1_771_329,
    2021: 2_201_307, 2022: 1_745_908, 2023: 2_124_732, 2024: 2_344_544,
    2025: 2_229_904, 2026: 1_221_092,
}
EXPECTED_TOTAL = 24_787_233

# reestrTZ2022_part1/_part2 are 95.9%/95.8% exact-row duplicates of 2021 with
# Jan-Mar 2021 dates (data_diagnostic.md section 6). data/merge_data.py already
# leaves them out; 10_stage_parquet.py asserts that they really are absent.
EXCLUDED_SOURCE_FILES = ("reestrTZ2022_part1.zip", "reestrTZ2022_part2.zip")

# D_REG drifts format across eras; merge_data.py never parsed it, so the raw
# strings survive in the merged CSV and have to be parsed per source year.
DATE_FORMATS = {y: "%Y-%m-%d" for y in range(2013, 2019)}
DATE_FORMATS.update({y: "%d.%m.%Y" for y in range(2019, 2023)})
DATE_FORMATS.update({y: "%d.%m.%y" for y in range(2023, 2027)})

# The migration cube is VIN-keyed and needs REG_ADDR_KOATUU, so it can only
# cover the window where both exist. 2026 has no KOATUU at all.
MIGRATION_YEARS = list(range(2021, 2026))
# VIN exists 2021-2026, so VIN-keyed model metrics may use the wider window.
VIN_YEARS = list(range(2021, 2027))
ALL_YEARS = list(range(2013, 2027))

# --------------------------------------------------------------------------
# Oblasts: legacy 10-digit KOATUU, first two digits. The dataset uses KOATUU
# throughout -- no year carries UA-prefixed KATOTTG codes.
# --------------------------------------------------------------------------

OBLASTS: list[tuple[str, str]] = [
    ("01", "АР Крим"),
    ("05", "Вінницька"),
    ("07", "Волинська"),
    ("12", "Дніпропетровська"),
    ("14", "Донецька"),
    ("18", "Житомирська"),
    ("21", "Закарпатська"),
    ("23", "Запорізька"),
    ("26", "Івано-Франківська"),
    ("32", "Київська"),
    ("35", "Кіровоградська"),
    ("44", "Луганська"),
    ("46", "Львівська"),
    ("48", "Миколаївська"),
    ("51", "Одеська"),
    ("53", "Полтавська"),
    ("56", "Рівненська"),
    ("59", "Сумська"),
    ("61", "Тернопільська"),
    ("63", "Харківська"),
    ("65", "Херсонська"),
    ("68", "Хмельницька"),
    ("71", "Черкаська"),
    ("73", "Чернівецька"),
    ("74", "Чернігівська"),
    ("80", "м. Київ"),
    ("85", "м. Севастополь"),
]
assert len(OBLASTS) == 27, "the oblast crosswalk must have exactly 27 entries"
OBLAST_CODES = [c for c, _ in OBLASTS]
OBLAST_NAMES = dict(OBLASTS)
OBLAST_INDEX = {c: i for i, c in enumerate(OBLAST_CODES)}

# ISO 3166-2:UA -> KOATUU prefix. These are two different numbering schemes:
# five entries do NOT match numerically, so "strip UA- and use the digits"
# silently mis-assigns Crimea, Luhansk, Chernivtsi, Kyiv city and Sevastopol.
ISO_TO_KOATUU = {
    "UA-43": "01", "UA-05": "05", "UA-07": "07", "UA-12": "12", "UA-14": "14",
    "UA-18": "18", "UA-21": "21", "UA-23": "23", "UA-26": "26", "UA-32": "32",
    "UA-35": "35", "UA-09": "44", "UA-46": "46", "UA-48": "48", "UA-51": "51",
    "UA-53": "53", "UA-56": "56", "UA-59": "59", "UA-61": "61", "UA-63": "63",
    "UA-65": "65", "UA-68": "68", "UA-71": "71", "UA-77": "73", "UA-74": "74",
    "UA-30": "80", "UA-40": "85",
}
assert sorted(ISO_TO_KOATUU.values()) == sorted(OBLAST_CODES)

# --------------------------------------------------------------------------
# Vocabularies. FUEL/COLOR/KIND each have 13-14 distinct values across the
# whole 24.8M-row series, so these maps are exhaustive rather than best-effort.
# BODY has 466 distinct values and is handled as "top N + Інше" instead.
# --------------------------------------------------------------------------

# The last entry is not a fuel: it is the bucket for rows where FUEL is empty.
# Rows are never dropped from the cube for a missing attribute -- dropping them
# would quietly shrink the denominator of every share the UI shows.
FUEL_UNKNOWN = "Не вказано"
FUEL_GROUPS = ["Бензин", "Дизель", "Газ/бігаз", "Гібрид", "Електро", "Інше",
               FUEL_UNKNOWN]
FUEL_GROUP_MAP = {
    "БЕНЗИН": "Бензин",
    "ДИЗЕЛЬНЕ ПАЛИВО": "Дизель",
    "БЕНЗИН АБО ГАЗ": "Газ/бігаз",
    "ГАЗ": "Газ/бігаз",
    "ДИЗЕЛЬНЕ ПАЛИВО АБО ГАЗ": "Газ/бігаз",
    "ЕЛЕКТРО АБО БЕНЗИН": "Гібрид",
    "ЕЛЕКТРО АБО ДИЗЕЛЬНЕ ПАЛИВО": "Гібрид",
    "БЕНЗИН, ГАЗ АБО ЕЛЕКТРО": "Гібрид",
    "ГАЗ ТА ЕЛЕКТРО": "Гібрид",
    "ЕЛЕКТРО": "Електро",
    "ВОДЕНЬ": "Інше",
    "НЕ ВИЗНАЧЕНО": "Інше",
    "ВІДСУТНЄ": "Інше",
    ".": "Інше",
}

# Three spellings of orange are published; they are one colour.
COLOR_CANON = {
    "ПОМАРАНЧЕВИЙ (ОРАНЖЕВИЙ)": "ОРАНЖЕВИЙ",
    "ЖОВТОГАРЯЧИЙ": "ОРАНЖЕВИЙ",
    "НЕВИЗНАЧЕНИЙ": "ІНШИЙ",
}

BODY_TOP_N = 12
COLOR_TOP_N = 10

# --------------------------------------------------------------------------
# Cube dimensions. Age and days are stored as band indexes so the flow cube
# stays small; the client band-interpolates a median for any filter combo.
# --------------------------------------------------------------------------

# The last band is "no usable age": MAKE_YEAR missing, or an age outside the
# plausibility window the Parquet already applies (0-60 years), which is why the
# 21+ band stops at 60 rather than running to infinity.
AGE_UNKNOWN = "Не визначено"
AGE_BANDS = ["0–3", "4–7", "8–12", "13–20", "21+", AGE_UNKNOWN]
# Edges are used to band-interpolate a median; the unknown bucket has none and
# is excluded from that interpolation while still counting toward volumes.
AGE_BAND_EDGES = [(0, 3), (4, 7), (8, 12), (13, 20), (21, 60)]

DAYS_BINS = ["0–30", "31–90", "91–180", "181–365", "366–730",
             "731–1095", "1096–1460", "1461+"]
DAYS_BIN_EDGES = [(0, 30), (31, 90), (91, 180), (181, 365), (366, 730),
                  (731, 1095), (1096, 1460), (1461, 3650)]

OWNER_TYPES = ["P", "J"]
OWNER_LABELS = {"P": "Фізична особа", "J": "Юридична особа"}

MIN_CELL = 3           # build-time suppression floor per cube cell
CUBE_CELL_LIMIT = 60_000   # above this, drop days_hist (see PLAN.md Phase 4)
MODEL_MIN_ROWS = 500       # model inclusion threshold, 2013-2026

# --------------------------------------------------------------------------
# Brand normalization.
#
# BRAND frequently contains brand + model ("SSANG YONG  REXTON" with MODEL
# "REXTON"), which is why the suffix strip runs before anything else: it takes
# the distinct-brand count from 36,515 to 4,267. The alias table below only
# mops up what survives that; it is built from build/reports/brands.md, not
# from memory, and 11_dimensions.py regenerates that report every run.
# --------------------------------------------------------------------------

BRAND_ALIASES = {
    "SSANG YONG": "SSANGYONG",
    "SSANG-YONG": "SSANGYONG",
    "SSANGYONG MOTOR": "SSANGYONG",
    "MERCEDES BENZ": "MERCEDES-BENZ",
    "MERCEDES": "MERCEDES-BENZ",
    "VW": "VOLKSWAGEN",
    "LADA": "ВАЗ",
    "LADA (ВАЗ)": "ВАЗ",
    "ВАЗ (LADA)": "ВАЗ",
    "LAND-ROVER": "LAND ROVER",
    "LANDROVER": "LAND ROVER",
    "ALFA ROMEO": "ALFA-ROMEO",
    "ROLLS ROYCE": "ROLLS-ROYCE",
    "GREAT WALL": "GREATWALL",
    # Trailer makers published under two transliterations of the same umlaut.
    "KOEGEL": "KOGEL",
    "SCHWARZMUELLER": "SCHWARZMULLER",
    "SCHMITZ CARGOBULL": "SCHMITZ",
}

# Annotations drawn on every time axis. The 2022 duty-free import window is the
# only one needing a source: customs duty, VAT and excise on imported cars were
# lifted from 1 April 2022 (law signed 5 April) and restored from 1 July 2022.
EVENTS = [
    {"date": "2014-03-01", "label": "Анексія Криму, початок війни на сході"},
    {"date": "2020-03-12", "label": "Карантин COVID-19"},
    {"date": "2022-02-24", "label": "Повномасштабне вторгнення"},
    {"date": "2022-04-01", "end": "2022-06-30",
     "label": "Безмитний імпорт авто (1 квітня – 30 червня 2022)"},
]

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "ы": "y",
    "э": "e", "ъ": "", "ё": "e",
}


class Report:
    """Echo to stdout and keep a UTF-8 copy under build/reports/."""

    def __init__(self, filename: str):
        self.filename = filename
        self.lines: list[str] = []

    def __call__(self, *args):
        s = " ".join(str(a) for a in args)
        print(s, flush=True)
        self.lines.append(s)

    def save(self) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / self.filename
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return path


def fail(msg: str):
    """Assertions in this pipeline must stop the build, not warn."""
    raise SystemExit(f"BUILD FAILED: {msg}")


def sql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def normalize_ws(s: str | None) -> str | None:
    """Upper, trim, collapse internal whitespace runs to one space."""
    if s is None:
        return None
    out = re.sub(r"\s+", " ", s.strip().upper())
    return out or None


def strip_model_suffix(brand: str | None, model: str | None) -> str | None:
    """`BRAND` often ends with `" " + MODEL`; the leading token(s) are the brand."""
    if not brand or not model:
        return brand
    suffix = " " + model
    if brand.endswith(suffix) and len(brand) > len(suffix):
        return brand[: -len(suffix)].strip() or brand
    return brand


def canon_brand(brand: str | None, model: str | None) -> str | None:
    b = strip_model_suffix(normalize_ws(brand), normalize_ws(model))
    return BRAND_ALIASES.get(b, b) if b else None


def slug(name: str) -> str:
    """Filename-safe ASCII slug; Cyrillic brand names are transliterated so the
    shard files stay portable across filesystems and URLs."""
    s = unicodedata.normalize("NFKD", name.lower())
    out = []
    for ch in s:
        if ch in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch)
        elif unicodedata.combining(ch):
            continue
        else:
            out.append("-")
    res = re.sub(r"-+", "-", "".join(out)).strip("-")
    return res or "x"
