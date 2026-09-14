// Shell: rail routing, the segmented period control, the filter strip, and the
// URL hash that carries the full filter state so any view is shareable and
// survives a reload.
//
// Every screen is a module exporting the same shape -- defaults(), ranges,
// rangeKey, controls(), optional prepare(), render() -- so adding one is a
// single entry in SCREENS and nothing here special-cases a screen by name.

import { loadMeta } from './data.js';
import { readHash, writeHash, num } from './fmt.js';
import * as mapScreen from './map.js';
import * as scorecard from './scorecard.js';
import * as about from './about.js';

const SCREENS = {
  map: { title: 'Карта міграції авто', section: 'screen-map', mod: mapScreen },
  model: { title: 'Картка моделі', section: 'screen-model', mod: scorecard },
  about: { title: 'Про дані', section: 'screen-about', mod: about },
};

let meta = null;
let current = 'map';
let rendering = false;
let queued = false;

const el = (id) => document.getElementById(id);

function stateFor(screen, params) {
  const base = SCREENS[screen].mod.defaults();
  for (const k of Object.keys(base)) {
    if (params.has(k)) base[k] = params.get(k);
  }
  return base;
}

function paramsFor(screen, state) {
  const base = SCREENS[screen].mod.defaults();
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    if (v !== base[k] && v !== '') p.set(k, v);
  }
  return p;
}

function renderSeg(screen, state, setState) {
  const seg = el('seg');
  const { ranges, rangeKey } = SCREENS[screen].mod;
  seg.replaceChildren();
  // A screen with no ranges keeps the burger and nothing else; it also has no
  // rangeKey, so the loop must not run at all rather than read a missing key.
  for (const r of ranges) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = r.label;
    b.setAttribute('aria-pressed', String(state[rangeKey] === r.id));
    b.addEventListener('click', () => setState({ [rangeKey]: r.id }));
    seg.append(b);
  }
  const burger = document.createElement('span');
  burger.className = 'burger';
  burger.setAttribute('aria-hidden', 'true');
  burger.innerHTML = '<i></i><i></i><i></i>';
  seg.append(burger);
}

/** Autocomplete for the model pickers.
 *
 *  A native <datalist> is not usable here: it never reports WHICH option the
 *  user chose, only the text that landed in the input, and browsers disagree on
 *  whether picking even fires `input`. Matching that text back to a row is what
 *  broke the finder -- the option text carries a « · 12 тис.» count suffix that
 *  the suggestion filter does not match, so the lookup always missed and the
 *  charts kept showing the previous model. This selects by the row's own key
 *  and never compares display strings. */
function combobox(spec, state, setState) {
  const wrap = document.createElement('span');
  wrap.className = 'combo';
  const input = document.createElement('input');
  input.type = 'search';
  input.placeholder = spec.placeholder || '';
  input.value = spec.display(state[spec.key]) || '';
  input.autocomplete = 'off';
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-autocomplete', 'list');

  const list = document.createElement('ul');
  list.setAttribute('role', 'listbox');
  list.hidden = true;

  let rows = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    active = -1;
  };

  const highlight = () => {
    [...list.children].forEach((li, i) => {
      li.setAttribute('aria-selected', String(i === active));
      if (i === active) li.scrollIntoView({ block: 'nearest' });
    });
  };

  const choose = (i) => {
    const row = rows[i];
    if (!row) return;
    close();
    setState({ [spec.key]: row.v });
  };

  const open = () => {
    rows = spec.suggest(input.value);
    list.replaceChildren(...(rows.length ? rows : [null]).map((row, i) => {
      const li = document.createElement('li');
      if (!row) {
        li.className = 'none';
        li.textContent = 'Нічого не знайдено';
        return li;
      }
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      const name = document.createElement('b');
      name.textContent = row.label ?? row.t;
      const count = document.createElement('span');
      count.textContent = row.hint ?? '';
      li.append(name, count);
      li.addEventListener('mousedown', (ev) => { ev.preventDefault(); choose(i); });
      return li;
    }));
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    active = -1;
  };

  input.addEventListener('focus', () => {
    // The field shows the current model, so without this the first keystroke
    // appends to it ("VOLKSWAGEN PASSAT" + "OCTAVIA") and matches nothing.
    input.select();
    open();
  });
  input.addEventListener('input', open);
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      if (list.hidden) open();
      if (!rows.length) return;
      active = ev.key === 'ArrowDown'
        ? (active + 1) % rows.length
        : (active <= 0 ? rows.length : active) - 1;
      highlight();
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      choose(active >= 0 ? active : 0);
    } else if (ev.key === 'Escape') {
      close();
      input.blur();
    }
  });
  // The native clear button on input[type=search] fires `search`, not `input`.
  input.addEventListener('search', () => {
    if (!input.value) { close(); setState({ [spec.key]: '' }); }
  });

  wrap.append(input, list);
  return wrap;
}

function renderFilters(screen, state, setState) {
  const box = el('filters');
  box.replaceChildren();
  const specs = SCREENS[screen].mod.controls(state, meta) || [];
  for (const spec of specs) {
    const label = document.createElement('label');
    label.append(document.createTextNode(`${spec.label} `));

    if (spec.type === 'range') {
      const input = document.createElement('input');
      input.type = 'range';
      input.min = spec.min; input.max = spec.max; input.step = spec.step;
      input.value = state[spec.key];
      const out = document.createElement('span');
      out.className = 'hint';
      out.textContent = `${num(Number(state[spec.key]))}${spec.suffix || ''}`;
      input.addEventListener('input', () => {
        out.textContent = `${num(Number(input.value))}${spec.suffix || ''}`;
      });
      input.addEventListener('change', () => setState({ [spec.key]: input.value }));
      label.append(input, out);
    } else if (spec.type === 'search') {
      label.append(combobox(spec, state, setState));
    } else {
      const sel = document.createElement('select');
      for (const o of spec.options) {
        const opt = document.createElement('option');
        opt.value = o.v;
        opt.textContent = o.t;
        if (String(state[spec.key]) === o.v) opt.selected = true;
        sel.append(opt);
      }
      sel.addEventListener('change', () => setState({ [spec.key]: sel.value }));
      label.append(sel);
    }
    box.append(label);
  }
}

function setScreen(next) {
  current = next;
  for (const [id, s] of Object.entries(SCREENS)) {
    el(s.section).hidden = id !== next;
  }
  document.querySelectorAll('.rail button').forEach((b) => {
    b.setAttribute('aria-current', String(b.dataset.screen === next));
  });
  el('title').textContent = SCREENS[next].title;
}

async function draw(push = false) {
  // Latest wins. Dropping a change that arrives mid-fetch would leave the
  // screen showing something other than what the URL says.
  if (rendering) { queued = true; return; }
  rendering = true;
  try {
    const { screen, params } = readHash();
    const name = SCREENS[screen] ? screen : 'map';
    setScreen(name);
    const state = stateFor(name, params);
    const setState = (patch) => {
      const next = { ...state, ...patch };
      writeHash(name, paramsFor(name, next));
      draw();
    };
    await SCREENS[name].mod.prepare?.();
    renderSeg(name, state, setState);
    renderFilters(name, state, setState);
    const subtitle = await SCREENS[name].mod.render(document, meta, state, setState);
    el('subtitle').textContent = subtitle || '';
    if (push) writeHash(name, paramsFor(name, state), true);
  } catch (err) {
    console.error(err);
    el('subtitle').textContent = `Не вдалося побудувати екран: ${err.message}`;
  } finally {
    rendering = false;
    if (queued) { queued = false; draw(); }
  }
}

async function main() {
  meta = await loadMeta();
  document.querySelectorAll('.rail button').forEach((b) => {
    b.addEventListener('click', () => {
      writeHash(b.dataset.screen, new URLSearchParams());
      draw();
    });
  });
  window.addEventListener('hashchange', () => draw());
  await draw(true);
}

main().catch((err) => {
  console.error(err);
  document.getElementById('subtitle').textContent =
    `Не вдалося завантажити дані: ${err.message}`;
});
