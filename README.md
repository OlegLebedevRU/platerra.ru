# Platerra — корпоративный сайт и архив проектов

Актуальный сайт находится в `website/`: статический Node-генератор, локальные
изображения, шесть страниц. Архив в `recovered/`, `recovered_lj/` и `site/`
сохранён как источник материалов и не является публикуемым сайтом.

```powershell
cd website
npm run build
npm run check
```

Размещение: `deploy/compose.yml`, виртуальные хосты и сертификаты через
существующий nginx L4Desk. Инструкция и проверки: [deploy/README.md](deploy/README.md).
Сертификаты и ключи из локального `.env` исключены из Git.

---

# platerra.ru archive extraction workspace

This repository is the working area for recovering historical content from archived copies of `platerra.ru`.

## Scope

Recovery target:
- page texts
- related images
- per-page metadata

Out of scope:
- CSS/JS restoration
- full visual reconstruction of the old site

The extracted corpus is prepared for the next step: building a historical project catalog.

## Repository layout

```text
config/
  sample_config.json            # editable run configuration example
manifests/
  manifest.schema.json          # schema for extractor output manifest
  manifest.example.json         # example manifest instance
recovered/
  projects/                     # extracted project-like pages
  portfolio/                    # extracted portfolio-like pages
  other-pages/                  # extracted content pages that are not projects/portfolio
  unmatched/                    # extracted pages with unclear classification
scripts/
  extract_wayback_content.py    # initial extraction script
requirements.txt
```

Each extracted page is stored in a folder with:
- `text.md` — cleaned page text
- `metadata.json` — source URL, archive URL, timestamp, title, image links, classification, notes
- `images/` — downloaded related images

## Quick start

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy and adjust config:

```bash
cp config/sample_config.json config/local_config.json
```

4. Run extractor:

```bash
python scripts/extract_wayback_content.py --config config/local_config.json
```

Optional flags:
- `--limit N` — process only first N snapshots
- `--dry-run` — enumerate/fetch/parse without writing recovered files

## Notes for next iterations

- Deduplication currently uses lightweight content hashing and snapshot grouping; stronger semantic dedup should be added later.
- Classification is rule-based (`projects`, `portfolio`, `other-pages`, `unmatched`) and should be improved with richer heuristics.
- Manifest keeps source traceability (`source_url`, `archive_url`, `timestamp`) to support transparent auditing.

## Static site

The repository now includes a generated static archive in `site/`.

To rebuild it from the current recovered corpus:

```bash
python scripts/build_static_site.py
```

The generator deduplicates items by source URL, creates a searchable catalog, and copies available preview images into `site/media/`.
