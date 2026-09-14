// Shell: rail routing, the segmented period control, the filter strip, the
// «Про дані» panel, and the URL hash that carries the full filter state so any
// view is shareable and survives a reload.

import { loadMeta } from './data.js';
import { readHash, writeHash, num, pct } from './fmt.js';
import * as mapScreen from './map.js';
import * as scorecard from './scorecard.js';

const SCREENS = {
  map: { title: 'Карта міграції авто', section: 'screen-map', mod: mapScreen },
  model: { title: 'Картка моделі', section: 'screen-model', mod: scorecard },
};

let meta = null;
let current = 'map';
let aboutOpen = false;
let rendering = false;

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
  seg.replaceChildren();
  for (const r of SCREENS[screen].mod.ranges) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = r.label;
    const key = screen === 'map' ? 'years' : 'range';
    b.setAttribute('aria-pressed', String(state[key] === r.id));
    b.addEventListener('click', () => setState({ [key]: r.id }));
    seg.append(b);
  }
  const burger = document.createElement('span');
  burger.className = 'burger';
  burger.setAttribute('aria-hidden', 'true');
  burger.innerHTML = '<i></i><i></i><i></i>';
  seg.append(burger);
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
      const input = document.createElement('input');
      input.type = 'search';
      input.placeholder = spec.placeholder || '';
      input.value = spec.display(state[spec.key]) || '';
      const listId = `dl-${spec.key}`;
      const dl = document.createElement('datalist');
      dl.id = listId;
      input.setAttribute('list', listId);
      const fill = () => {
        dl.replaceChildren(...spec.suggest(input.value).map((o) => {
          const opt = document.createElement('option');
          opt.value = o.t;
          opt.dataset.value = o.v;
          return opt;
        }));
      };
      fill();
      input.addEventListener('input', () => {
        fill();
        const hit = [...dl.children].find((o) => o.value === input.value);
        if (hit) setState({ [spec.key]: hit.dataset.value });
      });
      input.addEventListener('search', () => {
        if (!input.value) setState({ [spec.key]: '' });
      });
      label.append(input, dl);
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

function renderAbout() {
  const box = el('about');
  box.hidden = !aboutOpen;
  if (!aboutOpen || box.dataset.built) return;
  box.dataset.built = '1';
  const y2020 = meta.years.find((y) => y.year === 2020);
  const y2025 = meta.years.find((y) => y.year === 2025);
  const mig = meta.migration;
  const dup2025 = meta.duplicate_row_pct['2025'];
  box.innerHTML = `
    <h2 id="about-h">Про дані</h2>
    <ul>
      <li>Джерело — <a href="${meta.source.dataset}">${meta.source.name}</a>,
        ${meta.source.publisher}, ${meta.source.portal}.
        ${num(meta.source.rows)} записів за ${meta.source.years[0]}–${meta.source.years[1]}.
        Один рядок — одна реєстраційна дія, а не одне авто.</li>
      <li><strong>Ідентичність авто розділена.</strong> VIN є лише у 2021–2026,
        номерний знак — лише у 2013–2025. У перетині 26,0% VIN мають більше ніж
        один номер, тому зв’язування по номеру рве історію приблизно кожного
        четвертого авто. Усе зв’язування тут — тільки по VIN.</li>
      <li><strong>KOATUU — це область реєстрації власника, а не місцезнаходження
        авто.</strong> Карта показує проксі того, куди авто потрапляє.</li>
      <li><strong>Карта міграції побудована на 2021–2025</strong> — єдине вікно,
        де VIN і KOATUU існують одночасно. У 2026 немає ані коду області, ані
        номерного знака.</li>
      <li>Рух визначено як <em>перша зафіксована реєстрація у вікні 2021–2025 →
        наступна зафіксована подія</em>. Вікно обрізане зліва, тому це не
        «перша реєстрація» авто. Операційні коди не класифікуються взагалі.</li>
      <li>${num(mig.dropped_no_valid_destination)} VIN
        (${pct(mig.dropped_share_of_later, 2)} тих, у кого є пізніша подія) мають
        пізніші події без дійсного коду області — їх виключено зі знаменника, а
        не зараховано як «лишився».</li>
      <li>Комірки з менш ніж ${mig.min_cell} авто приховано:
        ${num(mig.pairs_suppressed)} пар (${pct(mig.pairs_suppressed_pct, 2)}).</li>
      <li class="flag"><strong>2020 рік позначено:</strong> лише
        ${pct(y2020.koatuu_valid_pct, 1)} рядків того року мають коректний
        10-значний KOATUU. Географію 2020 не варто читати як інші роки.</li>
      <li><strong>Два з трьох архівів 2022 року — дублікати 2021-го</strong>
        (${meta.source.excluded_archives.join(', ')}) і виключені повністю.</li>
      <li>У ${y2025.year} році ${pct(dup2025, 2)} рядків — точні дублікати.
        На карту міграції це не впливає (події одного дня не створюють переїзду),
        але річні лічильники реєстрацій їх містять.</li>
      <li><strong>Окуповані території.</strong> Частки Криму, Донеччини й
        Луганщини в реєстрі падають протягом серії. Це відсутність у реєстрі,
        а не відсутність у країні.</li>
      <li>Моделі з менш ніж ${num(meta.models.threshold)} реєстраціями не
        показуються: у картках ${num(meta.models.models_included)} моделей
        ${num(meta.models.brands_included)} марок.</li>
      <li>Межі областей — ${meta.geo.source}, ліцензія ${meta.geo.license}.
        Зібрано ${meta.built}.</li>
    </ul>`;
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
  if (rendering) return;
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
    renderAbout();
    const subtitle = await SCREENS[name].mod.render(document, meta, state, setState);
    el('subtitle').textContent = subtitle || '';
    if (push) writeHash(name, paramsFor(name, state), true);
  } catch (err) {
    console.error(err);
    el('subtitle').textContent = `Не вдалося побудувати екран: ${err.message}`;
  } finally {
    rendering = false;
  }
}

async function main() {
  meta = await loadMeta();
  document.querySelectorAll('.rail button').forEach((b) => {
    b.addEventListener('click', () => {
      if (b.dataset.screen === 'about') {
        aboutOpen = !aboutOpen;
        b.setAttribute('aria-current', String(aboutOpen));
        renderAbout();
        return;
      }
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
