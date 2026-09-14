// Every fetch is a RELATIVE path so the site works unchanged under the
// https://<user>.github.io/<repo>/ base path. Nothing is fetched from an
// external host at runtime -- d3 is vendored and the geometry is committed.

const cache = new Map();

function json(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

export const loadMeta = () => json('data/meta.json');
export const loadGeo = () => json('data/oblasts.geojson');
export const loadFlows = (year) => json(`data/flows/flows_${year}.json`);
export const loadModelIndex = () => json('data/models/index.json');
export const loadShard = (slug) => json(`data/models/${slug}.json`);
// Only written when the cube overflowed and dropped its days histogram.
export const loadMedians = () => json('data/flows/medians.json');

/** Fetch several years of the cube at once; the loader caches per year. */
export const loadYears = (years) => Promise.all(years.map(loadFlows));

/** The cube's `fuel` and `dh` arrays are OPTIONAL: the build drops them when
 *  the cell count overflows. Feature-detect instead of assuming. */
export const hasFuel = (cube) => Array.isArray(cube.fuel);
export const hasDaysHist = (cube) => Array.isArray(cube.dh);
