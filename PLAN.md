# CarTrail UA — implementation plan

> **This file is the spec.** It is written for the agent that will implement `IDEA.md`.
> Every assertion, threshold and gate below is a requirement, not a suggestion.
> Commit it to the repo alongside `IDEA.md` and `data_diagnostic.md`.

---

## Context

`IDEA.md` specifies **CarTrail UA** — a two-screen static web product built on the
Ukrainian MIA vehicle-registration open dataset (data.gov.ua, 2013–2026, 24.8M rows,
1.19 GB of ZIPs already downloaded to `data/`). Prototype level: *"working web front-end,
max 15 points — a runnable SPA at a public URL, no backend; the series is aggregated once,
offline, into small static JSON files that ship with the front-end."*

The raw data is already on disk and already diagnosed. `data_diagnostic.md` is a
full-series (not sampled) DuckDB study that establishes hard constraints on what the
product may legitimately claim — duplicate 2022 archives, a VIN/plate identity split,
a 2020 geography anomaly, schema drift across four eras. **Those findings are
requirements, not background reading.** The job is the missing middle and end:
an offline aggregation pipeline, and the SPA that consumes its output.

**Decisions already made by the user:**
- **UI language: Ukrainian.** Source vocabularies (`FUEL`, `COLOR`, `BODY`, `KIND`) pass
  through untouched — no translation dictionaries. Static UI strings are Ukrainian.
- **Deploy: GitHub Pages**, `main` branch → `/docs` folder, **no build step**. The plan
  ends at a verified local commit; the user runs the three push/enable commands (no `gh`
  CLI is installed).
- **Python deps install into the existing `.venv` in this folder**, via
  `.venv\Scripts\python.exe -m pip install <pkg>`. It already has duckdb 1.5.5,
  pandas 3.0.5, numpy 2.5.3 — most likely nothing needs adding. Prefer stdlib
  (`urllib.request`, `json`, `zipfile`) over new dependencies. **npm never enters this
  repo** — the front-end has zero build tooling.

---

## Non-negotiable ground rules

These come straight from `data_diagnostic.md` and must hold everywhere in the pipeline
and the UI. Violating one produces a confidently wrong product.

1. **`reestrTZ2022_part1.zip` / `_part2.zip` are excluded.** They are 95.9% / 95.8%
   exact-row duplicates of 2021 with Jan–Mar 2021 dates. `data/merge_data.py` already
   excludes them — keep it that way and assert it.
2. **Vehicle linkage is VIN-only.** Plate has a ~26% chain-break rate. No plate-keyed
   panel ships. `N_REG_NEW` may be staged but no user-facing metric derives from it.
3. **The migration map is 2021–2025 only** — the sole window where VIN and
   `REG_ADDR_KOATUU` coexist. 2026 has neither.
4. **Never say "first registration."** Say **«перша зафіксована реєстрація у вікні
   2021–2025»**. The window is left-censored and the operation vocabulary is not
   reliably classifiable (`data_diagnostic.md` §4: codes 40/70/71/50/80 are ambiguous
   and high-volume). Defining moves as *first-observed → next-observed VIN event*
   sidesteps operation classification entirely — do it that way.
5. **KOATUU is the owner's registered address, not the vehicle's location.** Label it as
   a proxy in the UI, on the map itself, not only in a footnote.
6. **2020 geography is flagged** (22.8% invalid `REG_ADDR_KOATUU`). The flag is driven by
   a per-year valid-rate figure written into `meta.json` by the build, not a hardcoded
   string.
7. **Occupied-territory coverage is a caveat, not a finding.** Crimea/Donetsk/Luhansk
   row shares collapse across the series; the UI must state that this is absence from
   the registry, not absence from the country.

---

## Repo layout

```
Ukraine Car Registration/
  .gitignore                  ← NEW, before git init
  PLAN.md                     (this file)
  README.md                   ← NEW (short: what, data source, how to rebuild, URL)
  IDEA.md  data_diagnostic.md        (existing, committed)
  data/                       (existing; ZIPs + merged CSV are GITIGNORED)
  scripts/
    common.py                 (existing — REUSE, do not rewrite)
    01..06_*.py               (existing diagnostic scripts, committed as-is)
    10_stage_parquet.py       ← NEW
    11_dimensions.py          ← NEW
    12_build_geo.py           ← NEW
    13_build_migration.py     ← NEW
    14_build_models.py        ← NEW
    15_build_meta.py          ← NEW
    build_all.py              ← NEW (runs 10→15 in order, fails loudly)
  build/                      ← NEW, GITIGNORED (parquet + intermediate reports)
  docs/                       ← NEW, THE DEPLOYED SITE (committed)
    .nojekyll
    index.html
    css/app.css
    js/{app,data,map,scorecard,fmt}.js
    vendor/d3.v7.min.js       (vendored, committed — no runtime CDN)
    data/
      meta.json
      oblasts.geojson
      flows/flows_2021.json … flows_2025.json
      models/index.json
      models/<brand-slug>.json
```

---

## Phase 0 — Repo hygiene (do before anything else)

`data/` holds ZIPs of 12–113 MB (several over GitHub's 100 MB hard reject) and an
**8.6 GB** `merged_registrations.csv`. A single `git add -A` before `.gitignore` exists
requires history surgery to ever push.

1. Write `.gitignore` **first**:
   ```
   .venv/
   _scratch/
   build/
   data/*.zip
   data/merged_registrations.csv
   data/*.parquet
   __pycache__/
   *.pyc
   ```
2. `git init -b main` — **explicitly**, not bare `git init`. Git 2.49 on Windows still
   defaults to `master` unless `init.defaultBranch` is set, and Phase 8 pushes `main`.
   (If the branch ends up `master` anyway, `git branch -M main`.)
3. `git add -A && git status --short` — **read the list**. Confirm no `.zip`, no
   `merged_registrations.csv`, no `.venv`.
4. `git count-objects -vH` after the first commit — `size-pack` must be tens of MB, not GB.
   If it isn't, stop and fix `.gitignore` before continuing.
5. Create empty `docs/.nojekyll` (without it, Pages runs Jekyll and silently drops
   underscore-prefixed paths).

Commit as you go — one commit per phase is fine.

---

## Phase 1 — Stage a typed Parquet (`scripts/10_stage_parquet.py`)

All aggregation runs off one typed Parquet file, not repeated 8.6 GB CSV scans.

**Source gate — decide, don't assume.** Run against `data/merged_registrations.csv`:
```sql
SELECT SOURCE_YEAR, COUNT(*) FROM read_csv('...merged_registrations.csv',
       delim=';', header=true, all_varchar=true) GROUP BY 1 ORDER BY 1;
```
Reconcile against the per-year table in `data_diagnostic.md` §1.
**Expected total: 24,787,233** (= 23,566,141 for 2013–2025 + 1,221,092 for 2026).
- **Match** → stage from the merged CSV.
- **Mismatch** → discard it and stage from the ZIPs via
  `scripts/common.py:register_all()` + `union_view()`, which already handle every
  documented schema quirk. Do not patch the merged CSV.

**The merged CSV carries raw `D_REG` strings in three formats** — `merge_data.py` never
parsed dates; only `common.py` does. Parse per `SOURCE_YEAR` using
`common.py:detect_date_format` (2013–2018 `%Y-%m-%d`; 2019–2022 `%d.%m.%Y`;
2023–2026 `%d.%m.%y`). **Assert a per-year non-null parse rate ≥ 99%** and print the
table — `TRY_STRPTIME` turns any surprise into a silent NULL.

**Note on reading:** every source file is UTF-8 (`data_diagnostic.md` §1, verified on all
16). If a preview looks like `Р’РўРћР...`, that is a console codepage artifact, not
corrupted data — always read with `encoding="utf-8"` and never "fix" it.

**Output `build/registrations.parquet`, columns:**

| column | derivation |
|---|---|
| `source_year` | int |
| `d_reg` | DATE, parsed per-year as above |
| `reg_year` | `year(d_reg)` |
| `person` | `P` / `J`, uppercased & trimmed |
| `koatuu` | `REG_ADDR_KOATUU` if `^\d{10}$` after trim, else NULL |
| `oblast` | `substr(koatuu,1,2)`, else NULL |
| `oper_code` | trimmed (kept for ad-hoc checks; no UI metric depends on it) |
| `brand`, `model` | normalized — see Phase 2 |
| `brand_raw`, `model_raw` | kept for audit |
| `vin` | trimmed upper, NULL if empty/`NULL` |
| `plate` | `common.py`'s `NORM_PLATE` expression (staged for audit only) |
| `make_year` | int, NULL outside 1900–2027 |
| `age_at_reg` | `reg_year - make_year`, NULL if <0 or >60 |
| `color`, `kind`, `body`, `fuel` | trimmed upper Cyrillic, as published |
| `fuel_grp` | grouped — see Phase 2 |
| `capacity` | int (cm³), NULL if implausible |

Write with `COPY (...) TO 'build/registrations.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)`.
Print final row count and reconcile again.

---

## Phase 2 — Dimensions & normalization (`scripts/11_dimensions.py`)

### 2a. Brand/model normalization — **the biggest unflagged risk**

The raw data has `BRAND = "SSANG YONG  REXTON"`, `MODEL = "REXTON"` (doubled space; the
brand field frequently contains brand **+** model). Screen 2 is worthless if
`SSANG YONG  REXTON` and `SSANGYONG` are separate brands.

Required pass, in this order:
1. Uppercase, trim, collapse runs of whitespace to one space.
2. If `BRAND` ends with `" " + MODEL`, strip that suffix → brand is the leading token(s).
3. Apply an explicit alias table for the survivors (`SSANG YONG`→`SSANGYONG`,
   `MERCEDES BENZ`→`MERCEDES-BENZ`, `VW`→`VOLKSWAGEN`, `ВАЗ`/`LADA`, `ЗАЗ`, `ГАЗ`,
   `УАЗ`, etc.) — **build this table from the measured data, not from memory.**
4. **Report before/after distinct-brand counts**, and write the top 200 brands by volume
   to `build/reports/brands.md`. Eyeball that list. Iterate the alias table until the
   top 50 are clean.

Persist the mapping to `build/brand_map.json` so the result is reproducible and auditable.
Do this **before** sharding model files — the shard filenames depend on it.

### 2b. Fuel grouping

Do not guess the vocabulary. First dump distinct `FUEL` values with counts to
`build/reports/vocab.md`, then write the map. Target groups (Ukrainian, 5 + other):
`Бензин`, `Дизель`, `Газ/бігаз`, `Гібрид`, `Електро`, `Інше`.
**Assert the mapped groups cover ≥ 99.5% of non-null rows.** Do the same dump for
`COLOR`, `BODY`, `KIND` (used as-is in the UI, but you need the distinct counts to size
the "top N + Інше" cutoffs).

### 2c. Oblast crosswalk (27 regions)

Hardcode the KOATUU 2-digit prefix → oblast table (this is a stable legacy standard):

`01` АР Крим · `05` Вінницька · `07` Волинська · `12` Дніпропетровська ·
`14` Донецька · `18` Житомирська · `21` Закарпатська · `23` Запорізька ·
`26` Івано-Франківська · `32` Київська · `35` Кіровоградська · `44` Луганська ·
`46` Львівська · `48` Миколаївська · `51` Одеська · `53` Полтавська ·
`56` Рівненська · `59` Сумська · `61` Тернопільська · `63` Харківська ·
`65` Херсонська · `68` Хмельницька · `71` Черкаська · `73` Чернівецька ·
`74` Чернігівська · `80` м. Київ · `85` м. Севастополь

**Assert:** exactly 27 entries, and the share of non-null `koatuu` rows whose prefix is
unmapped is **< 1% per year**. Dump the top unmapped prefixes to the report if not.

---

## Phase 3 — GeoJSON (`scripts/12_build_geo.py`)

The choropleth needs real polygons. **Strategy, not a hardcoded URL** — fetch at *build*
time, validate, simplify, and **commit the result** to `docs/data/oblasts.geojson`.
There must be **no runtime fetch from any external host**; a CDN dependency is a site
that breaks silently a year from now.

Script contract:
1. Try candidate admin-1 Ukraine GeoJSON sources in order (public community mirrors of
   Natural Earth / geoBoundaries admin-1 are the usual suppliers). Treat every URL as
   unverified — the script must validate, not trust.
2. **Assert exactly 27 features** and that some property carries an oblast name.
3. Build a feature-name → KOATUU-prefix crosswalk **in code, with an assertion that all
   27 resolve.** Normalize aggressively (strip «область»/«Oblast», fold apostrophes,
   accept both Ukrainian and English spellings, `Kyiv City` vs `Kyiv`).
4. Simplify geometry (round coordinates to 3–4 decimals; drop tiny rings) to land the
   file **under ~800 KB**. Write `koatuu` and `name_uk` onto each feature's properties.
5. **Fallback if nothing validates:** ship a centroid-based bubble/arc map using a
   hardcoded table of 27 oblast-centre lat/lon, and state the fallback in `meta.json` and
   in the UI. Do not ship a half-matched polygon layer.

---

## Phase 4 — Screen 1 data: migration cube (`scripts/13_build_migration.py`)

### Move definition (VIN-keyed, `source_year` 2021–2025)

Per VIN, over rows with a **valid `oblast`**, ordered by `d_reg`:
- `e1` = first such event; `e2` = the next such event with `d_reg > e1.d_reg`.
- `from_ob = e1.oblast`, `to_ob = e2.oblast`, `move_year = year(e2.d_reg)`
- `days = e2.d_reg - e1.d_reg`
- `age_band` from `e2.reg_year - make_year`
- `person = e2.person` (owner type at destination), `fuel_grp` from `e1`

**Correctness rules — state these in code comments and enforce them:**
- **Keep the diagonal** (`from_ob == to_ob`) in the cube — retention rate needs it.
  Exclude it from the arc layer only, at render time.
- A VIN whose only later event lacks a valid oblast (**including any 2026 event, which
  has no KOATUU at all**) is **dropped from the denominator entirely** — not counted as
  "stayed". Counting it as retention silently inflates the headline metric. Write the
  dropped count and its share into `meta.json`.
- Retention rate = share of *observable* second events landing in the same oblast.

**Age bands (5, reused as both filter dimension and age histogram):**
`0–3` · `4–7` · `8–12` · `13–20` · `21+`
Because `age_band` is a cube dimension, median-age-at-move is derived by band
interpolation from the same cells — no separate age histogram is stored.

**Days histogram (8 bins):** `0–30 · 31–90 · 91–180 · 181–365 · 366–730 · 731–1095 ·
1096–1460 · 1461+` → the client band-interpolates a median for any filter combination.
Label such figures «медіана (оцінка за інтервалами)».

### Size gate — one query decides the file layout

```sql
SELECT COUNT(*) FROM (
  SELECT from_ob, to_ob, move_year, person, fuel_grp, age_band FROM moves GROUP BY ALL
);
```
- **≤ ~60k non-empty cells** → ship the full cube **with** the 8-bin days histogram;
  medians stay responsive to every filter.
- **> ~60k** → drop `days_hist` from the cube (counts only), and emit a separate
  **exact**-median table keyed at `(from_ob, to_ob, move_year)` — 27×27×5 = 3,645 rows,
  trivial. Tiles reading from it are labelled «усі типи власників, усе пальне».

Apply a build-time floor of `n >= 3` per cell and record the suppressed row total in
`meta.json`.

### Output

`docs/data/flows/flows_<year>.json` for 2021…2025, **column-oriented** (parallel typed
arrays, not an array of objects — roughly 3× smaller):
```json
{"from":[…],"to":[…],"own":[…],"fuel":[…],"ageb":[…],"n":[…],"dh":[[…8 ints…],…]}
```
The client fetches only the selected years and caches them. Codes (oblast, fuel group,
age band, owner type) are small integer indexes resolved against dictionaries in
`meta.json`.

**Write the flows loader so `fuel` and `dh` are optional arrays** — if either is absent,
the loader skips that dimension and the UI hides the fuel control / switches medians to
the exact-median table. Phase 7's overflow ladder drops them, and that must stay a
build-config flip, not a front-end edit.

---

## Phase 5 — Screen 2 data: model scorecards (`scripts/14_build_models.py`)

**Two observation windows are mixed on this screen. Each tile carries its own window
label in the UI — not one footnote at the bottom of the card.**

| metric | window | key |
|---|---|---|
| registrations per year | 2013–2026 | row counts (no linkage) |
| median age at registration | 2013–2026 | row counts |
| owner-type split (P/J) | 2013–2026 | row counts |
| fuel mix, colour mix, body mix | 2013–2026 | row counts |
| regional concentration | 2013–2025 | rows with valid `koatuu` |
| national rank + YoY rank change | 2013–2026 | row counts |
| **resale rate** | **2021–2026** | **VIN** (≥2 events) |
| **median ownership duration** | **2021–2026** | **VIN** (median gap between consecutive events) |

**Inclusion threshold:** models with **≥ 500** total registrations 2013–2026. Tune the
threshold if the size budget (Phase 7) is missed; record the chosen threshold, the number
of models included, and the number and row-share excluded in `meta.json`.

**Output:**
- `docs/data/models/index.json` — `{brands:[…], models:[{b:<brandIdx>, m:"MODEL",
  n:<total>, s:"<brand-slug>"}]}`. Powers autocomplete for both the primary and the
  comparison selector. Target < 600 KB.
- `docs/data/models/<brand-slug>.json` — every model of that brand with its full metric
  block. **Shard by brand, not per model** — thousands of tiny files bloat git and
  round-trip badly. Expect a few hundred files, each well under 500 KB.

---

## Phase 6 — Front-end (`docs/`)

**Stack: plain HTML + ES modules + vendored D3 v7. No bundler, no npm, no framework.**
Relative paths (`fetch('data/meta.json')`) survive the `https://<user>.github.io/<repo>/`
base path with zero configuration — this is the single biggest reason not to reach for
Vite here. Download `d3.v7.min.js` once into `docs/vendor/` and commit it.

**Ukrainian UI throughout.** Registry vocabularies render as published.

### Shell (`index.html`, `js/app.js`)
Header, two tabs — **«Карта міграції авто»** / **«Картка моделі»** — a persistent
**«Про дані»** panel (collapsible) carrying the §3 caveats, and a KPI row per screen.
URL hash holds the full filter state so a view is shareable and survives reload.

### Screen 1 — Used-Car Migration Map (`js/map.js`)
- **Arc flow map** over `oblasts.geojson`; arc width ∝ vehicle count; diagonal excluded.
- **Net-balance choropleth**, diverging scale, inflow − outflow per oblast.
- **Chord diagram** of the 27×27 matrix.
- **Ranked corridor table**: volume, median days to move, median age at move, inline bars.
- **Click an oblast** to pivot the whole screen to it (its inbound and outbound flows).
- **Controls:** year range 2021–2025, direction (inflow/outflow/net), owner type,
  fuel group, age band, minimum-corridor-volume slider.
- **On-map label:** «Регіон реєстрації власника — проксі, не місцезнаходження авто».
- 2020 is not selectable here (outside the window) but the flag rendering is driven from
  `meta.json` valid-rate values, which the Screen-2 map reuses.

### Screen 2 — Model Scorecard (`js/scorecard.js`)
- Brand+model autocomplete → one card: annotated registration trend, median age at
  registration, resale rate, ownership duration, owner split, fuel and colour donuts.
- **Side-by-side comparison** of two models on shared axes. The two models may live in
  **different brand shards** — the loader must fetch and cache per-shard, not assume one.
- **Rank movement** — position in the national top list, YoY delta.
- **Regional concentration** — small choropleth reusing `oblasts.geojson`.
- **Event annotations** on every time axis, from a `meta.json` constant: 2014 (анексія
  Криму та початок війни), весна 2020 (COVID), 24.02.2022 (повномасштабне вторгнення),
  і вікно безмитного імпорту авто 2022 (приблизно березень–червень 2022 — **verify the
  dates before labelling and keep the wording hedged if unverified**).

### Styling (`css/app.css`)
One hand-written stylesheet. Dark-neutral data-app palette, a diverging scale for net
balance (colour-blind-safe: blue↔orange, not red↔green), one sequential scale for
magnitude. Responsive down to ~400 px — charts reflow or scroll inside their own
container; the page body never scrolls horizontally.

---

## Phase 7 — Verification (all of these must pass)

1. **Row reconciliation.** `SELECT source_year, COUNT(*) FROM build/registrations.parquet`
   matches `data_diagnostic.md` §1 per year; total = **24,787,233**. (§3's figure of
   23,566,141 is the same sum through 2025 — it was computed over rows having a plate
   column, which is exactly 2013–2025 minus the duplicate 2022 parts. The two agree;
   it is not a discrepancy.)
2. **Parse-rate assertions.** Per-year `d_reg` non-null ≥ 99%; unmapped KOATUU prefix
   share < 1%/year; fuel-group coverage ≥ 99.5%. All printed by `build_all.py`.
3. **Duplicate exclusion.** Assert zero rows trace to `reestrTZ2022_part1/2`.
4. **Size budget.** `docs/data` total **≤ 25 MB**, no single file **> 5 MB**. Measure and
   print it. If over: first raise the model threshold, then drop `fuel` from the
   migration cube, then drop `days_hist` — in that order.
5. **Independent recompute.** Pick one number visible in the UI (e.g. the top corridor's
   count for 2023, natural persons, all fuels) and recompute it with a standalone DuckDB
   query written from scratch against the Parquet. It must match exactly.
6. **Serve and click through.** From `docs/`: `..\.venv\Scripts\python.exe -m http.server 8000`
   → open `http://localhost:8000`. Exercise both screens, every control, the oblast pivot,
   the model comparison, and a hash-URL reload. Browser console must be error-free.
7. **No absolute or external paths.** Grep `docs/` for `src="/`, `href="/`, `fetch("/`,
   and any `http://` / `https://` in a runtime fetch or asset tag. There must be none —
   these are exactly what breaks under the `/<repo>/` Pages base path.
8. **Git size.** `git count-objects -vH` → `size-pack` in the tens of MB.

---

## Phase 8 — Deploy handoff

Finish with a local commit on `main`, then hand the user exactly these steps (no `gh` CLI
is installed, so repo creation is theirs):

1. Create a **public** repo on github.com (Pages needs public on free plans).
2. ```
   git remote add origin https://github.com/<user>/<repo>.git
   git push -u origin main
   ```
3. **Settings → Pages → Source: Deploy from a branch → `main` → `/docs` → Save.**
4. Site appears at `https://<user>.github.io/<repo>/` within a minute or two.

Also write `README.md`: what the product is, the data source and licence, the exact
rebuild command (`.venv\Scripts\python.exe scripts\build_all.py`), the data caveats in
one paragraph, and the live URL placeholder.

---

## Execution order

`Phase 0` → `1` → `2` → `3` → `4` → `5` → `6` → `7` → `8`.

Phases 3–5 are independent of each other once Phase 2 lands and can be built in any
order, but **Phase 2's brand normalization must be settled before Phase 5 shards files**.
`scripts/build_all.py` runs 10→15 in order and exits non-zero on any failed assertion —
no phase silently produces half-valid JSON.
