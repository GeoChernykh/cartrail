"""
Download the "Vidomosti pro transportni zasoby ta yikh vlasnykiv" (MVS)
dataset from data.gov.ua and build a schema inventory of the downloaded
zip archives.

Usage (from any directory, via the `py` launcher on Windows):
    py download_and_inventory.py                 # download missing files, then report
    py download_and_inventory.py --report-only    # skip downloads, just (re)build the report
    py download_and_inventory.py --download-only  # download missing files, skip the report

Re-running is safe: any file that already exists, is a valid zip, and is at
least ~70% of its expected size is skipped. Downloads are streamed to a
"<name>.part" file and only renamed to the final name on success; a failed
or interrupted download leaves no partial file behind under the final name.

Stdlib only -- no pip install required.
"""

import argparse
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_URL = "https://data.gov.ua/dataset/0ffd8b75-0628-48cc-952a-9302f9799ec0/resource"
LOG_PATH = HERE / "download_log.txt"
REPORT_PATH = HERE / "_inventory.md"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# (resource_id, download_path, local file name, approx size in MB from data.gov.ua)
RESOURCES = [
    ("86a9548b-8323-4fa2-972e-0692edf6959f", "download/tz_opendata_z01012013_po31122013.zip", "reestrTZ2013.zip", 97),
    ("80a115ae-61df-4a13-8771-36c2826268df", "download/tz_opendata_z01012014_po31122014.zip", "reestrTZ2014.zip", 72),
    ("09c606dc-d740-40db-96f0-e679eeca6ace", "download/tz_opendata_z01012015_po31122015.zip", "reestrTZ2015.zip", 62),
    ("7bdc2a1b-5399-4ab0-97e0-633e68837b04", "download/tz_opendata_z01012016_po31122016.zip", "reestrTZ2016.zip", 59),
    ("9ce32352-bd11-4324-a2b4-5addbd228b1b", "download/tz_opendata_z01012017_po31122017.zip", "reestrTZ2017.zip", 59),
    ("01323740-88df-46c2-b06e-fbb58c89fe17", "download/tz_opendata_z01012018_po01012019.zip", "reestrTZ2018.zip", 66),
    ("7a58e8f7-9323-47d4-a21d-19486e014eb4", "download/tz_opendata_z01012019_po01012020.zip", "reestrTZ2019.zip", 87),
    ("ebeb92fe-424c-41d1-aacf-288e91049dc9", "download/tz_opendata_z01012020_po01012021.zip", "reestrTZ2020.zip", 70),
    ("c5cb530d-0533-40be-b9ad-f03e06c94b10", "download/tz_opendata_z01012021_po01012022.zip", "reestrTZ2021.zip", 104),
    ("bef7b47b-7963-44b5-88a8-f84241137b5b", "download/reestrtz2022.zip", "reestrTZ2022_part1.zip", 13),
    ("fb6d9eb4-875e-45c9-be51-d49b6875b9eb", "download/reestrtz2022.zip", "reestrTZ2022_part2.zip", 21),
    ("b1bcb4a9-8e60-4a1c-91c0-00faae008816", "download/reestrtz2022.zip", "reestrTZ2022_part3.zip", 90),
    ("c3a12388-55c2-4546-8b71-b4b7ff0d8b16", "download/reestrtz2023.zip", "reestrTZ2023.zip", 111),
    ("c3ffecc4-bb5c-4102-b761-6dcfeb60b4fe", "download/reestrtz2024.zip", "reestrTZ2024.zip", 112),
    ("b7e72d22-55f5-4545-87dc-94e6c8ee03ef", "download/reestrtz2025.zip", "reestrTZ2025.zip", 114),
    ("3f13166f-090b-499e-8e23-e9851c5a5f67", "download/reestrtz2026.zip", "reestrTZ2026.zip", 49),
]

PLAUSIBLE_FRACTION = 0.70  # a file must be at least this fraction of its expected size


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_plausible(path: Path, expected_mb: float) -> bool:
    if not path.exists():
        return False
    if path.stat().st_size < expected_mb * 1024 * 1024 * PLAUSIBLE_FRACTION:
        return False
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def download(url: str, dest: Path) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            written = 0
            chunk_size = 1024 * 1024
            next_report = 0
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if written >= next_report:
                    mb = written / (1024 * 1024)
                    if total:
                        log(f"  {dest.name}: {mb:.0f} MB / {total / (1024 * 1024):.0f} MB")
                    else:
                        log(f"  {dest.name}: {mb:.0f} MB")
                    next_report += 10 * 1024 * 1024
        if not zipfile.is_zipfile(part):
            raise zipfile.BadZipFile(f"{dest.name} did not download as a valid zip")
        part.replace(dest)
        log(f"OK  {dest.name} ({dest.stat().st_size / (1024 * 1024):.1f} MB)")
    except (urllib.error.URLError, urllib.error.HTTPError, zipfile.BadZipFile, OSError) as exc:
        if part.exists():
            part.unlink()
        raise RuntimeError(f"{dest.name}: {exc}") from exc


def do_downloads() -> list[str]:
    failed = []
    for resource_id, path, fname, expected_mb in RESOURCES:
        dest = HERE / fname
        if is_plausible(dest, expected_mb):
            log(f"SKIP {fname} (already present, {dest.stat().st_size / (1024 * 1024):.1f} MB)")
            continue
        url = f"{BASE_URL}/{resource_id}/{path}"
        log(f"GET  {fname} <- {url}")
        try:
            download(url, dest)
        except RuntimeError as exc:
            log(f"FAIL {exc}")
            failed.append(str(exc))
    return failed


def fix_mojibake(name: str) -> str:
    # Zip names with no UTF-8 flag are decoded by Python as cp437. These
    # archives were built on Cyrillic DOS/Windows, so the *original* bytes
    # are cp866 -- re-encode back to bytes via cp437, then decode as cp866.
    try:
        fixed = name.encode("cp437").decode("cp866")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name
    if any("Ѐ" <= ch <= "ӿ" for ch in fixed) and not any(
        "Ѐ" <= ch <= "ӿ" for ch in name
    ):
        return fixed
    return name


# Cyrillic look-alike letters that sometimes turn up inside otherwise-Latin
# file extensions (e.g. a Cyrillic "с" where "c" was meant) -- normalize
# before checking for a ".csv" suffix.
_HOMOGLYPHS = str.maketrans(
    "асеорху" "АСЕОРХУ", "aceopxy" "ACEOPXY"
)


def looks_like_csv(filename: str) -> bool:
    return filename.translate(_HOMOGLYPHS).lower().endswith(".csv")


def decode_header(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def count_lines(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> int:
    newline_count = 0
    last_byte = b""
    with zf.open(info) as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        newline_count += 1  # last line has no trailing newline
    return newline_count


def inspect_zip(path: Path) -> dict:
    result = {"csvs": [], "error": None}
    try:
        with zipfile.ZipFile(path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            names = [fix_mojibake(i.filename) for i in infos]
            csv_infos = [
                i for i, n in zip(infos, names) if looks_like_csv(n) or looks_like_csv(i.filename)
            ]
            result["names"] = names
            if not csv_infos:
                return result
            largest = max(csv_infos, key=lambda i: i.file_size)
            with zf.open(largest) as f:
                first_line = f.readline()
            header = decode_header(first_line).rstrip("\r\n")
            row_count = count_lines(zf, largest)
            data_rows = max(row_count - 1, 0)
            result["csvs"] = [
                {
                    "name": fix_mojibake(i.filename),
                    "uncompressed_mb": i.file_size / (1024 * 1024),
                }
                for i in csv_infos
            ]
            result["largest_csv"] = fix_mojibake(largest.filename)
            result["header"] = header
            result["data_rows"] = data_rows
    except zipfile.BadZipFile as exc:
        result["error"] = str(exc)
    return result


def build_report() -> str:
    lines = []
    lines.append("| File | Size on disk | CSVs inside | Largest CSV rows | Largest CSV header |")
    lines.append("|---|---|---|---|---|")
    detail_lines = []
    for _, _, fname, _ in RESOURCES:
        path = HERE / fname
        if not path.exists():
            lines.append(f"| {fname} | (missing) | - | - | - |")
            continue
        size_mb = path.stat().st_size / (1024 * 1024)
        info = inspect_zip(path)
        if info.get("error"):
            lines.append(f"| {fname} | {size_mb:.1f} MB | ERROR: {info['error']} | - | - |")
            continue
        csv_names = ", ".join(c["name"] for c in info["csvs"]) or "(no CSV found)"
        row_count = info.get("data_rows", "-")
        header = info.get("header", "-")
        lines.append(f"| {fname} | {size_mb:.1f} MB | {csv_names} | {row_count} | `{header}` |")
        detail_lines.append(f"### {fname}")
        detail_lines.append(f"- size on disk: {size_mb:.1f} MB")
        detail_lines.append(f"- entries: {', '.join(info.get('names', [])) or '(none)'}")
        if info.get("csvs"):
            detail_lines.append(f"- largest CSV: {info['largest_csv']} ({info.get('data_rows')} data rows)")
            detail_lines.append(f"- header: `{info.get('header')}`")
        detail_lines.append("")
    report = "\n".join(lines) + "\n\n" + "\n".join(detail_lines)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()

    failed = []
    if not args.report_only:
        log("=== starting download pass ===")
        failed = do_downloads()
        log("=== download pass complete ===")
        if failed:
            log(f"FAILED ({len(failed)}): " + "; ".join(failed))
        else:
            log("all files present and valid")

    if not args.download_only:
        log("=== building inventory report ===")
        report = build_report()
        REPORT_PATH.write_text(report, encoding="utf-8")
        print("\n" + report)
        log(f"report written to {REPORT_PATH}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
