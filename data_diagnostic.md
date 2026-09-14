# Vehicle-linkage diagnostic: can rows be linked across years?

Diagnostic pass only (no cleaning/pipeline). Source: 16 yearly ZIP/CSV archives from
`data.gov.ua`, MIA vehicle-registration log, 2013–2026 (2022 published as three separate
resources, saved as `_part1/_part2/_part3`). All numbers below come from DuckDB queries
against the **full extracted series** (23.6M rows across the 13 genuinely-yearly files),
not a row sample — see "Method note" at the end for why. Scripts are under `./scripts/`.

**Privacy**: this dataset contains **no owner names or addresses**. `PERSON` is a
single-character owner-type flag (`P`=physical, `J`=juridical person), and the only
location field is a regional code (`REG_ADDR_KOATUU`), not a street address. Plates and
VINs below are masked (`AA••••XX` / `WBA•••••••••XXXX` style) wherever an example is shown.

---

## 1. Schema inventory

| | 2013–2018 | 2019–2020 | 2021–2025 | 2026 |
|---|---|---|---|---|
| header casing/quoting | lowercase, unquoted | UPPERCASE, quoted | UPPERCASE, quoted | UPPERCASE, quoted |
| `VIN` | absent | absent | **present** | present |
| `REG_ADDR_KOATUU`, `DEP_CODE`, `N_REG_NEW` (plate) | present | present | present | **absent** |
| `POWER_KWT` | absent | absent | absent | present |
| `OPER_CODE`/`OPER_NAME` | two columns | two columns | two columns | **fused into one** column (literally named `CD.OPER_CODE\|\|'-'\|\|CD.OPERAS`, split on `' - '`) |
| `D_REG` date format | `YYYY-MM-DD` | `DD.MM.YYYY` | `DD.MM.YYYY` (2021–2022), `DD.MM.YY` (2023–2025) | `DD.MM.YY` |
| encoding | UTF-8 (all 16 files) | UTF-8 | UTF-8 | UTF-8 |
| delimiter | `;` throughout | | | |

All 16 files decode cleanly as **UTF-8**, confirmed by attempting utf-8 then cp1251 on
every file (`01_schema_inventory.py`) — the cp1251 hypothesis in the task brief does not
hold for this dataset. One file has a **homoglyph in its own filename**:
`tz_opendata_z01012019_po01012020.сsv` uses a Cyrillic с in `.csv`.

Row counts (all years, exact, from `COUNT(*)`):

| year | rows | year | rows |
|---|---|---|---|
| 2013 | 1,935,496 | 2021 | 2,201,307 |
| 2014 | 1,439,551 | 2022_part1 | 270,775 *(duplicate, see §6)* |
| 2015 | 1,296,256 | 2022_part2 | 443,599 *(duplicate, see §6)* |
| 2016 | 1,432,560 | 2022_part3 | 1,745,908 *(genuine 2022)* |
| 2017 | 1,417,655 | 2023 | 2,124,732 |
| 2018 | 1,547,418 | 2024 | 2,344,544 |
| 2019 | 2,079,481 | 2025 | 2,229,904 |
| 2020 | 1,771,329 | 2026 | 1,221,092 *(partial year, through Aug)* |

The full year×column presence matrix is in `reports/01_schema_inventory.md`
(job scratch) and reproduced by re-running `scripts/01_schema_inventory.py`.

**Rename note**: no column was silently renamed to something unrecognizable — the drift
is casing/quoting (cosmetic) plus genuine column additions/removals (VIN in, then
KOATUU/DEP_CODE/plate out in 2026) and the 2026 OPER_CODE/OPER_NAME fusion.

---

## 2. Candidate keys

| column | years present | null rate | cardinality (non-null) | verdict |
|---|---|---|---|---|
| `VIN` | 2021–2026 only | 0.0% every year it exists | ~1.4–2.1M distinct/year | Real vehicle key, but **absent for 13 of 16 files** |
| `N_REG_NEW` (plate) | 2013–2025 only | 0.7–1.5% (1.3–1.4% in 2024/2025) | ~1.1–2.1M distinct/year | Real vehicle key, but **absent in 2026** |
| `PERSON` | all years | 0.0% | **2** (`P`/`J`) | Not an identifier — owner-type flag only |
| `DEP_CODE` | 2013–2025 (absent 2026) | 0.0% | 150–414 distinct/year, format changes 3x (see §6) | Identifies the *service department*, not the vehicle |

**VIN and plate never co-exist with full-series coverage.** 2021–2025 is the only window
where both are present simultaneously — which is exactly what makes it possible to check
the plate against a ground truth in §3, instead of only against attribute-consistency
heuristics.

---

## 3. Is the plate a usable vehicle key? (core question)

Computed on the union of all years with a plate column, **excluding** `2022_part1`/`part2`
(confirmed duplicates of 2021, §6): 2013–2021, 2022_part3, 2023–2025 = 23,566,141 rows,
16,434,925 distinct normalized plates.

**Rows per plate:**

| rows-per-plate | % of plates | % of rows |
|---|---|---|
| 1 | 73.8% | 51.5% |
| 2 | 17.4% | 24.3% |
| 3–5 | 8.0% | 19.2% |
| 6–10 | 0.7% | 3.4% |
| 11+ | 0.1% | 0.6% |

26.2% of plates (4,308,482) appear more than once.

**Brand+year-of-manufacture consistency within multi-row plates**: constant in **63.6%**,
changes in **36.4%** — a third of repeat-plate groups look like a different vehicle.

**Is that formatting noise or real reuse?** Normalizing case/whitespace and folding the 11
Cyrillic/Latin homoglyph pairs (the 9 the task named, plus Н/H and the Ukrainian І/I, both
empirically present in plate text) collapsed distinct keys by **essentially 0.0%**
(16,436,400 raw-trimmed keys → 16,434,925 normalized keys — a 1,475-key, 0.009% reduction),
and moved the brand+year consistency rate by **–0.0 percentage points**. **This is a
negative result worth stating plainly: homoglyph/case noise is not the source of the
inconsistency in this data. The 36.4% of multi-row plates with a brand/year change is
overwhelmingly real reuse, not formatting artifacts.**

**Time gap vs. brand/year change**: median gap between consecutive events is **256 days**
when brand+year stays constant, vs. **420 days** when it changes — plates that get
reassigned to a different vehicle sit idle roughly 60% longer first, consistent with a
plate returning to a pool before reissue.

**Registering away from the owner's home region (proxy for the 2016 "any service centre"
rule)**: comparing `DEP_CODE` vs. `REG_ADDR_KOATUU` oblast prefixes gives 17–20% in
2016–2018 rising to ~93–94% from 2019 on — **but this jump is very likely an artifact, not
a real behavior change**: `DEP_CODE` itself changes numbering scheme at exactly 2016 and
again at 2019 (§6), so the 2019+ comparison is very likely comparing two incompatible
numbering schemes, not measuring geography. The only internally-consistent window (2016–2018,
single 4-digit scheme) shows a real, modest upward trend (17.0% → 19.7%), weakly consistent
with loosened geographic restriction, but I would not trust the 2019+ numbers as a
geography signal at all. Pre-2016 (2013–2015) uses a third, 7-digit scheme that is not
directly comparable either — there is no clean before/after test of the 2016 rule in this
data, only this weak, partial signal.

**Ground-truth cross-validation, 2021–2025 (the only years with both VIN and plate)** —
this is the strongest evidence in this report:

- **25.97%** of VINs (1,517,411 / 5,843,843) have **more than one distinct plate** —
  keying by plate alone would **break the chain** for roughly 1 in 4 real vehicles.
- **1.91%** of plates (147,642 / 7,726,508) have more than one distinct VIN — keying by
  plate would **falsely merge** two different vehicles only rarely.
- Of the 1,517,411 multi-plate VINs, only **15.6%** have a row whose operation name
  mentions a plate/number-sign change — so **~84% of plate churn has no dedicated
  "plate change" operation code attached to it**; it most likely rides along with
  ownership-transfer events instead (§4) rather than being its own flagged action.

**Reading**: plate-based linkage rarely fabricates false links (good), but silently
truncates a real vehicle's history into multiple shorter fragments about a quarter of the
time (bad) — an undercount of continuity, not a source of contamination.

---

## 4. Operation-type vocabulary

Classified every `(OPER_CODE, OPER_NAME)` pair by year (keyed on the numeric code, since
names can carry minor wording drift and 2026 fuses the two into one field) into four
buckets. Full per-year tables in `reports/04_operation_vocab.md`.

| bucket | example codes |
|---|---|
| first registration | 10, 20, 30 (`ПЕРВИННА РЕЄСТРАЦІЯ...`) |
| re-registration / ownership transfer | 309, 310, 319, 321, 322, 330 (`...НА НОВОГО ВЛАСНИКА...`) |
| de-registration / export / scrapping | 530, 534, 540, 560 (`ЗНЯТТЯ З ОБЛІКУ...`) |
| administrative change | 400–403, 410, 430, 431, 440, 250/252/270 (temporary talons) |

**Flagged as ambiguous, not confidently classifiable** (high volume, so this matters): code
**40** (`ВТОРИННА РЕЄСТРАЦІЯ ТЗ, ПРИДБАНОГО В ТОРГОВЕЛЬНІЙ ОРГАНІЗАЦІЇ` — literally
"secondary registration of a vehicle purchased at a trading organization") was the single
highest-volume code in 2013 (583,250 rows) and stays large through the series; codes
**70/71** (`РЕЄСТРАЦІЯ ТЗ ПРИВЕЗЕНОГО З-ЗА КОРДОНУ` — vehicle imported from abroad) and
**50/80** (purchase-agreement / auction registration) are similarly ambiguous. All of these
read semantically as "this owner's first registration of a just-acquired vehicle" but the
literal wording ("secondary", "registration by agreement") doesn't match a strict
first-registration keyword rule, so they were left unclassified rather than force-fit. This
matters directly for §5: any "first registration" share computed from the strict keyword
rule is a **lower bound**, not an exact figure, because these high-volume codes are excluded.

---

## 5. Lifecycle feasibility (plate key, full 2013–2025 series)

- Plates with an observable first-registration event **and** ≥1 later event: **4.0%**
  (663,746 / 16,434,925) — read this as a floor, not a ceiling, given the §4 classification
  gap (codes 40/70/71/50/80 are not counted as "first registration" here).
- Plates with an observable terminal (de-registration) event: **9.6%** (1,577,910 / 16,434,925).
- Median events per vehicle: **1** (73.8% of plates are singletons — consistent with §3).
- Median gap between consecutive events: **332 days** (IQR 53–883 days).
- **Left-censoring caveat**: the series starts in 2013, so a plate whose first observed row
  isn't a first-registration event may simply predate the data — this mechanically
  depresses the "first + later" share and is not evidence the key failed.

---

## 6. Known traps

**2022 split archives — confirmed, not assumed**: `reestrTZ2022_part1.zip` and `_part2.zip`
are **95.9%** and **95.8%** exact-row duplicates of `reestrTZ2021.zip` respectively (their
`D_REG` dates fall in Jan–Mar 2021, not 2022). Only `_part3.zip` is genuine 2022 data.
`part1`/`part2` are excluded from every other section of this report.

**Exact-duplicate rows within a year**: low everywhere (0.03–0.31%) except **2025, at
1.43%** (31,785 duplicate rows) — worth a note if 2025 is used for point-in-time counts,
not a structural problem.

**KOATUU vs. KATOTTG**: the dataset uses **legacy 10-digit numeric KOATUU throughout**;
no year shows `UA`-prefixed KATOTTG codes at all, and 2026 drops the field entirely rather
than migrating it. One anomaly: **2020 has 22.8% (404,586 rows) of non-standard
`REG_ADDR_KOATUU` values** (neither 10-digit numeric nor `UA`-prefixed) — worth a follow-up
look before using 2020 geography, not explained by this pass.

**`DEP_CODE` changes numbering scheme at least twice**: 7-digit codes dominate 2013–2015,
4-digit codes dominate 2016–2018, 5-digit codes dominate 2019–2025 (and the field
disappears in 2026). This is what undermines the §3 geography comparison across 2019.

**Territorial coverage** (share of rows by owner's KOATUU oblast — reminder: this is
*registered address*, not current location or service location):

| | 2013 | 2015 | 2018 | 2022 | 2025 |
|---|---|---|---|---|---|
| Crimea (01/85) | 4.89% | 0.43% | 0.04% | 0.05% | 0.04% |
| Donetsk (14) | 7.56% | 5.04% | 4.66% | 2.69% | 2.13% |
| Luhansk (44) | 3.38% | 2.02% | 1.73% | 0.93% | 0.56% |

Crimea's share collapses sharply between 2013 and 2015 (consistent with 2014 annexation);
Donetsk/Luhansk decline more gradually, with a further step down visible from 2022 onward.

**Year-of-manufacture outliers**: negligible. Zero rows below 1900 across all 16 years;
only 4 rows (all in 2013) above 2027; no other anomalies found.

---

## Method note: why full-series instead of the suggested 200k-row sample

The task suggested sampling 200k rows each from 2014/2018/2022/2025 for initial iteration.
That row-level sample was used for schema/encoding checks (§1), but **§3 and §5 run on the
complete series instead**: a vehicle with one event in 2014 and one in 2018 would only
land in both 200k/1.4M-row samples about 1.8% of the time, which would make plates look
almost entirely singleton as a pure sampling artifact — exactly the statistic §3 exists to
measure. DuckDB's out-of-core engine made the full 23.6M-row scan tractable directly (each
script completed in a few minutes), so the "confirm on the full series" step is already
built into every number above rather than being a separate pass.

---

## Verdict: is panel analysis viable?

**Yes, but as two separate, non-overlapping panels, not one continuous key.**

1. **2021–2025**: use `VIN`. It is 0% null, fully present, and (being the manufacturer's
   own identifier) is the reliable key wherever it exists.
2. **2013–2020**: no VIN exists at all. The plate (`N_REG_NEW`) is the only available key,
   and the ground-truth check against VIN in the overlap window (2021–2025) puts a number
   on its reliability: **~2% false-merge risk (safe to use), but ~26% chain-break risk**
   (a real vehicle's history will often fragment into 2+ apparently-unrelated plate-groups).
   Treat plate-keyed panel results as an **undercount of true continuity**, not a source of
   spurious linkage — trends built on it (e.g. "% of vehicles re-registered within N years")
   will be biased toward *shorter* observed chains than reality, not toward false chains.
3. **2026**: no plate column exists at all, and it is a partial year besides. It can only
   be linked backward via VIN (to 2021–2025), never via plate. Any 2013–2020 vehicle whose
   next event happens to fall in 2026 is fundamentally unlinkable with this data.

**Recommendation**: run the panel as VIN-keyed for 2021–2026, and plate-keyed for
2013–2025, and report them as two separate results rather than splicing them into one
"vehicle ID" — a spliced key would silently inherit the plate panel's ~26% chain-break rate
without a way to flag which links are weak. If the analysis specifically needs pre-2021
individual-vehicle continuity with low fragmentation risk, cohort/group-level analysis
(by brand+model+registration-year cohort, e.g.) is the safer default for that window;
individual-vehicle panel claims pre-2021 should carry the 26% caveat explicitly.
