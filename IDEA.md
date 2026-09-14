# Section 3g — Ukrainian Open Data (data.gov.ua)

## 1. Selected dataset

**Name:** Відомості про транспортні засоби та їх власників
(Records of vehicles and their owners)

**Link:** https://data.gov.ua/dataset/06779371-308f-42d7-895e-5a39833375f0

**Author / provider:** Ministry of Internal Affairs of Ukraine (МВС), published on the
national open-data portal data.gov.ua and last updated 01.09.2026 — the series is
actively maintained.

**Data type:** structured tabular data — semicolon-delimited CSV files packed in ZIP
archives, UTF-8, one resource per year.

**Size:** 1.19 GB across 16 resources covering 2013 → 2026 (50–115 MB per year; the
2026 file is a partial year through August, 49 MB). Three resources for 2022 are
published under the same server-side name `reestrtz2022.zip` and were saved locally as
`_part1 / _part2 / _part3`.

**Description (3 sentences).** The dataset is the registration log of the MIA service
centres: one row per registration action, carrying the operation type and date, the
registering department, brand, model, year of manufacture, body type, fuel type, engine
capacity, weight, colour, owner type (natural or legal person), the owner's registration
region as a KOATUU code, the licence plate (2013–2025) and the VIN (2021–2026). Because
registration is compulsory, this is not a survey sample but a full-population record of
every vehicle put on or taken off the road in Ukraine over thirteen years — 23.6 million
rows, 16.4 million distinct plates and 5.8 million distinct VINs. It contains no owner
names or addresses: `PERSON` is a single-character owner-type flag and `REG_ADDR_KOATUU`
is a regional code, so the data is analytically rich while remaining non-personal.

**Screenshots:** [dataset page on data.gov.ua] · [resource list, 16 yearly archives] ·
[CSV preview after unzipping]

---

## 2. Proposed product — **CarTrail UA**

A two-screen web product built on top of the registration log:
**(1) the Used-Car Migration Map** and **(2) the Model Scorecard**.

### Who it is for

- **Primary:** a person buying a used car in Ukraine, who wants to know whether a model
  is gaining or losing popularity, how quickly its owners resell it, and how old the
  typical example on the market is.
- **Secondary:** dealers and importers deciding which region to source from and which to
  sell into; insurers pricing a regional book of business; journalists and researchers
  covering the car market, imports and regional economics.

### What problem does it solve

The registry is published as sixteen yearly ZIP archives of raw CSV. Answering even a
simple question — "is this model being resold faster than its rivals?", "where do cars
first registered in Kyiv end up?" — requires downloading a gigabyte, reconciling four
different schema versions, and knowing that two of the three 2022 archives are in fact
duplicates of 2021. In practice a statutory publication describing the entire national
fleet goes unused, while buyers rely on classified-ad listings that show asking prices
and never show what actually happened to the car afterwards.

### What value does it provide

CarTrail UA is the only view of the Ukrainian car market built on registration events
rather than advertisements. Ads show intent; registrations show completed transactions
for the whole country, with no sampling and no self-reporting. That makes two things
visible that no existing service offers: the **geography of second-hand flow** — which
oblasts are net importers and which are net exporters of used cars, along which
corridors and after how long — and the **turnover behaviour of a specific model** — how
often it changes hands, how old it is when it does, and whether it is being bought by
individuals or by companies.

### Key features

**Screen 1 — Used-Car Migration Map**

- Flow map of Ukraine: arcs from the oblast of first registration to the oblast of the
  next registration, thickness proportional to the number of vehicles.
- Net-balance choropleth: net inflow minus outflow per oblast, diverging colour scale.
- Chord diagram of the oblast-to-oblast matrix, for reading both directions at once.
- Ranked table of the top corridors, with the median time from first registration to the
  move and the median age of the vehicles moving along it.
- Click an oblast to pivot the whole screen to that region: where its cars come from and
  where they go.

**Screen 2 — Model Scorecard**

- Search by brand and model → a single card with registration trend, median age at
  registration, resale rate, ownership duration, owner-type split, fuel mix and colours.
- Side-by-side comparison of two models on the same axes.
- Rank movement: where the model sits in the national top list and how that changed
  year over year.
- Regional concentration: a small choropleth showing where this model is actually
  registered.
- Event annotations on every time axis — 2014, COVID, 24.02.2022, the 2022 duty-free
  import window — so a spike is read in context instead of guessed at.

### Key metrics

*Migration:* net inflow/outflow per oblast; retention rate (share of vehicles whose next
registration is in the same oblast); top corridors by volume; median days from first
registration to an inter-regional move; median vehicle age at the moment of the move.

*Model:* registrations per year; median age at registration; resale rate (share of VINs
with two or more registration events in the observation window); median ownership
duration in days; share of legal-entity owners; EV and hybrid share; top-10 concentration
of the brand's models; year-over-year rank change.

### Visualizations

Arc flow map over a GeoJSON outline of Ukraine's oblasts; diverging choropleth of the net
balance; chord diagram; ranked corridor table with inline bars; annotated multi-year line
chart; sparkline grid for the scorecard; grouped bars for model comparison; donut for
fuel and colour mix; KPI row on both screens.

### Controls

Year range (2013–2026, with the map limited to 2021–2025 — see limitations); oblast
selector; brand and model search with autocomplete; fuel type; vehicle age band; owner
type (natural / legal person); flow direction (inflow, outflow, net); minimum corridor
volume threshold, to keep the map readable.

---

## 3. Data-quality notes that shaped the design

These come from a diagnostic pass run against the full 23.6-million-row series, and are
stated here because they constrain what the product may legitimately claim.

- **Vehicle identity is split.** VIN exists only in 2021–2026; the plate exists only in
  2013–2025. Cross-checking them in the 2021–2025 overlap shows that 26.0% of VINs carry
  more than one plate, so a plate-keyed history breaks the chain for about one vehicle in
  four, while falsely merging two vehicles in only 1.9% of cases. Any linkage across
  vehicles therefore uses VIN, and plate-based results are reported as an undercount of
  continuity rather than as fact.
- **The migration map is built on 2021–2025.** That is the only window where VIN and
  KOATUU coexist; 2026 drops both the region code and the plate.
- **KOATUU is the owner's registration address, not the vehicle's location.** The map is
  presented as a proxy for where cars end up, and labelled as such.
- **Two of the three 2022 archives are duplicates** of 2021 (95.9% and 95.8% exact-row
  overlap, with January–March 2021 dates); only `_part3` is genuine 2022 data and the
  other two are excluded everywhere.
- **2020 geography is unreliable:** 22.8% of `REG_ADDR_KOATUU` values that year are
  neither valid 10-digit KOATUU nor KATOTTG codes, so 2020 is flagged in the interface.
- **Coverage reflects the war.** Crimea's share of rows falls from 4.89% in 2013 to 0.43%
  in 2015 and 0.04% by 2018; Donetsk and Luhansk decline steadily and step down again
  from 2022. Occupied territory is absent from the registry, not from the country.

---

## 4. Prototype level

**Working web front-end (max 15 points).** A runnable single-page application deployed at
a public URL, with no backend: the 23.6-million-row series is aggregated once, offline
(pandas), into small static JSON files that ship with the front-end. The interface is
fully interactive and every figure in it is computed from the real registry, not mocked.