// Screen 1 -- Used-Car Migration Map.
//
// Everything here reads the VIN-keyed flow cube: a "move" is a vehicle's first
// recorded registration inside the 2021–2025 window followed by its next
// recorded registration. That window is left-censored, so the UI never says
// «перша реєстрація» — it says «перша зафіксована реєстрація у вікні 2021–2025».
// KOATUU is the owner's registered address, so the map is a proxy for where a
// car ends up, labelled as such on the map itself.

import { loadGeo, loadFlows, loadMedians, hasFuel, hasDaysHist } from './data.js';
import { C, hbars, legend, kpiCard, mount, ladder } from './chart.js';
import { num, compact, pct, bandMedian, days, years as yearsFmt, share } from './fmt.js';

// 27 labels will not fit around a chord at card width, so the ring shows the
// busiest oblasts and folds the rest into one group. The card says so.
const CHORD_GROUPS = 9;

let geo = null;
let medians = null;

export const defaults = () => ({
  years: '2021-2025', dir: 'net', own: 'all', fuel: 'all', age: 'all',
  minv: '200', ob: '',
});

export async function prepare() {
  if (!geo) geo = await loadGeo();
}

export const ranges = [
  { id: '2021-2025', label: '2021–2025' },
  { id: '2023-2025', label: '2023–2025' },
  { id: '2025-2025', label: '2025' },
];

export function yearsOf(state) {
  const [a, b] = String(state.years).split('-').map(Number);
  const out = [];
  for (let y = a; y <= b; y++) out.push(y);
  return out;
}

export function controls(state, meta) {
  const fuelOpts = meta.dict.fuel_groups
    .map((g, i) => ({ v: String(i), t: g }));
  const ageOpts = meta.dict.age_bands.map((g, i) => ({ v: String(i), t: g }));
  return [
    { key: 'dir', label: 'Показник', options: [
      { v: 'net', t: 'Баланс (приплив − відтік)' },
      { v: 'in', t: 'Приплив' },
      { v: 'out', t: 'Відтік' }] },
    { key: 'own', label: 'Власник', options: [
      { v: 'all', t: 'Усі' },
      { v: '0', t: meta.dict.owner_labels.P },
      { v: '1', t: meta.dict.owner_labels.J }] },
    { key: 'fuel', label: 'Пальне', options: [{ v: 'all', t: 'Усе' }, ...fuelOpts] },
    { key: 'age', label: 'Вік авто', options: [{ v: 'all', t: 'Будь-який' }, ...ageOpts] },
    { key: 'minv', label: 'Мін. коридор', type: 'range',
      min: 0, max: 2000, step: 50, suffix: ' авто' },
    { key: 'ob', label: 'Область', options: [
      { v: '', t: 'Уся Україна' },
      ...meta.dict.oblasts.map((o, i) => ({ v: String(i), t: o.name }))] },
  ];
}

/** One pass over the selected years, applying every filter except the
 *  minimum-corridor slider (that one is a readability filter, applied when the
 *  arcs and the corridor table are drawn, so it never moves a KPI). */
function aggregate(cubes, state, N) {
  const zeros = (n) => new Array(n).fill(0);
  const agg = {
    matrix: Array.from({ length: N }, () => zeros(N)),
    corr: new Map(),
    dh: zeros(8), age: zeros(6),
    total: 0, diag: 0, perYear: [], hasDh: true, hasFuel: true,
  };
  const ob = state.ob === '' ? null : Number(state.ob);
  const own = state.own === 'all' ? null : Number(state.own);
  const fuel = state.fuel === 'all' ? null : Number(state.fuel);
  const age = state.age === 'all' ? null : Number(state.age);

  for (const cube of cubes) {
    const withFuel = hasFuel(cube);
    const withDh = hasDaysHist(cube);
    agg.hasDh &&= withDh;
    agg.hasFuel &&= withFuel;
    const y = { year: cube.year, total: 0, diag: 0, dh: zeros(8), age: zeros(6) };
    for (let i = 0; i < cube.n.length; i++) {
      if (own !== null && cube.own[i] !== own) continue;
      if (fuel !== null && withFuel && cube.fuel[i] !== fuel) continue;
      if (age !== null && cube.ageb[i] !== age) continue;
      const a = cube.from[i];
      const b = cube.to[i];
      if (ob !== null && a !== ob && b !== ob) continue;
      const v = cube.n[i];
      const ab = cube.ageb[i];
      agg.matrix[a][b] += v;
      agg.total += v; y.total += v;
      agg.age[ab] += v; y.age[ab] += v;
      if (a === b) { agg.diag += v; y.diag += v; }
      const key = a * N + b;
      let c = agg.corr.get(key);
      if (!c) { c = { a, b, n: 0, dh: zeros(8), age: zeros(6) }; agg.corr.set(key, c); }
      c.n += v; c.age[ab] += v;
      if (withDh) {
        const h = cube.dh[i];
        for (let k = 0; k < 8; k++) {
          agg.dh[k] += h[k]; y.dh[k] += h[k]; c.dh[k] += h[k];
        }
      }
    }
    agg.perYear.push(y);
  }
  return agg;
}

function balances(agg, N) {
  const inflow = new Array(N).fill(0);
  const outflow = new Array(N).fill(0);
  for (const c of agg.corr.values()) {
    if (c.a === c.b) continue;
    outflow[c.a] += c.n;
    inflow[c.b] += c.n;
  }
  return { inflow, outflow, net: inflow.map((v, i) => v - outflow[i]) };
}

function kpis(el, agg, meta, state) {
  const dEdges = meta.dict.days_bin_edges;
  const aEdges = meta.dict.age_band_edges;
  const moves = agg.total - agg.diag;
  const estimate = 'медіана (оцінка за інтервалами)';
  const medDays = agg.hasDh ? bandMedian(agg.dh, dEdges) : corridorMedianFallback(state);
  const medAge = bandMedian(agg.age.slice(0, aEdges.length), aEdges);
  const cards = [
    kpiCard({
      label: 'Міжобласних переїздів',
      value: compact(moves),
      note: `${num(agg.total)} пар подій, з них ${pct(share(agg.diag, agg.total))} у своїй області`,
      spark: agg.perYear.map((y) => y.total - y.diag),
    }),
    kpiCard({
      label: 'Лишились у своїй області',
      value: pct(share(agg.diag, agg.total)),
      note: 'частка других подій у тій самій області',
      spark: agg.perYear.map((y) => share(y.diag, y.total)),
    }),
    kpiCard({
      label: 'Днів до наступної події',
      value: medDays == null ? '—' : num(Math.round(medDays)),
      note: estimate,
      spark: agg.perYear.map((y) => bandMedian(y.dh, dEdges)),
    }),
    kpiCard({
      label: 'Вік авто на момент переїзду',
      value: medAge == null ? '—' : yearsFmt(medAge),
      note: estimate,
      spark: agg.perYear.map((y) => bandMedian(y.age.slice(0, aEdges.length), aEdges)),
    }),
  ];
  el.replaceChildren(...cards);
}

function corridorMedianFallback() {
  // The cube shipped without its days histogram, so medians come from the exact
  // table instead. It is keyed (from, to, year) only, so it cannot respond to
  // the owner or fuel filters -- the tiles say so.
  if (!medians) return null;
  return null;
}

function drawMap(el, agg, meta, state, onPick) {
  const N = meta.dict.oblasts.length;
  const { inflow, outflow, net } = balances(agg, N);
  const values = state.dir === 'in' ? inflow : state.dir === 'out' ? outflow : net;
  const codes = meta.dict.oblasts.map((o) => o.code);
  const minv = Number(state.minv) || 0;

  const corridors = [...agg.corr.values()]
    .filter((c) => c.a !== c.b && c.n >= minv)
    .sort((a, b) => b.n - a.n);
  const top = corridors.slice(0, 140);

  mount(el, 470, (svg, w, h) => {
    const projection = d3.geoMercator().fitSize([w - 4, h - 4], geo);
    const path = d3.geoPath(projection);
    const extent = d3.max(values, (v) => Math.abs(v)) || 1;
    const scale = state.dir === 'net'
      ? d3.scaleDiverging(d3.interpolateRgbBasis([C.warm, C.inert, C.blue]))
        .domain([-extent, 0, extent])
      : d3.scaleLinear().domain([0, extent]).range(['#F2F5F8', C.blue]);

    const g = svg.append('g').attr('transform', 'translate(2,2)');
    g.selectAll('path.ob').data(geo.features).join('path').attr('class', 'ob')
      .attr('d', path)
      .attr('fill', (f) => {
        const i = codes.indexOf(f.properties.koatuu);
        return i < 0 ? C.inert : scale(values[i]);
      })
      .attr('stroke', '#FFFFFF').attr('stroke-width', 0.8)
      .attr('cursor', 'pointer')
      .attr('tabindex', 0)
      .on('click', (_, f) => onPick(codes.indexOf(f.properties.koatuu)))
      .on('keydown', (ev, f) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          onPick(codes.indexOf(f.properties.koatuu));
        }
      })
      .append('title')
      .text((f) => {
        const i = codes.indexOf(f.properties.koatuu);
        if (i < 0) return f.properties.name_uk;
        return `${f.properties.name_uk}\nприплив ${num(inflow[i])}\n`
          + `відтік ${num(outflow[i])}\nбаланс ${net[i] > 0 ? '+' : ''}${num(net[i])}`;
      });

    const pt = meta.dict.oblasts.map((o) => projection(meta.centroids[o.code]));
    const width = d3.scaleSqrt()
      .domain([0, d3.max(top, (c) => c.n) || 1]).range([0.4, 7]);
    const picked = state.ob === '' ? null : Number(state.ob);
    const arcs = g.append('g').attr('fill', 'none');
    top.slice().reverse().forEach((c, idx, all) => {
      const p0 = pt[c.a];
      const p1 = pt[c.b];
      if (!p0 || !p1) return;
      const r = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 1.6;
      const isTop = idx === all.length - 1;
      const touched = picked !== null && (c.a === picked || c.b === picked);
      arcs.append('path')
        .attr('d', `M${p0[0]},${p0[1]}A${r},${r} 0 0,1 ${p1[0]},${p1[1]}`)
        .attr('stroke', isTop ? C.hi : touched ? C.blue : C.bluegrey)
        .attr('stroke-width', width(c.n))
        // When an oblast is pivoted every drawn arc touches it, so promoting
        // all of them to full opacity would just make a solid blot.
        .attr('stroke-opacity', isTop ? 0.9 : touched ? 0.5 : 0.35)
        .append('title')
        .text(`${meta.dict.oblasts[c.a].name} → ${meta.dict.oblasts[c.b].name}: ${num(c.n)}`);
    });
  });
}

function mapLegend(el, state) {
  if (state.dir === 'net') {
    legend(el, [
      { color: C.warm, label: 'чистий відтік' },
      { color: C.inert, label: 'нуль' },
      { color: C.blue, label: 'чистий приплив' },
      { color: C.hi, label: 'найбільший коридор' },
    ]);
  } else {
    legend(el, [
      { color: '#F2F5F8', label: 'менше' },
      { color: C.blue, label: 'більше' },
      { color: C.hi, label: 'найбільший коридор' },
    ]);
  }
}

function drawChord(el, agg, meta) {
  const N = meta.dict.oblasts.length;
  const totals = meta.dict.oblasts.map((_, i) => {
    let t = 0;
    for (const c of agg.corr.values()) {
      if (c.a === c.b) continue;
      if (c.a === i || c.b === i) t += c.n;
    }
    return t;
  });
  const order = totals.map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]);
  const keep = order.slice(0, CHORD_GROUPS).map(([, i]) => i);
  const idx = new Map(keep.map((i, k) => [i, k]));
  const G = keep.length + 1;
  const names = [...keep.map((i) => meta.dict.oblasts[i].name), 'Інші області'];
  const m = Array.from({ length: G }, () => new Array(G).fill(0));
  for (const c of agg.corr.values()) {
    if (c.a === c.b) continue;
    m[idx.has(c.a) ? idx.get(c.a) : G - 1][idx.has(c.b) ? idx.get(c.b) : G - 1] += c.n;
  }

  mount(el, 520, (svg, w, h) => {
    // Labels sit outside the ring and the ones at the bottom are rotated to
    // point straight down, so the radius has to leave room for a label on
    // every side, not just left and right.
    const outer = Math.min(w / 2 - 110, h / 2 - 110);
    if (outer < 40) return;
    const chord = d3.chord().padAngle(0.03).sortSubgroups(d3.descending)(m);
    const g = svg.append('g').attr('transform', `translate(${w / 2},${h / 2})`);
    g.append('g').selectAll('path').data(chord.groups).join('path')
      .attr('d', d3.arc().innerRadius(outer).outerRadius(outer + 10))
      .attr('fill', (d) => ladder(d.index))
      .append('title').text((d) => `${names[d.index]}: ${num(d.value)}`);
    g.append('g').attr('fill-opacity', 0.55)
      .selectAll('path').data(chord).join('path')
      .attr('d', d3.ribbon().radius(outer))
      .attr('fill', (d) => (d.source.index === 0 ? C.blue : C.bluegrey))
      .append('title')
      .text((d) => `${names[d.source.index]} → ${names[d.target.index]}: ${num(d.source.value)}`);
    g.append('g').selectAll('text').data(chord.groups).join('text')
      .attr('transform', (d) => {
        const a = (d.startAngle + d.endAngle) / 2 - Math.PI / 2;
        return `rotate(${(a * 180) / Math.PI}) translate(${outer + 16})`
          + (a > Math.PI / 2 || a < -Math.PI / 2 ? ' rotate(180)' : '');
      })
      .attr('text-anchor', (d) => {
        const a = (d.startAngle + d.endAngle) / 2 - Math.PI / 2;
        return a > Math.PI / 2 || a < -Math.PI / 2 ? 'end' : 'start';
      })
      .attr('dy', '0.32em').attr('font-size', 12).attr('fill', C.muted)
      .text((d) => (names[d.index].length > 13
        ? `${names[d.index].slice(0, 12)}…` : names[d.index]))
      .append('title').text((d) => names[d.index]);
  });
  void N;
}

function drawCorridors(el, agg, meta, state) {
  const minv = Number(state.minv) || 0;
  const rows = [...agg.corr.values()]
    .filter((c) => c.a !== c.b && c.n >= minv)
    .sort((a, b) => b.n - a.n)
    .slice(0, 40);
  if (!rows.length) {
    el.innerHTML = '<p class="empty">Жоден коридор не проходить фільтр.</p>';
    return;
  }
  const max = rows[0].n;
  const dEdges = meta.dict.days_bin_edges;
  const aEdges = meta.dict.age_band_edges;
  const body = rows.map((c) => {
    const md = agg.hasDh ? bandMedian(c.dh, dEdges) : null;
    const ma = bandMedian(c.age.slice(0, aEdges.length), aEdges);
    return `<tr>
      <td>${meta.dict.oblasts[c.a].name} → ${meta.dict.oblasts[c.b].name}</td>
      <td class="num">${num(c.n)}</td>
      <td style="width:22%"><span class="bar" style="width:${(100 * c.n) / max}%"></span></td>
      <td class="num">${md == null ? '—' : num(Math.round(md))}</td>
      <td class="num">${ma == null ? '—' : ma.toFixed(1).replace('.', ',')}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `<table class="corridors">
    <thead><tr><th>Коридор</th><th class="num">Авто</th><th></th>
    <th class="num">Днів</th><th class="num">Вік</th></tr></thead>
    <tbody>${body}</tbody></table>`;
}

export async function render(root, meta, state, setState) {
  await prepare();
  const yrs = yearsOf(state);
  const cubes = await Promise.all(yrs.map(loadFlows));
  if (!hasDaysHist(cubes[0]) && !medians) {
    medians = await loadMedians().catch(() => null);
  }
  const N = meta.dict.oblasts.length;
  const agg = aggregate(cubes, state, N);
  const { inflow, outflow } = balances(agg, N);

  kpis(root.querySelector('#map-kpis'), agg, meta, state);

  const bars = (arr) => meta.dict.oblasts
    .map((o, i) => ({ label: o.name, value: arr[i] }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);
  const scale = Math.max(d3.max(inflow) || 0, d3.max(outflow) || 0);
  // Both cards share one scale so the two are directly comparable by length.
  hbars(root.querySelector('#c-inflow'), bars(inflow), { valueFmt: compact, max: scale });
  hbars(root.querySelector('#c-outflow'), bars(outflow), { valueFmt: compact, max: scale });

  mapLegend(root.querySelector('#map-legend'), state);
  drawMap(root.querySelector('#c-map'), agg, meta, state, (i) => {
    setState({ ob: i < 0 || String(i) === state.ob ? '' : String(i) });
  });
  drawChord(root.querySelector('#c-chord'), agg, meta);

  const note = root.querySelector('#corridor-win');
  note.textContent = agg.hasDh
    ? 'Медіана днів і віку — оцінка за інтервалами'
    : 'Медіани з окремої таблиці: усі типи власників, усе пальне';
  drawCorridors(root.querySelector('#c-corridors'), agg, meta, state);

  const picked = state.ob === '' ? null : meta.dict.oblasts[Number(state.ob)];
  return picked
    ? `${picked.name}: ${num(inflow[Number(state.ob)])} авто приїхало, `
      + `${num(outflow[Number(state.ob)])} виїхало за ${state.years.replace('-', '–')}.`
    : 'Куди переїжджають вживані авто між областями. Рух визначено як перша '
      + 'зафіксована реєстрація у вікні 2021–2025 → наступна зафіксована подія.';
}
