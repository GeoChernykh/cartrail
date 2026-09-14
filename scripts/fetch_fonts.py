"""Vendor the Inter web font into docs/fonts/ and regenerate its @font-face CSS.

    .venv\\Scripts\\python.exe scripts\\fetch_fonts.py

Standalone, like the vendored d3 bundle -- not part of build_all.py, because the
output is committed and only changes when the font does. The site must never
fetch from an external host at runtime, so the .woff2 files are downloaded here
and referenced by relative path.

Google serves Inter as a VARIABLE font: one file per unicode subset covering the
whole 100-900 weight axis, so every weight the design uses costs four files
total, not twelve. The `unicode-range` values are copied straight out of
Google's stylesheet rather than transcribed by hand -- getting one wrong makes
the browser silently skip a subset, and Ukrainian would fall back mid-sentence.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dims

CSS_URL = ("https://fonts.googleapis.com/css2"
           "?family=Inter:wght@400..700&display=swap")
# Without a desktop User-Agent Google serves legacy TTF instead of woff2.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

WANTED = ("latin", "latin-ext", "cyrillic", "cyrillic-ext")
FONT_DIR = dims.REPO_ROOT / "docs" / "fonts"
APP_CSS = dims.REPO_ROOT / "docs" / "css" / "app.css"

BEGIN = "/* --- generated: inter @font-face --- */"
END = "/* --- end generated --- */"

# One @font-face block in Google's CSS, preceded by a /* subset */ comment.
BLOCK = re.compile(
    r"/\*\s*(?P<subset>[a-z-]+)\s*\*/\s*@font-face\s*\{(?P<body>[^}]*)\}", re.S)


def get(url: str) -> bytes:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()


def faces(css: str) -> dict[str, tuple[str, str]]:
    """subset -> (woff2 url, unicode-range), keeping the first of each subset.
    The weight axis is on the file, so the duplicate blocks per weight are the
    same URL and only one is needed."""
    out: dict[str, tuple[str, str]] = {}
    for m in BLOCK.finditer(css):
        subset = m.group("subset")
        if subset not in WANTED or subset in out:
            continue
        body = m.group("body")
        url = re.search(r"url\((\S+?)\)", body)
        rng = re.search(r"unicode-range:\s*([^;]+);", body)
        if not (url and rng):
            raise SystemExit(f"{subset}: no woff2 url or unicode-range in {body[:120]!r}")
        out[subset] = (url.group(1), rng.group(1).strip())
    missing = [s for s in WANTED if s not in out]
    if missing:
        raise SystemExit(f"Google's CSS did not carry these subsets: {missing}")
    return out


def render_css(entries: dict[str, tuple[str, str]]) -> str:
    blocks = [
        BEGIN,
        "/* Inter, variable (100-900) per unicode subset. Regenerate with",
        "   scripts/fetch_fonts.py -- do not hand-edit between these markers. */",
    ]
    for subset in WANTED:
        _, rng = entries[subset]
        blocks.append(
            "@font-face {\n"
            "  font-family: 'Inter';\n"
            "  font-style: normal;\n"
            "  font-weight: 100 900;\n"
            "  font-display: swap;\n"
            f"  src: url('../fonts/inter-{subset}.woff2') format('woff2');\n"
            f"  unicode-range: {rng};\n"
            "}"
        )
    blocks.append(END)
    return "\n".join(blocks)


def splice(css_text: str, generated: str) -> str:
    start = css_text.find(BEGIN)
    if start == -1:
        # First run: put the faces at the very top, ahead of :root.
        return f"{generated}\n\n{css_text.lstrip()}"
    stop = css_text.find(END, start)
    if stop == -1:
        raise SystemExit(f"{APP_CSS}: found {BEGIN!r} with no matching {END!r}")
    return css_text[:start] + generated + css_text[stop + len(END):]


def main() -> None:
    print(f"fetching {CSS_URL}")
    entries = faces(get(CSS_URL).decode())

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for subset in WANTED:
        url, _ = entries[subset]
        data = get(url)
        if data[:4] != b"wOF2":
            raise SystemExit(f"{subset}: not a woff2 file (got {data[:4]!r})")
        path = FONT_DIR / f"inter-{subset}.woff2"
        path.write_bytes(data)
        total += len(data)
        print(f"  {path.relative_to(dims.REPO_ROOT)}  {len(data):,} bytes")
    print(f"  total {total:,} bytes")

    text = APP_CSS.read_text(encoding="utf-8")
    APP_CSS.write_text(splice(text, render_css(entries)), encoding="utf-8")
    print(f"rewrote the generated @font-face region in "
          f"{APP_CSS.relative_to(dims.REPO_ROOT)}")


if __name__ == "__main__":
    main()
