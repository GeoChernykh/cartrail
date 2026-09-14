// Ukrainian formatting plus the band-interpolated statistics the cube needs.
// Medians here are estimated from histogram bins, never exact -- every figure
// derived this way is labelled «оцінка за інтервалами» where it is shown.

const nf0 = new Intl.NumberFormat('uk-UA', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('uk-UA', { maximumFractionDigits: 1 });

export const num = (v) => (v == null ? '—' : nf0.format(v));
export const num1 = (v) => (v == null ? '—' : nf1.format(v));
export const pct = (v, digits = 1) =>
  v == null ? '—' : `${v.toFixed(digits).replace('.', ',')}%`;

export function compact(v) {
  if (v == null) return '—';
  const a = Math.abs(v);
  if (a >= 1e6) return `${nf1.format(v / 1e6)} млн`;
  if (a >= 1e3) return `${nf0.format(Math.round(v / 1e3))} тис.`;
  return nf0.format(v);
}

// Axis tick for a magnitude, kept to round values: 20 тис., 1,5 млн.
export function tick(v) {
  if (v === 0) return '0';
  return compact(v);
}

/** Median estimated from counts per bin, interpolating inside the bin that
 *  straddles the halfway point. `edges` is [[lo, hi], …] inclusive. */
export function bandMedian(counts, edges) {
  const n = counts.reduce((a, b) => a + b, 0);
  if (!n) return null;
  const half = n / 2;
  let cum = 0;
  for (let i = 0; i < counts.length && i < edges.length; i++) {
    if (cum + counts[i] >= half) {
      const [lo, hi] = edges[i];
      const within = counts[i] ? (half - cum) / counts[i] : 0;
      return lo + within * (hi - lo + 1);
    }
    cum += counts[i];
  }
  return edges[edges.length - 1][1];
}

/** Share of the whole, guarding against an empty denominator. */
export const share = (part, whole) => (whole ? (100 * part) / whole : null);

export function declension(n, one, few, many) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

export const days = (v) =>
  v == null ? '—' : `${num(Math.round(v))} ${declension(Math.round(v), 'день', 'дні', 'днів')}`;

export const years = (v) =>
  v == null ? '—' : `${num1(v)} ${declension(Math.round(v), 'рік', 'роки', 'років')}`;

/** Read `#screen?a=b&c=d` into {screen, params}. */
export function readHash() {
  const raw = location.hash.replace(/^#/, '');
  const [screen, query = ''] = raw.split('?');
  return { screen: screen || 'map', params: new URLSearchParams(query) };
}

export function writeHash(screen, params, replace = false) {
  const q = params.toString();
  const next = `#${screen}${q ? `?${q}` : ''}`;
  if (location.hash === next) return;
  if (replace) history.replaceState(null, '', next);
  else history.pushState(null, '', next);
}
