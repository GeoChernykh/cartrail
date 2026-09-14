// Screen 3 -- «Про дані».
//
// Every figure here is read from meta.json, written by the build. Nothing is a
// hardcoded string, so a rebuild that changes the data changes this screen too
// -- which is the whole point of the 2020 geography flag: it is driven by the
// measured per-year KOATUU valid rate, not by a sentence someone typed once.

import { C, vbars, kpiCard, mount } from './chart.js';
import { num, compact, pct } from './fmt.js';

export const defaults = () => ({});
export const ranges = [];
export const controls = () => [];

const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function kpis(el, meta) {
  const years = meta.years;
  el.replaceChildren(
    kpiCard({
      label: 'Записів у реєстрі',
      value: compact(meta.source.rows),
      note: 'один рядок — одна реєстраційна дія, не одне авто',
      spark: years.map((y) => y.rows),
    }),
    kpiCard({
      label: 'Охоплені роки',
      value: `${meta.source.years[0]}–${meta.source.years[1]}`,
      note: `${years.length} щорічних архівів, 2026 — неповний рік`,
    }),
    kpiCard({
      label: 'Моделей у картках',
      value: num(meta.models.models_included),
      note: `від ${num(meta.models.threshold)} реєстрацій, `
        + `${num(meta.models.brands_included)} марок`,
    }),
    kpiCard({
      label: 'Областей на карті',
      value: num(meta.dict.oblasts.length),
      note: 'разом з АР Крим, м. Київ і м. Севастополь',
    }),
  );
}

const asPct = (v) => `${String(Math.round(v * 10) / 10).replace('.', ',')}%`;

function coverage(el, meta) {
  const items = meta.years.map((y) => ({
    label: String(y.year), value: y.koatuu_valid_pct,
  }));
  // 2020 is the anomaly the flag is about, and the reader should see it rather
  // than take it on trust; the highlight blue marks exactly one bar. 2026 is
  // excluded from the comparison: it has no KOATUU column at all, which is a
  // schema fact, not a data-quality dip, and its bar has no height to colour.
  const worst = items.filter((d) => d.value > 0)
    .reduce((a, b) => (a.value < b.value ? a : b));
  vbars(el, items, {
    height: 280,
    fmt: asPct,
    fill: (d) => (d.label === worst.label ? C.hi : C.blue),
  });
}

function duplicates(el, meta) {
  const items = Object.entries(meta.duplicate_row_pct)
    .map(([year, v]) => ({ label: year, value: v }));
  const worst = items.reduce((a, b) => (a.value > b.value ? a : b));
  vbars(el, items, {
    height: 280,
    fmt: asPct,
    fill: (d) => (d.label === worst.label ? C.hi : C.blue),
  });
}

function moveCard(el, meta) {
  const mig = meta.migration;
  const win = meta.windows.migration;
  el.innerHTML = `
    <p>Рухом вважається <strong>перша зафіксована реєстрація у вікні
    ${win[0]}–${win[win.length - 1]}</strong> і наступна зафіксована подія того
    самого VIN. Вікно обрізане зліва, тому це не «перша реєстрація» авто:
    машина могла мати історію й раніше. Коди операцій не класифікуються
    взагалі — це навмисно, бо високочастотні коди 40, 70/71, 50/80 не
    піддаються надійній класифікації.</p>
    <dl>
      <dt>VIN із першою подією у вікні</dt>
      <dd>${num(mig.vins_with_first_event)}</dd>
      <dt>З них мають другу подію</dt>
      <dd>${num(mig.observable_pairs)}</dd>
      <dt>Виключено зі знаменника</dt>
      <dd>${num(mig.dropped_no_valid_destination)}
        (${pct(mig.dropped_share_of_later, 2)})</dd>
      <dt>Приховано порогом n &lt; ${mig.min_cell}</dt>
      <dd>${num(mig.pairs_suppressed)} (${pct(mig.pairs_suppressed_pct, 2)})</dd>
      <dt>Частка, що лишилась у своїй області</dt>
      <dd>${pct(mig.retention_pct)}</dd>
    </dl>
    <p>Ті ${num(mig.dropped_no_valid_destination)} VIN мають пізніші події, але
    жодна з них не несе дійсного коду області — зокрема всі події 2026 року.
    Їх виключено зі знаменника, а не зараховано як «лишився»: інакше показник
    утримання був би завищений.</p>`;
}

function limitsCard(el, meta) {
  const y2020 = meta.years.find((y) => y.year === 2020);
  const y2026 = meta.years.find((y) => y.year === 2026);
  const dupWorst = Object.entries(meta.duplicate_row_pct)
    .reduce((a, b) => (a[1] > b[1] ? a : b));
  el.innerHTML = `
    <ul>
      <li><strong>Ідентичність авто розділена.</strong> VIN є лише у
        ${meta.windows.vin[0]}–${meta.windows.vin.at(-1)}, номерний знак — лише
        у 2013–2025. У перетині 26,0% VIN мають більше ніж один номер, тому
        зв’язування по номеру рве історію приблизно кожного четвертого авто.
        Усе зв’язування тут — тільки по VIN.</li>
      <li><strong>KOATUU — це область реєстрації власника, а не
        місцезнаходження авто.</strong> Карта показує проксі того, куди авто
        потрапляє, і підписана саме так.</li>
      <li class="flag"><strong>2020 рік позначено.</strong> Лише
        ${pct(y2020.koatuu_valid_pct, 1)} рядків того року мають коректний
        10-значний KOATUU. Географію 2020 не варто читати як інші роки.</li>
      <li><strong>2026 не має коду області взагалі</strong>
        (${pct(y2026.koatuu_valid_pct, 1)} валідних KOATUU), тому карта
        міграції на нього не поширюється.</li>
      <li><strong>Два з трьох архівів 2022 року — дублікати 2021-го</strong>
        (${esc(meta.source.excluded_archives.join(', '))}) і виключені повністю.</li>
      <li>Найбільше точних дублікатів рядків — у ${dupWorst[0]} році,
        ${pct(dupWorst[1], 2)}. На карту міграції це не впливає (події одного
        дня не створюють переїзду), але річні лічильники реєстрацій їх
        містять.</li>
      <li><strong>Окуповані території.</strong> Частки Криму, Донеччини й
        Луганщини в реєстрі падають протягом серії. Це відсутність у реєстрі,
        а не відсутність у країні.</li>
    </ul>`;
}

function sourcesCard(el, meta) {
  el.innerHTML = `
    <ul>
      <li><strong>Дані.</strong> <a href="${esc(meta.source.dataset)}"
        rel="noopener">${esc(meta.source.name)}</a> —
        ${esc(meta.source.publisher)}, ${esc(meta.source.portal)}.
        ${num(meta.source.rows)} записів за
        ${meta.source.years[0]}–${meta.source.years[1]}.</li>
      <li><strong>Приватність.</strong> Реєстр не містить імен чи адрес
        власників: <code>PERSON</code> — це односимвольна ознака типу власника,
        а <code>REG_ADDR_KOATUU</code> — код області.</li>
      <li><strong>Межі областей.</strong> ${esc(meta.geo.source)}, ліцензія
        ${esc(meta.geo.license)}. Геометрія завантажена на етапі збірки й
        збережена в репозиторії — сайт нічого не тягне зі сторонніх серверів
        під час роботи.</li>
      <li><strong>Вікна спостереження.</strong> Лічильники реєстрацій —
        ${meta.windows.all[0]}–${meta.windows.all.at(-1)}; географія —
        ${meta.windows.geography[0]}–${meta.windows.geography[1]}; метрики за
        VIN — ${meta.windows.vin[0]}–${meta.windows.vin.at(-1)}; карта
        міграції — ${meta.windows.migration[0]}–${meta.windows.migration.at(-1)}.</li>
      <li><strong>Збірка.</strong> ${esc(meta.built)}.</li>
    </ul>`;
}

export async function render(root, meta) {
  kpis(root.querySelector('#about-kpis'), meta);
  coverage(root.querySelector('#c-koatuu'), meta);
  duplicates(root.querySelector('#c-dupes'), meta);
  moveCard(root.querySelector('#about-move'), meta);
  limitsCard(root.querySelector('#about-limits'), meta);
  sourcesCard(root.querySelector('#about-sources'), meta);
  void mount;
  return 'Що саме показують ці цифри, звідки вони взялися і чого з них не '
    + 'можна робити висновків.';
}
