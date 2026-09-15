// Shared chart primitives. Deliberately stripped, per dashboard-style-prompt.md:
// no chart borders, no plot fill, no axis lines, no vertical gridlines, at most
// ONE dotted horizontal gridline at a round value plus a 0 baseline label,
// 4-5 sparse x labels, no data labels, no entrance animations.
//
// Charts render at real pixel size and re-render on resize rather than scaling
// a viewBox, so 14px axis text stays 14px at every container width.

import { tick } from './fmt.js';

export const C = {
  blue: '#3B6E93',
  bluegrey: '#A9C0D2',
  cyan: '#93DCF2',
  inert: '#E0E0E0',
  hi: '#2F88F7',
  warm: '#D97A3A',
  ink: '#2B2B2B',
  muted: '#6B6B6B',
};

// Categorical series descend in weight, so a ranking reads by colour as well
// as by length. Anything past the third rank is inert grey by design.
export const ladder = (i) => [C.blue, C.bluegrey, C.cyan][i] ?? C.inert;

const observed = new WeakMap();

/** Render `draw(svg, width, height)` into `el` and re-render on resize. */
export function mount(el, height, draw) {
  const render = () => {
    const w = Math.max(el.clientWidth, 220);
    el.textContent = '';
    const svg = d3.select(el).append('svg')
      .attr('width', w).attr('height', height)
      .attr('role', 'img');
    draw(svg, w, height);
  };
  render();
  if (!observed.has(el)) {
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => observed.get(el)?.());
    });
    ro.observe(el);
    observed.set(el, render);
  } else {
    observed.set(el, render);
  }
}

/** The single dotted gridline, at the largest round value that fits. */
function gridline(svg, x0, x1, y, max, fmt = tick) {
  const candidates = d3.ticks(0, max, 4).filter((t) => t > 0 && t <= max);
  const at = candidates[candidates.length - 1];
  if (at == null) return;
  svg.append('line')
    .attr('x1', x0).attr('x2', x1).attr('y1', y(at)).attr('y2', y(at))
    .attr('stroke', C.inert).attr('stroke-dasharray', '2 4');
  svg.append('text')
    .attr('x', 0).attr('y', y(at) + 4)
    .attr('fill', C.muted).attr('font-size', 12).text(fmt(at));
  svg.append('text')
    .attr('x', 0).attr('y', y(0) + 4)
    .attr('fill', C.muted).attr('font-size', 12).text(fmt(0));
}

/** Trim a label until it actually fits, measuring the rendered glyphs instead
 *  of guessing from character count -- Cyrillic caps are wider than the 7.2px
 *  average and were overflowing the label column. */
function fitLabel(node, text, maxWidth) {
  node.text(text);
  const el = node.node();
  if (!el.getComputedTextLength || el.getComputedTextLength() <= maxWidth) return;
  let lo = 1;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    node.text(`${text.slice(0, mid)}…`);
    if (el.getComputedTextLength() <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  node.text(`${text.slice(0, lo)}…`);
}

/** Horizontal bars, sorted descending, labels right-aligned in a fixed column. */
export function hbars(el, items, opts = {}) {
  const { labelWidth = 128, barHeight = 24, gap = 6, valueFmt = tick,
    color = null, max: fixedMax = null } = opts;
  const rows = items.slice().sort((a, b) => b.value - a.value);
  const height = Math.max(rows.length * (barHeight + gap) + 8, 60);
  mount(el, height, (svg, w) => {
    if (!rows.length) return;
    const valueW = 78;
    const x0 = labelWidth + 10;
    const x1 = Math.max(w - valueW, x0 + 40);
    const max = fixedMax ?? d3.max(rows, (d) => d.value) ?? 1;
    const x = d3.scaleLinear().domain([0, max || 1]).range([x0, x1]);
    rows.forEach((d, i) => {
      const y = i * (barHeight + gap) + 4;
      const text = svg.append('text')
        .attr('x', labelWidth).attr('y', y + barHeight / 2 + 4)
        .attr('text-anchor', 'end').attr('font-size', 14).attr('fill', C.ink);
      fitLabel(text, d.label, labelWidth);
      text.append('title').text(d.label);
      svg.append('rect')
        .attr('x', x0).attr('y', y)
        .attr('width', Math.max(x(d.value) - x0, d.value > 0 ? 1 : 0))
        .attr('height', barHeight)
        .attr('fill', color ? color(d, i) : ladder(i));
      svg.append('text')
        .attr('x', w - 4).attr('y', y + barHeight / 2 + 4)
        .attr('text-anchor', 'end').attr('font-size', 14).attr('fill', C.muted)
        .text(valueFmt(d.value));
    });
  });
}

/** Vertical bars: solid primary blue, ~30% gap, square corners, one colour. */
export function vbars(el, items, opts = {}) {
  const { height = 240, everyNth = null, fill = C.blue, fmt = tick } = opts;
  mount(el, height, (svg, w) => {
    if (!items.length) return;
    const pad = { l: 46, r: 6, t: 10, b: 24 };
    const max = d3.max(items, (d) => d.value) || 1;
    const y = d3.scaleLinear().domain([0, max]).nice()
      .range([height - pad.b, pad.t]);
    const x = d3.scaleBand().domain(items.map((d) => d.label))
      .range([pad.l, w - pad.r]).padding(0.3);
    gridline(svg, pad.l, w - pad.r, y, max, fmt);
    svg.selectAll('rect.b').data(items).join('rect').attr('class', 'b')
      .attr('x', (d) => x(d.label)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d.value))
      .attr('height', (d) => Math.max(y(0) - y(d.value), 0))
      .attr('fill', (d, i) => (typeof fill === 'function' ? fill(d, i) : fill))
      .append('title').text((d) => `${d.label}: ${fmt(d.value)}`);
    sparseLabels(svg, items.map((d) => d.label), x, height - pad.b + 16, everyNth);
  });
}

/** Stacked vertical bars for a two-way split (owner type). */
export function stackedBars(el, items, keys, colors, opts = {}) {
  const { height = 240 } = opts;
  mount(el, height, (svg, w) => {
    if (!items.length) return;
    const pad = { l: 46, r: 6, t: 10, b: 24 };
    const max = d3.max(items, (d) => d3.sum(keys, (k) => d[k])) || 1;
    const y = d3.scaleLinear().domain([0, max]).nice().range([height - pad.b, pad.t]);
    const x = d3.scaleBand().domain(items.map((d) => d.label))
      .range([pad.l, w - pad.r]).padding(0.3);
    gridline(svg, pad.l, w - pad.r, y, max);
    const stacked = d3.stack().keys(keys)(items);
    svg.selectAll('g.s').data(stacked).join('g').attr('class', 's')
      .attr('fill', (d, i) => colors[i])
      .selectAll('rect').data((d) => d).join('rect')
      .attr('x', (d) => x(d.data.label)).attr('width', x.bandwidth())
      .attr('y', (d) => y(d[1])).attr('height', (d) => Math.max(y(d[0]) - y(d[1]), 0))
      .append('title').text((d) => tick(d[1] - d[0]));
    sparseLabels(svg, items.map((d) => d.label), x, height - pad.b + 16);
  });
}

/** Four or five labels across the full range, never one per bar. The last
 *  category is always labelled; if the tick before it would land within one
 *  step, that tick is dropped rather than overprinting ("2025 2026"). */
function sparseLabels(svg, labels, x, y, everyNth = null) {
  if (!labels.length) return;
  const step = everyNth ?? Math.max(1, Math.ceil(labels.length / 5));
  const last = labels.length - 1;
  const idx = [];
  for (let i = 0; i <= last; i += step) idx.push(i);
  if (idx[idx.length - 1] !== last) {
    if (last - idx[idx.length - 1] < step) idx.pop();
    idx.push(last);
  }
  for (const i of idx) {
    svg.append('text')
      .attr('x', x(labels[i]) + x.bandwidth() / 2).attr('y', y)
      .attr('text-anchor', 'middle').attr('font-size', 14).attr('fill', C.muted)
      .text(labels[i]);
  }
}

/** Lines (optionally with a very low opacity area). Never stacked. */
export function lines(el, series, xs, opts = {}) {
  const { height = 320, area = false, invert = false, events = [],
    xLabel = (v) => String(v) } = opts;
  mount(el, height, (svg, w) => {
    const live = series.filter((s) => s.values.some((v) => v != null));
    if (!live.length || !xs.length) return;
    const pad = { l: 52, r: 10, t: 14, b: 26 };
    const vals = live.flatMap((s) => s.values).filter((v) => v != null);
    const max = d3.max(vals) || 1;
    const min = invert ? 1 : 0;
    const y = d3.scaleLinear()
      .domain(invert ? [max, min] : [0, max]).nice()
      .range([height - pad.b, pad.t]);
    const x = d3.scalePoint().domain(xs.map(String))
      .range([pad.l, w - pad.r]).padding(0.5);
    if (!invert) gridline(svg, pad.l, w - pad.r, y, max);

    events.forEach((ev) => {
      const at = xs.indexOf(ev.x);
      if (at < 0) return;
      const px = x(String(ev.x));
      svg.append('line').attr('x1', px).attr('x2', px)
        .attr('y1', pad.t).attr('y2', height - pad.b)
        .attr('stroke', C.inert).attr('stroke-dasharray', '2 4');
      svg.append('text').attr('x', px + 4).attr('y', pad.t + 10)
        .attr('font-size', 12).attr('fill', C.muted).text(ev.short)
        .append('title').text(ev.label);
    });

    const line = d3.line()
      .defined((_, i) => live[0] && true)
      .x((_, i) => x(String(xs[i])))
      .y((v) => y(v));
    live.forEach((s) => {
      const pts = s.values.map((v, i) => [i, v]).filter(([, v]) => v != null);
      if (!pts.length) return;
      const gen = d3.line().x(([i]) => x(String(xs[i]))).y(([, v]) => y(v));
      if (area && !invert) {
        const ar = d3.area().x(([i]) => x(String(xs[i])))
          .y0(y(0)).y1(([, v]) => y(v));
        svg.append('path').attr('d', ar(pts)).attr('fill', s.color)
          .attr('fill-opacity', 0.12);
      }
      svg.append('path').attr('d', gen(pts)).attr('fill', 'none')
        .attr('stroke', s.color).attr('stroke-width', 2);
    });
    // Same sparse-label rule as the bar charts: last tick always drawn, and the
    // one before it dropped when they would collide.
    const step = Math.max(1, Math.ceil(xs.length / 5));
    const last = xs.length - 1;
    const idx = [];
    for (let i = 0; i <= last; i += step) idx.push(i);
    if (idx[idx.length - 1] !== last) {
      if (last - idx[idx.length - 1] < step) idx.pop();
      idx.push(last);
    }
    for (const i of idx) {
      svg.append('text').attr('x', x(String(xs[i]))).attr('y', height - pad.b + 18)
        .attr('text-anchor', 'middle').attr('font-size', 14).attr('fill', C.muted)
        .text(xLabel(xs[i]));
    }
    if (invert) {
      [min, max].forEach((v) => svg.append('text').attr('x', 0).attr('y', y(v) + 4)
        .attr('font-size', 12).attr('fill', C.muted).text(v));
    }
    void line;
  });
}

/** Bare KPI sparkline: one stroke, no axes, no points, no labels. */
export function spark(el, values, color = C.blue) {
  mount(el, 52, (svg, w, h) => {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
    if (pts.length < 2) return;
    const x = d3.scaleLinear().domain([0, values.length - 1]).range([1, w - 1]);
    const y = d3.scaleLinear()
      .domain(d3.extent(pts, ([, v]) => v)).nice().range([h - 4, 4]);
    svg.append('path')
      .attr('d', d3.line().x(([i]) => x(i)).y(([, v]) => y(v))(pts))
      .attr('fill', 'none').attr('stroke', color).attr('stroke-width', 1.8);
  });
}

export function legend(el, entries) {
  el.innerHTML = entries.map((e) =>
    `<span><i style="background:${e.color}"></i>${e.label}</span>`).join('');
}

export function kpiCard({ label, value, note, spark: sparkValues, color }) {
  const card = document.createElement('div');
  card.className = 'card kpi';
  const hasSpark = Array.isArray(sparkValues) && sparkValues.some((v) => v != null);
  card.innerHTML =
    `<p class="label">${label}</p><p class="value">${value}</p>` +
    // No stray margin from an empty note, same reasoning as the spark well.
    (note ? `<p class="note">${note}</p>` : '') +
    (hasSpark ? '<div class="spark"></div>' : '');
  if (hasSpark) {
    queueMicrotask(() => spark(card.querySelector('.spark'), sparkValues, color));
  }
  return card;
}
