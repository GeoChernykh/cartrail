# Dashboard build prompt

> Paste everything below into your agent. Fill in the three bracketed slots at the top first — the rest is a fixed style contract and should be handed over unchanged.

---

Build a single-page analytics dashboard. Follow the style contract below exactly; it describes a specific existing design, so do not substitute your own aesthetic direction, palette, or layout ideas anywhere it is explicit.

**Subject:** [what the dashboard measures, e.g. "web traffic for a B2B marketing site"]
**Stack:** [e.g. React + Recharts + Tailwind / plain HTML + CSS + Chart.js / Power BI theme JSON]
**Data source:** [file path, API, or "use realistic mock data covering 24 monthly periods"]

## Overall frame

The page sits on a flat light-grey field. All content lives inside one large rounded container — a "slab" — that floats on that field with generous margin on all sides. The slab is a slightly different grey from the page, distinguished by tone rather than by any border or shadow. Corner radius on the slab is large, roughly 40px.

A narrow icon rail runs down the left edge, overlapping the slab's left boundary so the buttons appear to sit half on, half off it. Each rail button is a white rounded square, about 72px, radius 20px, with a thin line icon centered inside. The active button is filled with the muted blue-grey and its icon turns white. The rail has no background of its own — the buttons float independently with about 16px between them.

## Color

Six values carry the whole design. Do not introduce additional hues.

| Role | Hex |
|---|---|
| Page background | `#EDEDEE` |
| Slab background | `#E4E5E7` |
| Card / rail button | `#FFFFFF` |
| Primary data blue | `#3B6E93` |
| Secondary blue-grey | `#A9C0D2` |
| Tertiary pale cyan | `#93DCF2` |
| Inert / "other" grey | `#E0E0E0` |
| Highlight blue (rare) | `#2F88F7` |

Text is `#2B2B2B` for anything primary and `#6B6B6B` for axis ticks and small labels. The highlight blue appears at most once per screen, on a single series worth calling out. Categorical series descend in weight: primary blue, then blue-grey, then pale cyan, then inert grey — so a bar chart reads as a ranking by color as well as by length.

## Type

One sans-serif family throughout, a neutral grotesque with a heavy bold available (Segoe UI, Inter, or Source Sans 3). No second family, no monospace.

- Page title: ~64px, weight 700, tight tracking (-0.02em), sentence case, sitting at the top-left of the slab with real breathing room above and below.
- KPI label: ~20px, weight 400, `#2B2B2B`, centered over its number.
- KPI value: ~56px, weight 600, centered, tight tracking. Percentages keep the `%` at full size.
- Card title: ~20px, weight 700, centered at the top of the card.
- Axis ticks and legend: ~14px, weight 400, `#6B6B6B`.

Labels are sentence case. No all-caps, no letter-spaced eyebrows, no unit strings tucked under headings.

## Layout

Three rows inside the slab, 20px gutters, cards stretching edge to edge within it.

```
┌──────────────────────────────────────────────────────────────┐
│  Web Traffic                       (Month)(Year)[Total]  ≡   │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                 │
│  │  KPI   │ │  KPI   │ │  KPI   │ │  KPI   │   row 1: 4 × 1fr│
│  └────────┘ └────────┘ └────────┘ └────────┘                 │
│  ┌──────┐ ┌──────┐ ┌──────────────────────┐                  │
│  │ bars │ │ bars │ │      time series     │   row 2: 1 1 2   │
│  └──────┘ └──────┘ └──────────────────────┘                  │
│  ┌────────────────────┐ ┌────────────────────┐               │
│  │      area/line     │ │        bars        │  row 3: 1 1   │
│  └────────────────────┘ └────────────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

Row 1 is four equal KPI cards, each squat and wide. Row 2 is three cards at 1 : 1 : 2 — two small horizontal-bar cards and one wide time series. Row 3 is two equal cards. Row heights increase down the page: short, medium, medium.

Top-right of the slab, level with the title, is a segmented time-range control: three pill buttons in a row, each white with fully rounded ends and about 24px of horizontal padding. The selected pill is filled `#A9BCCB` with darker text. To its right, a hamburger icon drawn as three thick rounded bars in the same blue-grey.

## Cards

Every card is white, radius 8px, with a shadow so faint it reads as an edge rather than a lift: `0 1px 3px rgba(0,0,0,0.08)`. No borders. Internal padding about 20px. All cards use the same radius and the same shadow — there is no elevation hierarchy here.

## Charts

The charts are deliberately stripped. Assume the reader wants shape, not precision.

- No chart borders, no plot-area fill, no axis lines, no vertical gridlines.
- At most one horizontal gridline, dotted, at a single round value (20K, 50K). Label it on the left in grey. Add a `0K` baseline label only.
- X-axis shows four or five sparse labels across the full range (`Jul 2017`, `Jan 2018`, …), never one per bar.
- No data labels on bars or points. No tooltips styled beyond the library default.
- No legends except where a chart has multiple series; then it is a row of small filled circles with labels, top-left inside the card, above the plot.

**KPI sparklines.** Below each KPI number, a bare line chart filling the card's width: 1.5–2px stroke in primary blue, no fill, no axes, no points, no labels. It occupies roughly the bottom third of the card.

**Vertical bars.** Solid primary blue, about 30% gap between bars, square corners, all bars the same color regardless of value.

**Horizontal bars.** Sorted descending, category labels right-aligned in a fixed-width column to the left of the plot, long names truncated with an ellipsis. Bars colored by rank down the palette ladder. Bar height around 24px with tight spacing. If the list overflows, use a thin grey scrollbar rail on the right of the plot area.

**Area/line.** Lines at 2px; area fills at very low opacity so overlapping series stay legible. Do not stack. The series ordering should match the legend ordering.

## Avoid

- Gradients, glassmorphism, glow, or any decorative background shapes.
- Dark mode, colored card backgrounds, or accent-colored KPI numbers.
- Icons inside KPI cards, trend arrows, or green/red change indicators.
- Rounded bar caps, donut charts, 3D effects, or animated chart entrances.
- Per-card hover lifts and transition effects on everything.
- Emoji anywhere.

## Quality floor

Responsive: below ~1100px the row-2 and row-3 cards stack to full width and KPI cards go two-up; the icon rail collapses to a top bar. Charts resize with their container rather than scrolling. Keyboard focus is visible on the segmented control and rail buttons. Respect `prefers-reduced-motion`. Check contrast on grey-on-white label text and darken `#6B6B6B` if it fails.

When you're done, render the page and compare it against this description point by point before reporting back.
