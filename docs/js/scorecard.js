// Screen 2 -- Model Scorecard.
//
// Two observation windows are mixed here, so every tile states its own window
// rather than relying on one footnote: row-count metrics run 2013–2026,
// regional concentration 2013–2025 (2026 has no KOATUU), and the VIN-keyed
// resale/ownership metrics 2021–2026 (VIN exists only from 2021).

import { loadModelIndex, loadShard, loadGeo } from './data.js';
import { C, hbars, lines, stackedBars, legend, kpiCard, mount } from './chart.js';
import { num, compact, pct, days, years as yearsFmt } from './fmt.js';

let index = null;
let geo = null;

export const defaults = () => ({ m: '', c: '', range: '2013-2026' });

/** The filter strip is built before render(), and the autocomplete needs the
 *  model index to resolve a key from the hash, so loading happens here. */
export async function prepare() {
  if (!index) index = await loadModelIndex();
  if (!geo) geo = await loadGeo();
}

export const rangeKey = 'range';
export const ranges = [
  { id: '2013-2026', label: '2013–2026' },
  { id: '2019-2026', label: '2019–2026' },
  { id: '2022-2026', label: '2022–2026' },
];

const keyOf = (row) => `${row.s}|${row.m}`;
const labelOf = (row) => `${index.brands[row.b]} ${row.m}`;

/** Suggestions for the combobox: the key is what gets selected, `label` and
 *  `hint` are only ever displayed. index.models is pre-sorted by volume, so the
 *  first 30 matches are the 30 most-registered. */
function suggest(q) {
  if (!index) return [];
  const needle = q.trim().toUpperCase();
  const out = [];
  for (const row of index.models) {
    if (needle && !labelOf(row).toUpperCase().includes(needle)) continue;
    out.push({ v: keyOf(row), label: labelOf(row), hint: compact(row.n) });
    if (out.length >= 30) break;
  }
  return out;
}

const rowFor = (key) => index?.models.find((r) => keyOf(r) === key) || null;

// With no model in the hash the screen shows the most-registered model. The
// hash stays clean (no `m` param) so the default link is still shareable.
const fallbackKey = () => (index?.models.length ? keyOf(index.models[0]) : '');

export function controls(state) {
  return [
    { key: 'm', label: 'Модель', type: 'search', placeholder: 'Наприклад, VOLKSWAGEN GOLF',
      suggest,
      display: (v) => { const r = rowFor(v || fallbackKey()); return r ? labelOf(r) : ''; } },
    { key: 'c', label: 'Порівняти з', type: 'search', placeholder: 'Друга модель (не обов’язково)',
      suggest, display: (v) => { const r = rowFor(v); return r ? labelOf(r) : ''; } },
  ];
}

async function modelData(key) {
  const row = rowFor(key);
  if (!row) return null;
  // The two compared models often live in DIFFERENT brand shards, so each is
  // fetched and cached per shard rather than assuming one file holds both.
  const shard = await loadShard(row.s);
  const m = shard.models?.[row.m];
  return m ? { row, label: labelOf(row), data: m } : null;
}

function yearWindow(state, meta) {
  const [a, b] = String(state.range).split('-').map(Number);
  const all = meta.windows.all;
  const from = all.indexOf(a);
  const to = all.indexOf(b);
  return { from: from < 0 ? 0 : from, to: to < 0 ? all.length - 1 : to, all };
}

function eventMarkers(meta, xs) {
  const byYear = new Map();
  for (const ev of meta.events) {
    const y = Number(ev.date.slice(0, 4));
    if (!xs.includes(y)) continue;
    const short = ev.end ? `${y} безмито` : String(y);
    const prev = byYear.get(y);
    byYear.set(y, prev
      ? { x: y, short: prev.short, label: `${prev.label} · ${ev.label}` }
      : { x: y, short, label: ev.label });
  }
  return [...byYear.values()];
}

function kpis(el, primary, meta) {
  const d = primary.data;
  const cards = [
    kpiCard({
      label: 'Реєстрацій · 2013–2026',
      value: compact(d.n),
      note: '2026 — неповний рік',
      spark: d.y,
    }),
    kpiCard({
      label: 'Вік при реєстрації · 2013–2026',
      value: d.am == null ? '—' : yearsFmt(d.am),
      note: 'медіана по всьому вікну',
      spark: d.a,
    }),
    kpiCard({
      label: 'Перепродажі · 2021–2026',
      value: d.rs == null ? '—' : pct(d.rs),
      note: `частка VIN із двома і більше подіями (${compact(d.vn)} VIN)`,
    }),
    kpiCard({
      label: 'Володіння · 2021–2026',
      value: d.od == null ? '—' : days(d.od),
      note: 'медіана між сусідніми подіями того самого VIN',
    }),
  ];
  el.replaceChildren(...cards);
  void meta;
}

function mixBars(el, counts, labels) {
  const total = counts.reduce((a, b) => a + b, 0);
  const items = counts
    .map((v, i) => ({ label: labels[i], value: v }))
    .filter((d) => d.value > 0);
  hbars(el, items, {
    labelWidth: 132,
    valueFmt: (v) => (total ? `${((100 * v) / total).toFixed(1).replace('.', ',')}%` : '—'),
  });
}

function regionMap(el, counts, meta) {
  const codes = meta.dict.oblasts.map((o) => o.code);
  const total = counts.reduce((a, b) => a + b, 0);
  mount(el, 300, (svg, w, h) => {
    if (!geo) return;
    const projection = d3.geoMercator().fitSize([w - 4, h - 4], geo);
    const path = d3.geoPath(projection);
    const max = d3.max(counts) || 1;
    const scale = d3.scaleLinear().domain([0, max]).range(['#F2F5F8', C.blue]);
    svg.append('g').attr('transform', 'translate(2,2)')
      .selectAll('path').data(geo.features).join('path')
      .attr('d', path)
      .attr('fill', (f) => {
        const i = codes.indexOf(f.properties.koatuu);
        return i < 0 ? C.inert : scale(counts[i]);
      })
      .attr('stroke', '#FFFFFF').attr('stroke-width', 0.8)
      .append('title')
      .text((f) => {
        const i = codes.indexOf(f.properties.koatuu);
        if (i < 0) return f.properties.name_uk;
        const sh = total ? ((100 * counts[i]) / total).toFixed(1).replace('.', ',') : '0';
        return `${f.properties.name_uk}: ${num(counts[i])} (${sh}%)`;
      });
  });
}

export async function render(root, meta, state) {
  await prepare();

  let primary = state.m ? await modelData(state.m) : null;
  if (!primary) primary = await modelData(fallbackKey());
  if (!primary) throw new Error('індекс моделей порожній');
  const compare = state.c ? await modelData(state.c) : null;

  const { from, to, all } = yearWindow(state, meta);
  const xs = all.slice(from, to + 1);
  const slice = (arr) => (arr || []).slice(from, to + 1);

  kpis(root.querySelector('#model-kpis'), primary, meta);

  mixBars(root.querySelector('#c-fuel'), primary.data.f, meta.dict.fuel_groups);
  mixBars(root.querySelector('#c-color'), primary.data.c, meta.dict.colors);
  mixBars(root.querySelector('#c-body'), primary.data.bd, meta.dict.bodies);

  const series = [{ label: primary.label, color: C.hi, values: slice(primary.data.y) }];
  if (compare) {
    series.push({ label: compare.label, color: C.blue, values: slice(compare.data.y) });
  }
  legend(root.querySelector('#trend-legend'),
    series.map((s) => ({ color: s.color, label: s.label })));
  lines(root.querySelector('#c-trend'), series, xs,
    { height: 360, area: true, events: eventMarkers(meta, xs) });

  regionMap(root.querySelector('#c-region'), primary.data.r, meta);

  const rankSeries = [
    { label: primary.label, color: C.hi, values: slice(primary.data.rk) },
  ];
  if (compare) {
    rankSeries.push({ label: compare.label, color: C.blue, values: slice(compare.data.rk) });
  }
  legend(root.querySelector('#rank-legend'),
    rankSeries.map((s) => ({ color: s.color, label: s.label })));
  lines(root.querySelector('#c-rank'), rankSeries, xs, { height: 300, invert: true });

  const ownItems = xs.map((y, i) => ({
    label: String(y),
    P: slice(primary.data.p)[i] || 0,
    J: slice(primary.data.j)[i] || 0,
  }));
  legend(root.querySelector('#own-legend'), [
    { color: C.blue, label: meta.dict.owner_labels.P },
    { color: C.bluegrey, label: meta.dict.owner_labels.J },
  ]);
  stackedBars(root.querySelector('#c-owner'), ownItems, ['P', 'J'],
    [C.blue, C.bluegrey], { height: 300 });

  const rk = primary.data.rk.filter((v) => v != null);
  const lastRank = rk.length ? rk[rk.length - 1] : null;
  const prevRank = rk.length > 1 ? rk[rk.length - 2] : null;
  const move = lastRank != null && prevRank != null ? prevRank - lastRank : null;
  const moveText = move == null ? ''
    : move === 0 ? ' Ранг не змінився за рік.'
      : ` Ранг ${move > 0 ? 'піднявся' : 'опустився'} на ${Math.abs(move)} за рік.`;
  return `${primary.label}: ${num(primary.data.n)} реєстрацій за 2013–2026`
    + (lastRank ? `, №${lastRank} у національному топі.` : '.')
    + moveText;
}
