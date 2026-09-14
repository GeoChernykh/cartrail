"""Phase 3 -- fetch, validate and commit the oblast polygons.

The choropleth needs real geometry, and the site must never fetch from an
external host at runtime: a CDN dependency is a page that breaks silently a
year from now. So the geometry is fetched at BUILD time, validated hard,
simplified, and written into docs/data/ to be committed.

Source: geoBoundaries gbOpen UKR ADM1 (simplified). Verified to carry exactly
27 features, each with a `shapeISO` of the form UA-xx. ISO 3166-2:UA and KOATUU
are two different numbering schemes -- five oblasts do not match numerically --
so the crosswalk is the explicit table in dims.ISO_TO_KOATUU and every one of
the 27 must resolve or the build fails.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dims

API_URL = "https://www.geoboundaries.org/api/current/gbOpen/UKR/ADM1/"
COORD_DECIMALS = 4          # ~11 m; far finer than a national choropleth needs
MIN_RING_AREA = 0.001       # square degrees, ~12 km2 here -- drops slivers only
MAX_BYTES = 800_000

OUT = dims.DOCS_DATA / "oblasts.geojson"
GEO_META = dims.BUILD_DIR / "geo_meta.json"


def fetch(url: str, say) -> bytes:
    say(f"fetching {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "CarTrailUA-build/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def candidates(say) -> list[tuple[str, dict]]:
    """Ordered candidate sources. Every URL is treated as unverified -- the
    caller validates, it never trusts."""
    out = []
    try:
        meta = json.loads(fetch(API_URL, say))
        if isinstance(meta, list):
            meta = meta[0]
        url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
        if url:
            out.append((url, {
                "source": "geoBoundaries gbOpen UKR ADM1 (simplified)",
                "license": meta.get("boundaryLicense"),
                "license_detail": meta.get("licenseDetail"),
                "source_url": meta.get("boundarySourceURL"),
                "download_url": url,
                "build_date": meta.get("buildDate"),
            }))
    except Exception as exc:                                  # noqa: BLE001
        say(f"  geoBoundaries API unavailable: {type(exc).__name__}: {exc}")
    return out


def round_ring(ring: list) -> list:
    out = []
    for x, y in ring:
        p = (round(x, COORD_DECIMALS), round(y, COORD_DECIMALS))
        if not out or out[-1] != p:
            out.append(p)
    if len(out) >= 3 and out[0] != out[-1]:
        out.append(out[0])
    return out


def signed_area(ring: list) -> float:
    """Shoelace area in square degrees; positive when the ring is wound
    counter-clockwise in (lon, lat)."""
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += x1 * y2 - x2 * y1
    return a / 2.0


def ring_area(ring: list) -> float:
    return abs(signed_area(ring))


def rewind(ring: list, exterior: bool) -> list:
    """Wind rings the way d3-geo reads them: exterior CLOCKWISE in (lon, lat),
    holes counter-clockwise -- the opposite of RFC 7946.

    This is not cosmetic. d3-geo clips on the sphere, so a ring wound the other
    way is read as its own complement: the oblast renders as *everything except*
    that oblast, every feature covers the globe (`d3.geoArea` returns 4π),
    `fitSize` sees world-sized bounds, and the map collapses to a few pixels
    inside a solid block of colour. Measured directly against this file:
    the source rings give geoArea 12.5653 ≈ 4π, the reversed rings 0.001025.
    Normalised once, here, at build time."""
    clockwise = signed_area(ring) < 0
    return ring if clockwise == exterior else ring[::-1]


def ring_centroid(ring: list) -> tuple[float, float, float]:
    """Polygon centroid plus its unsigned area, both by the shoelace formula."""
    cx = cy = a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if a == 0:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2.0


def simplify(geom: dict) -> tuple[dict, tuple[float, float]]:
    """Round coordinates, drop sliver rings, and return the centroid of the
    largest remaining ring (the arc layer anchors on it)."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    kept = []
    best = (None, -1.0)
    for poly in polys:
        rings = []
        for i, ring in enumerate(poly):
            r = round_ring(ring)
            if len(r) < 4:
                continue
            area = ring_area(r)
            if i == 0 and area < MIN_RING_AREA:
                break                      # the whole polygon is a sliver
            if i > 0 and area < MIN_RING_AREA:
                continue                   # a sliver hole
            if i == 0:
                cx, cy, a = ring_centroid(r)
                if a > best[1]:
                    best = ((cx, cy), a)
            rings.append([list(p) for p in rewind(r, exterior=(i == 0))])
        if rings:
            kept.append(rings)
    if not kept:
        raise ValueError("every ring was dropped as a sliver")
    out = ({"type": "MultiPolygon", "coordinates": kept} if len(kept) > 1
           else {"type": "Polygon", "coordinates": kept[0]})
    return out, best[0]


def build(raw: bytes, meta: dict, say) -> dict:
    fc = json.loads(raw)
    if fc.get("type") != "FeatureCollection":
        raise ValueError(f"not a FeatureCollection: {fc.get('type')!r}")
    feats = fc["features"]
    if len(feats) != 27:
        raise ValueError(f"expected exactly 27 features, got {len(feats)}")

    seen: dict[str, str] = {}
    out_feats = []
    for f in feats:
        props = f.get("properties") or {}
        iso = (props.get("shapeISO") or "").strip().upper()
        koatuu = dims.ISO_TO_KOATUU.get(iso)
        if not koatuu:
            raise ValueError(
                f"shapeISO {iso!r} ({props.get('shapeName')!r}) is not in "
                "dims.ISO_TO_KOATUU -- ISO 3166-2:UA is not KOATUU, extend the table"
            )
        if koatuu in seen:
            raise ValueError(f"KOATUU {koatuu} claimed twice: {seen[koatuu]} and {iso}")
        seen[koatuu] = iso
        geom, centroid = simplify(f["geometry"])
        out_feats.append({
            "type": "Feature",
            "properties": {
                "koatuu": koatuu,
                "name_uk": dims.OBLAST_NAMES[koatuu],
                "name_en": props.get("shapeName"),
                "cx": round(centroid[0], COORD_DECIMALS),
                "cy": round(centroid[1], COORD_DECIMALS),
            },
            "geometry": geom,
        })

    missing = sorted(set(dims.OBLAST_CODES) - set(seen))
    if missing:
        raise ValueError(f"no polygon resolved for KOATUU prefixes {missing}")
    say("  all 27 features resolved to distinct KOATUU prefixes")

    # Guard the winding fix: with clockwise exteriors every feature would cover
    # the globe, so the collection's own bounding box is the cheap tell.
    xs, ys = [], []
    for f in out_feats:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                for x, y in ring:
                    xs.append(x)
                    ys.append(y)
    box = (min(xs), min(ys), max(xs), max(ys))
    say(f"  bounding box: {[round(v, 2) for v in box]}")
    if not (21.0 < box[0] and box[2] < 41.5 and 43.0 < box[1] and box[3] < 53.0):
        raise ValueError(f"geometry leaves Ukraine's bounding box: {box}")
    for f in out_feats:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            if signed_area([tuple(p) for p in poly[0]]) >= 0:
                raise ValueError(
                    f"{f['properties']['name_uk']}: exterior ring is not "
                    "clockwise; d3-geo would render its complement")
    out_feats.sort(key=lambda f: f["properties"]["koatuu"])
    return {"type": "FeatureCollection", "meta": meta, "features": out_feats}


def main() -> None:
    say = dims.Report("12_build_geo.md")
    say("# Phase 3 -- oblast polygons\n")
    dims.DOCS_DATA.mkdir(parents=True, exist_ok=True)
    dims.BUILD_DIR.mkdir(parents=True, exist_ok=True)

    for url, meta in candidates(say):
        try:
            fc = build(fetch(url, say), meta, say)
        except Exception as exc:                              # noqa: BLE001
            say(f"  rejected: {type(exc).__name__}: {exc}")
            continue

        payload = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
        OUT.write_text(payload, encoding="utf-8")
        size = OUT.stat().st_size
        say(f"\nwrote {OUT} -- {size:,} bytes, {len(fc['features'])} features")
        say(f"source:  {meta['source']}")
        say(f"licence: {meta.get('license')} ({meta.get('license_detail')})")
        say(f"origin:  {meta.get('source_url')}")
        if size > MAX_BYTES:
            dims.fail(f"oblasts.geojson is {size:,} bytes, over the {MAX_BYTES:,} budget")
        GEO_META.write_text(
            json.dumps({**meta, "mode": "polygons", "bytes": size,
                        "centroids": {f["properties"]["koatuu"]:
                                      [f["properties"]["cx"], f["properties"]["cy"]]
                                      for f in fc["features"]}},
                       ensure_ascii=False),
            encoding="utf-8")
        say(f"\nreport: {say.save()}")
        return

    # PLAN.md Phase 3 step 5: never ship a half-matched polygon layer. Without a
    # validated source there is no geometry at all, and the fallback bubble map
    # would need a hand-built centroid table -- fail loudly instead of guessing.
    dims.fail(
        "no candidate GeoJSON source validated. Add a source to candidates() or "
        "supply docs/data/oblasts.geojson manually; do not ship partial geometry."
    )


if __name__ == "__main__":
    main()
