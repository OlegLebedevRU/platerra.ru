from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"
MEDIA_DIR = SITE_DIR / "media"

CATEGORY_LABELS = {
    "projects": "Проекты",
    "portfolio": "Портфолио",
    "other-pages": "Материалы",
    "blog-posts": "Блог",
    "unmatched": "Архив",
}

CATEGORY_DESCRIPTIONS = {
    "projects": "Исторические страницы и продуктовые презентации",
    "portfolio": "Внедрения, кейсы и отраслевые решения",
    "other-pages": "Сервисные страницы, лендинги и заметки",
    "blog-posts": "Публикации о платежах, интерфейсах и развитии платформ",
    "unmatched": "Материалы без точной классификации",
}

CATEGORY_ORDER = ["portfolio", "projects", "blog-posts", "other-pages", "unmatched"]
NOISE_TITLES = {
    "мои твиты",
    "the domain is expired",
    "этот домен продается",
}
NOISE_TITLE_PARTS = (
    "hello world",
    "общее —",
    "без рубрики",
    "uncategorized",
)
NOISE_SOURCE_PARTS = (
    "/category/",
    "/tag/",
    "/comments/",
)
LINE_NOISE = {
    "главная",
    "компания",
    "услуги",
    "контакты",
    "проекты",
    "новости",
    "pricing",
    "features",
    "demo",
    "вверх",
    "купить",
    "подробнее",
    "возврат к списку",
    "написать нам",
}
HIGHLIGHT_CATEGORIES = {"portfolio", "projects"}
NOTES_CATEGORIES = {"blog-posts", "other-pages"}


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.netloc or "").replace(":80", "")
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{host}{path}{query}"


def collapse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(value: str) -> str:
    return collapse_text(value).casefold()


def is_noise_title(title: str) -> bool:
    lowered = normalize_title(title)
    return lowered in NOISE_TITLES or any(part in lowered for part in NOISE_TITLE_PARTS)


def is_noise_source(source_url: str) -> bool:
    lowered = (source_url or "").casefold()
    return any(part in lowered for part in NOISE_SOURCE_PARTS)


def format_date(timestamp: str) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").strftime("%d.%m.%Y")
    except ValueError:
        return timestamp


def parse_markdown(text: str) -> str:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    rendered: list[str] = []
    for block in blocks:
        stripped = [line.strip() for line in block]
        if len(stripped) == 1 and stripped[0].startswith("# "):
            rendered.append(f"<h3>{escape(stripped[0][2:].strip())}</h3>")
            continue
        if all(line.startswith(("- ", "* ")) for line in stripped):
            items = "".join(f"<li>{escape(line[2:].strip())}</li>" for line in stripped)
            rendered.append(f"<ul>{items}</ul>")
            continue
        numbered = []
        numbered_match = True
        for line in stripped:
            match = re.match(r"^(\d+)[\.)]\s+(.*)$", line)
            if not match:
                numbered_match = False
                break
            numbered.append(match.group(2).strip())
        if numbered_match:
            items = "".join(f"<li>{escape(item)}</li>" for item in numbered)
            rendered.append(f"<ol>{items}</ol>")
            continue
        paragraph = "<br>".join(escape(line) for line in stripped)
        rendered.append(f"<p>{paragraph}</p>")
    return "\n".join(rendered)


def clean_text(text: str) -> str:
    cleaned: list[str] = []
    previous = ""
    for raw_line in text.splitlines():
        line = collapse_text(raw_line)
        lowered = line.casefold()
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue
        if lowered in LINE_NOISE:
            continue
        if re.fullmatch(r"[+()\\d\\s-]{7,}", line):
            continue
        if "@" in line and "." in line:
            continue
        if lowered.startswith(("©", "copyright", "звоните:", "онлайн заявка")):
            continue
        if line == previous:
            continue
        cleaned.append(line)
        previous = line
    return "\n".join(cleaned).strip()


def build_excerpt(text: str, fallback: str) -> str:
    candidates = [collapse_text(block) for block in text.split("\n\n") if collapse_text(block)]
    for candidate in candidates:
        if candidate.startswith("# "):
            continue
        if len(candidate) < 40:
            continue
        return candidate[:240].rstrip(" ,.;:") + ("…" if len(candidate) > 240 else "")
    fallback = collapse_text(fallback)
    return fallback[:180].rstrip(" ,.;:") + ("…" if len(fallback) > 180 else "")


def best_preview(meta: dict) -> Path | None:
    for image in meta.get("images", []):
        saved_path = image.get("saved_path")
        if not saved_path:
            continue
        candidate = ROOT / saved_path
        if candidate.exists():
            return candidate
    return None


def score_item(item: dict) -> tuple[int, int, str]:
    return (
        len(item["text"]),
        1 if item.get("preview_source") else 0,
        item.get("timestamp", ""),
    )


def load_items() -> list[dict]:
    items: list[dict] = []
    for base in (ROOT / "recovered", ROOT / "recovered_lj"):
        for metadata_path in sorted(base.rglob("metadata.json")):
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            category = meta.get("category") or metadata_path.parent.parent.name
            text_path = ROOT / meta["text_path"]
            raw_text = text_path.read_text(encoding="utf-8").strip() if text_path.exists() else ""
            text = clean_text(raw_text)
            preview = best_preview(meta)
            items.append(
                {
                    "id": meta["id"],
                    "title": meta.get("title") or metadata_path.parent.name,
                    "category": category,
                    "category_label": CATEGORY_LABELS.get(category, category),
                    "category_description": CATEGORY_DESCRIPTIONS.get(category, ""),
                    "timestamp": meta.get("timestamp", ""),
                    "display_date": format_date(meta.get("timestamp", "")),
                    "year": (meta.get("timestamp", "") or "")[:4],
                    "source_url": meta.get("source_url", ""),
                    "archive_url": meta.get("archive_url", ""),
                    "source_key": normalize_url(meta.get("source_url", "")),
                    "text": text,
                    "excerpt": build_excerpt(text, meta.get("title") or metadata_path.parent.name),
                    "preview_source": preview,
                    "image_count": sum(1 for image in meta.get("images", []) if (ROOT / image.get("saved_path", "")).exists()),
                    "notes": meta.get("notes") or {},
                }
            )
    deduped: dict[tuple[str, str], dict] = {}
    for item in items:
        key = (item["category"], item["source_key"] or item["id"])
        current = deduped.get(key)
        if current is None or score_item(item) > score_item(current):
            deduped[key] = item
    return sorted(deduped.values(), key=lambda item: item.get("timestamp", ""), reverse=True)


def copy_preview(item: dict) -> str:
    source: Path | None = item.get("preview_source")
    if not source:
        return ""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    extension = source.suffix.lower() or ".img"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", item["id"]).strip("-") or "preview"
    target = MEDIA_DIR / f"{safe_name}{extension}"
    shutil.copy2(source, target)
    return f"media/{target.name}"


def choose_unique(items: Iterable[dict], limit: int) -> list[dict]:
    selected: list[dict] = []
    seen_titles: set[str] = set()
    for item in items:
        title_key = normalize_title(item["title"])
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def rank_highlight(item: dict) -> tuple[int, int, int, int, str]:
    category_weight = 3 if item["category"] == "portfolio" else 2 if item["category"] == "projects" else 1
    image_weight = 1 if item.get("preview_source") else 0
    text_weight = min(len(item["text"]), 12000)
    penalty = -1 if is_noise_source(item["source_url"]) else 0
    return (category_weight, image_weight, text_weight, penalty, item.get("timestamp", ""))


def rank_note(item: dict) -> tuple[int, int, int, str]:
    category_weight = 2 if item["category"] == "blog-posts" else 1
    image_weight = 1 if item.get("preview_source") else 0
    text_weight = min(len(item["text"]), 12000)
    return (category_weight, image_weight, text_weight, item.get("timestamp", ""))


def build_dataset(items: list[dict]) -> dict:
    category_counts = Counter(item["category"] for item in items)
    curated = [
        item
        for item in items
        if not is_noise_title(item["title"]) and not is_noise_source(item["source_url"])
    ]
    highlights = choose_unique(
        sorted((item for item in curated if item["category"] == "portfolio"), key=rank_highlight, reverse=True),
        4,
    ) + choose_unique(
        sorted((item for item in curated if item["category"] == "projects"), key=rank_highlight, reverse=True),
        4,
    )
    notes = choose_unique(
        sorted((item for item in curated if item["category"] == "blog-posts"), key=rank_note, reverse=True),
        4,
    ) + choose_unique(
        sorted((item for item in curated if item["category"] == "other-pages"), key=rank_note, reverse=True),
        2,
    )

    serialized_items = []
    for item in items:
        preview = copy_preview(item)
        serialized_items.append(
            {
                "id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "categoryLabel": item["category_label"],
                "categoryDescription": item["category_description"],
                "date": item["display_date"],
                "year": item["year"],
                "timestamp": item["timestamp"],
                "excerpt": item["excerpt"],
                "html": parse_markdown(item["text"]),
                "sourceUrl": item["source_url"],
                "archiveUrl": item["archive_url"],
                "previewImage": preview,
                "imageCount": item["image_count"],
                "isNoise": is_noise_title(item["title"]),
            }
        )

    ids = {item["id"] for item in highlights}
    note_ids = {item["id"] for item in notes}

    stats = {
        "total": len(serialized_items),
        "projects": category_counts.get("projects", 0),
        "portfolio": category_counts.get("portfolio", 0),
        "other": category_counts.get("other-pages", 0) + category_counts.get("unmatched", 0),
        "blog": category_counts.get("blog-posts", 0),
    }

    years = sorted({item["year"] for item in serialized_items if item["year"]})

    categories = [
        {
            "key": key,
            "label": CATEGORY_LABELS[key],
            "description": CATEGORY_DESCRIPTIONS[key],
            "count": category_counts.get(key, 0),
        }
        for key in CATEGORY_ORDER
        if category_counts.get(key, 0)
    ]

    return {
        "stats": stats,
        "years": {"start": years[0] if years else "", "end": years[-1] if years else ""},
        "categories": categories,
        "highlights": [item for item in serialized_items if item["id"] in ids],
        "notes": [item for item in serialized_items if item["id"] in note_ids],
        "items": serialized_items,
    }


INDEX_HTML = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Platerra Archive</title>
    <meta name="description" content="Архив проектов, портфолио и материалов Platerra, собранный из recovered-контента и метафайлов.">
    <link rel="stylesheet" href="styles.css">
  </head>
  <body>
    <div class="page-shell">
      <header class="hero">
        <div class="hero__eyebrow">Platerra Archive</div>
        <div class="hero__grid">
          <div>
            <h1>Статический архив проектов, внедрений и материалов Platerra</h1>
            <p class="hero__lead">Современный минималистичный сайт, собранный из recovered-контента, метафайлов и исторических снимков домена.</p>
          </div>
          <div class="hero__panel">
            <p>Внутри — проектные страницы, отраслевые кейсы, публикации и сервисные материалы в едином каталоге с поиском и фильтрами.</p>
            <nav class="hero__nav">
              <a href="#highlights">Проекты</a>
              <a href="#notes">Материалы</a>
              <a href="#catalog">Каталог</a>
            </nav>
          </div>
        </div>
        <div class="stats" id="stats"></div>
      </header>

      <main>
        <section class="section" id="collections">
          <div class="section__header">
            <div>
              <div class="section__eyebrow">Коллекции</div>
              <h2>Собранные направления</h2>
            </div>
            <p>Дедуплицированный каталог по recovered-папкам и архивным источникам.</p>
          </div>
          <div class="collections" id="collections-grid"></div>
        </section>

        <section class="section" id="highlights">
          <div class="section__header">
            <div>
              <div class="section__eyebrow">Портфолио</div>
              <h2>Ключевые проекты и внедрения</h2>
            </div>
            <p>Выборка наиболее содержательных проектных страниц и кейсов.</p>
          </div>
          <div class="card-grid" id="highlights-grid"></div>
        </section>

        <section class="section" id="notes">
          <div class="section__header">
            <div>
              <div class="section__eyebrow">Материалы</div>
              <h2>Публикации и дополнительные страницы</h2>
            </div>
            <p>Блоговые заметки, сервисные страницы и контекст вокруг продуктовой истории.</p>
          </div>
          <div class="card-grid card-grid--compact" id="notes-grid"></div>
        </section>

        <section class="section" id="catalog">
          <div class="section__header">
            <div>
              <div class="section__eyebrow">Архив</div>
              <h2>Полный каталог</h2>
            </div>
            <p>Поиск по названиям и описаниям, фильтрация по категориям, просмотр деталей каждого материала.</p>
          </div>
          <div class="toolbar">
            <label class="search-field">
              <span>Поиск</span>
              <input id="search-input" type="search" placeholder="Например: FORPAY, терминалы, ЖКХ">
            </label>
            <div class="filters" id="filter-buttons"></div>
          </div>
          <div class="catalog-meta" id="catalog-meta"></div>
          <div class="archive-grid" id="archive-grid"></div>
        </section>
      </main>
    </div>

    <aside class="drawer" id="drawer" aria-hidden="true">
      <button class="drawer__close" id="drawer-close" type="button" aria-label="Закрыть">×</button>
      <div class="drawer__content" id="drawer-content"></div>
    </aside>
    <div class="backdrop" id="backdrop" hidden></div>

    <script src="data/site-data.js"></script>
    <script src="app.js"></script>
  </body>
</html>
"""


STYLES_CSS = """:root {
  --bg: #f4f1eb;
  --surface: rgba(255, 255, 255, 0.72);
  --surface-strong: rgba(255, 255, 255, 0.92);
  --line: rgba(30, 24, 18, 0.08);
  --text: #1f1a16;
  --muted: #6b6257;
  --accent: #b85c38;
  --accent-soft: rgba(184, 92, 56, 0.12);
  --shadow: 0 24px 60px rgba(31, 26, 22, 0.08);
  --radius: 24px;
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
}

* {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(184, 92, 56, 0.14), transparent 24%),
    linear-gradient(180deg, #faf8f4 0%, var(--bg) 100%);
}

body.drawer-open {
  overflow: hidden;
}

img {
  max-width: 100%;
  display: block;
}

button,
input {
  font: inherit;
}

.page-shell {
  width: min(1200px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 64px;
}

.hero,
.section,
.drawer__content {
  backdrop-filter: blur(18px);
}

.hero,
.section {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 8px);
  box-shadow: var(--shadow);
}

.hero {
  padding: 28px;
}

.hero__eyebrow,
.section__eyebrow,
.meta-chip,
.archive-card__meta,
.card__meta {
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-size: 0.78rem;
}

.hero__grid,
.section__header {
  display: grid;
  gap: 24px;
}

.hero__grid {
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.9fr);
  align-items: end;
}

.hero h1,
.section h2,
.drawer h2 {
  margin: 0;
  font-weight: 600;
  line-height: 1.05;
}

.hero h1 {
  font-size: clamp(2.8rem, 6vw, 5.1rem);
  max-width: 10ch;
}

.hero__lead,
.section__header p,
.drawer p,
.archive-card p,
.card p,
.collection p {
  color: var(--muted);
  line-height: 1.6;
}

.hero__lead {
  margin: 20px 0 0;
  font-size: 1.05rem;
  max-width: 58ch;
}

.hero__panel {
  padding: 20px;
  border-radius: var(--radius);
  background: var(--surface-strong);
  border: 1px solid var(--line);
}

.hero__nav {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
}

.hero__nav a,
.filters button,
.archive-card button,
.card button,
.drawer__links a {
  text-decoration: none;
  border: 1px solid var(--line);
  background: transparent;
  color: inherit;
  border-radius: 999px;
  padding: 10px 14px;
  transition: 180ms ease;
  cursor: pointer;
}

.hero__nav a:hover,
.filters button:hover,
.archive-card button:hover,
.card button:hover,
.drawer__links a:hover {
  border-color: rgba(184, 92, 56, 0.24);
  background: var(--accent-soft);
}

.stats,
.collections,
.card-grid,
.archive-grid {
  display: grid;
  gap: 16px;
}

.stats {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 28px;
}

.stat,
.collection,
.card,
.archive-card,
.search-field,
.catalog-meta,
.drawer__hero {
  background: var(--surface-strong);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.stat,
.collection,
.card,
.archive-card,
.catalog-meta {
  padding: 18px;
}

.stat strong {
  display: block;
  font-size: 2rem;
  margin-bottom: 4px;
}

.section {
  margin-top: 18px;
  padding: 24px;
}

.section__header {
  grid-template-columns: minmax(0, 1fr) minmax(260px, 0.7fr);
  align-items: end;
  margin-bottom: 18px;
}

.collections {
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
}

.collection {
  min-height: 180px;
}

.collection strong {
  display: block;
  font-size: 2.1rem;
  margin: 18px 0 8px;
}

.card-grid {
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

.card-grid--compact {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.card,
.archive-card {
  display: grid;
  gap: 14px;
}

.card__cover,
.drawer__image {
  aspect-ratio: 16 / 10;
  border-radius: 18px;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(184, 92, 56, 0.18), rgba(31, 26, 22, 0.06));
}

.card__cover img,
.drawer__image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card h3,
.archive-card h3 {
  margin: 0;
  font-size: 1.15rem;
  line-height: 1.3;
}

.card__footer,
.archive-card__footer,
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.search-field {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  min-width: min(100%, 360px);
}

.search-field input {
  border: 0;
  outline: 0;
  background: transparent;
  padding: 0;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.filters button.is-active {
  background: var(--text);
  color: white;
  border-color: var(--text);
}

.catalog-meta {
  margin: 16px 0;
  color: var(--muted);
}

.archive-grid {
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
}

.archive-card {
  min-height: 100%;
}

.archive-card__meta,
.card__meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.drawer {
  position: fixed;
  inset: 24px 24px 24px auto;
  width: min(720px, calc(100vw - 32px));
  transform: translateX(calc(100% + 40px));
  transition: transform 220ms ease;
  z-index: 30;
}

.drawer.is-open {
  transform: translateX(0);
}

.drawer__close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--surface-strong);
  cursor: pointer;
}

.drawer__content {
  background: rgba(250, 248, 244, 0.96);
  border: 1px solid var(--line);
  border-radius: 28px;
  box-shadow: var(--shadow);
  padding: 22px;
  max-height: 100%;
  overflow: auto;
}

.drawer__hero {
  display: grid;
  gap: 16px;
  padding: 18px;
}

.drawer__links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.drawer__body {
  margin-top: 18px;
}

.drawer__body h3 {
  margin: 1.5em 0 0.5em;
}

.drawer__body p,
.drawer__body li {
  color: var(--muted);
  line-height: 1.72;
}

.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(31, 26, 22, 0.28);
  z-index: 20;
}

.empty-state {
  padding: 28px;
  text-align: center;
  color: var(--muted);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  background: rgba(255, 255, 255, 0.48);
}

@media (max-width: 960px) {
  .hero__grid,
  .section__header,
  .stats {
    grid-template-columns: 1fr;
  }

  .drawer {
    inset: auto 16px 16px 16px;
    width: auto;
  }
}

@media (max-width: 640px) {
  .page-shell {
    width: min(100% - 20px, 1200px);
    padding-top: 10px;
  }

  .hero,
  .section,
  .drawer__content {
    border-radius: 22px;
  }

  .hero,
  .section {
    padding: 18px;
  }

  .hero h1 {
    max-width: none;
  }
}
"""


APP_JS = """const data = window.PLATERRA_DATA;

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
"""


def write_site(dataset: dict) -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    DATA_DIR.mkdir(parents=True)
    MEDIA_DIR.mkdir(parents=True)

    (SITE_DIR / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (SITE_DIR / "styles.css").write_text(STYLES_CSS, encoding="utf-8")
    (SITE_DIR / "app.js").write_text(APP_JS, encoding="utf-8")
    (DATA_DIR / "site-data.js").write_text(
        "window.PLATERRA_DATA = " + json.dumps(dataset, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    items = load_items()
    dataset = build_dataset(items)
    write_site(dataset)
    print(f"Generated {SITE_DIR.relative_to(ROOT)} with {dataset['stats']['total']} items.")


if __name__ == "__main__":
    main()
