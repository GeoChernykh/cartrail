# CarTrail UA

A two-screen static web app over Ukraine's vehicle-registration register:

- **Карта міграції авто** — where used cars move between oblasts. A net-balance
  choropleth with a flow-arc layer, a direction matrix, and a ranked corridor
  table, filtered by year range, owner type, fuel group, vehicle age band and
  minimum corridor volume. Click an oblast to pivot the whole screen to it.
- **Картка моделі** — a scorecard for any brand + model: registrations per year
  with event annotations, median age at registration, resale rate, median
  ownership duration, owner split, fuel/colour/body mix, regional concentration,
  and national rank over time. Two models can be compared on shared axes.

The interface is Ukrainian. Registry vocabularies (`FUEL`, `COLOR`, `BODY`,
`KIND`) are shown exactly as published — nothing is translated.

**Live site:** `https://<user>.github.io/<repo>/` *(fill in after the first deploy)*

## Data

**Source:** [Відомості про транспортні засоби та їх власників](https://data.gov.ua/dataset/06779371-308f-42d7-895e-5a39833375f0)
— Ministry of Internal Affairs of Ukraine, published on data.gov.ua as sixteen
yearly ZIP archives, 2013–2026. **24,787,233 rows**, one per registration action.
The register contains no owner names or addresses: `PERSON` is a single-character
owner-type flag and `REG_ADDR_KOATUU` is a regional code.

**Oblast boundaries:** geoBoundaries gbOpen UKR ADM1 (simplified), Open Data
Commons Open Database License 1.0. Fetched, validated and simplified at build
time, then committed to `docs/data/oblasts.geojson` — the site never fetches
from an external host at runtime.

There is no backend. The whole series is aggregated offline into ~3.7 MB of
static JSON that ships with the front-end.

## Caveats that shaped the product

Vehicle identity is split across the series: VIN exists only in 2021–2026 and the
plate only in 2013–2025, and in the overlap 26.0% of VINs carry more than one
plate — so every linkage here is VIN-only and no plate-keyed metric ships. The
migration map is therefore built on 2021–2025, the sole window where VIN and
KOATUU coexist, and a "move" is defined as *the first recorded registration in
that window → the next recorded event*, never as a vehicle's first registration:
the window is left-censored and the operation vocabulary is not reliably
classifiable. KOATUU is the **owner's registered address**, not the vehicle's
location, and the map says so on the map itself. Two of the three 2022 archives
are 95.9% / 95.8% exact-row duplicates of 2021 and are excluded everywhere. Only
77.2% of 2020 rows carry a valid 10-digit KOATUU, so 2020 geography is flagged in
the interface from a figure the build writes, not a hardcoded string. Falling
row shares for Crimea, Donetsk and Luhansk are absence from the register, not
absence from the country. Full detail is in `data_diagnostic.md`, and the app's
«Про дані» panel carries the same caveats with live figures.

## Rebuilding

Python dependencies (duckdb, pandas, numpy) are already in the local `.venv`.
There is no npm and no build step for the front-end.

```
.venv\Scripts\python.exe scripts\build_all.py     # stages 10 -> 15
.venv\Scripts\python.exe scripts\verify.py        # Phase 7 gates
```

`build_all.py` runs each stage in order and exits non-zero on the first failed
assertion, so no stage can quietly emit half-valid JSON. `--skip-stage 10 11`
reuses an existing `build/registrations.parquet` when only the tail changed.

| stage | script | output |
|---|---|---|
| 10 | `10_stage_parquet.py` | `build/registrations.parquet` (typed, 570 MB) |
| 11 | `11_dimensions.py` | brand map, vocabulary gates, `build/dimensions.json` |
| 12 | `12_build_geo.py` | `docs/data/oblasts.geojson` |
| 13 | `13_build_migration.py` | `docs/data/flows/flows_<year>.json` |
| 14 | `14_build_models.py` | `docs/data/models/` (index + per-brand shards) |
| 15 | `15_build_meta.py` | `docs/data/meta.json` |

The raw ZIPs, the 8.6 GB merged CSV and `build/` are gitignored. Stage 10 needs
`data/merged_registrations.csv`, produced by `data/merge_data.py`.

To preview the site locally:

```
cd docs
..\.venv\Scripts\python.exe -m http.server 8000
```

## Deploying

GitHub Pages serves `docs/` from `main` with no build step. Every path in the
front-end is relative, so the `/<repo>/` base path needs no configuration.

1. Create a **public** repository on github.com (Pages needs public on free plans).
2. `git remote add origin https://github.com/<user>/<repo>.git`
   then `git push -u origin main`.
3. **Settings → Pages → Source: Deploy from a branch → `main` → `/docs` → Save.**

## Layout

```
scripts/     01..06  diagnostic pass (data_diagnostic.md)
             10..15  build pipeline, build_all.py, verify.py
             common.py, dims.py  shared helpers and dimension tables
docs/        the deployed site: index.html, css/, js/, vendor/d3.v7.min.js, data/
data/        raw archives and the merged CSV (gitignored), merge_data.py
```
