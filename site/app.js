const data = window.PLATERRA_DATA;

const state = {
  query: '',
  category: 'all',
};

const statsEl = document.getElementById('stats');
const collectionsEl = document.getElementById('collections-grid');
const highlightsEl = document.getElementById('highlights-grid');
const notesEl = document.getElementById('notes-grid');
const filterButtonsEl = document.getElementById('filter-buttons');
const searchInputEl = document.getElementById('search-input');
const archiveGridEl = document.getElementById('archive-grid');
const catalogMetaEl = document.getElementById('catalog-meta');
const drawerEl = document.getElementById('drawer');
const drawerContentEl = document.getElementById('drawer-content');
const drawerCloseEl = document.getElementById('drawer-close');
const backdropEl = document.getElementById('backdrop');

const stats = [
  { label: 'Материалов', value: data.stats.total },
  { label: 'Проектов', value: data.stats.projects + data.stats.portfolio },
  { label: 'Публикаций', value: data.stats.blog },
  { label: 'Период', value: `${data.years.start}–${data.years.end}` },
];

function cardMedia(item) {
  if (!item.previewImage) {
    return '<div class="card__cover"></div>';
  }
  return `<div class="card__cover"><img src="${item.previewImage}" alt="${item.title}"></div>`;
}

function metaLine(item) {
  const parts = [item.categoryLabel];
  if (item.date) parts.push(item.date);
  if (item.imageCount) parts.push(`${item.imageCount} илл.`);
  return parts.map((part) => `<span>${part}</span>`).join('');
}

function renderStats() {
  statsEl.innerHTML = stats
    .map((item) => `
      <article class="stat">
        <div class="meta-chip">${item.label}</div>
        <strong>${item.value}</strong>
      </article>
    `)
    .join('');
}

function renderCollections() {
  collectionsEl.innerHTML = data.categories
    .map((category) => `
      <article class="collection">
        <div class="meta-chip">${category.label}</div>
        <strong>${category.count}</strong>
        <p>${category.description}</p>
      </article>
    `)
    .join('');
}

function renderFeatureGrid(target, items) {
  target.innerHTML = items
    .map((item) => `
      <article class="card">
        ${cardMedia(item)}
        <div class="card__meta">${metaLine(item)}</div>
        <h3>${item.title}</h3>
        <p>${item.excerpt}</p>
        <div class="card__footer">
          <button type="button" data-open-item="${item.id}">Открыть</button>
        </div>
      </article>
    `)
    .join('');
}

function renderFilters() {
  const buttons = [{ key: 'all', label: 'Все' }].concat(
    data.categories.map((category) => ({ key: category.key, label: `${category.label} · ${category.count}` }))
  );
  filterButtonsEl.innerHTML = buttons
    .map(
      (button) => `
        <button type="button" class="${button.key === state.category ? 'is-active' : ''}" data-category="${button.key}">
          ${button.label}
        </button>
      `
    )
    .join('');
}

function matches(item) {
  const query = state.query.trim().toLowerCase();
  const inCategory = state.category === 'all' || item.category === state.category;
  if (!inCategory) return false;
  if (!query) return !item.isNoise;
  const haystack = `${item.title} ${item.excerpt}`.toLowerCase();
  return haystack.includes(query);
}

function renderArchive() {
  const filtered = data.items.filter(matches);
  catalogMetaEl.textContent = `Показано ${filtered.length} из ${data.items.filter((item) => !item.isNoise).length} материалов`;
  if (!filtered.length) {
    archiveGridEl.innerHTML = '<div class="empty-state">По вашему запросу ничего не найдено.</div>';
    return;
  }
  archiveGridEl.innerHTML = filtered
    .map(
      (item) => `
        <article class="archive-card">
          <div class="archive-card__meta">${metaLine(item)}</div>
          <h3>${item.title}</h3>
          <p>${item.excerpt}</p>
          <div class="archive-card__footer">
            <button type="button" data-open-item="${item.id}">Подробнее</button>
          </div>
        </article>
      `
    )
    .join('');
}

function openDrawer(id) {
  const item = data.items.find((entry) => entry.id === id);
  if (!item) return;
  const links = [
    item.archiveUrl ? `<a href="${item.archiveUrl}" target="_blank" rel="noreferrer">Архивный снимок</a>` : '',
    item.sourceUrl ? `<a href="${item.sourceUrl}" target="_blank" rel="noreferrer">Исходный URL</a>` : '',
  ].join('');
  drawerContentEl.innerHTML = `
    <div class="drawer__hero">
      <div class="archive-card__meta">${metaLine(item)}</div>
      <h2>${item.title}</h2>
      <p>${item.excerpt}</p>
      ${item.previewImage ? `<div class="drawer__image"><img src="${item.previewImage}" alt="${item.title}"></div>` : ''}
      <div class="drawer__links">${links}</div>
    </div>
    <div class="drawer__body">${item.html}</div>
  `;
  drawerEl.classList.add('is-open');
  drawerEl.setAttribute('aria-hidden', 'false');
  backdropEl.hidden = false;
  document.body.classList.add('drawer-open');
}

function closeDrawer() {
  drawerEl.classList.remove('is-open');
  drawerEl.setAttribute('aria-hidden', 'true');
  backdropEl.hidden = true;
  document.body.classList.remove('drawer-open');
}

renderStats();
renderCollections();
renderFeatureGrid(highlightsEl, data.highlights);
renderFeatureGrid(notesEl, data.notes);
renderFilters();
renderArchive();

filterButtonsEl.addEventListener('click', (event) => {
  const button = event.target.closest('[data-category]');
  if (!button) return;
  state.category = button.dataset.category;
  renderFilters();
  renderArchive();
});

searchInputEl.addEventListener('input', (event) => {
  state.query = event.target.value;
  renderArchive();
});

document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-open-item]');
  if (trigger) {
    openDrawer(trigger.dataset.openItem);
  }
});

drawerCloseEl.addEventListener('click', closeDrawer);
backdropEl.addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeDrawer();
  }
});
