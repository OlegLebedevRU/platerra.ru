#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


@dataclass
class Snapshot:
    timestamp: str
    original_url: str


def load_config(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9а-яё/_-]+", "-", value)
    value = value.replace("/", "-")
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "page"


def archive_url(timestamp: str, original_url: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/{original_url}"


def list_snapshots(session: requests.Session, config: Dict) -> List[Snapshot]:
    endpoint = config.get("wayback", {}).get("cdx_endpoint", "https://web.archive.org/cdx/search/cdx")
    collapse = config.get("wayback", {}).get("collapse", "digest")
    domain = config["domain"]
    params = {
        "url": f"*.{domain}/*",
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode",
        "filter": ["statuscode:200", "mimetype:text/html"],
        "collapse": collapse,
    }
    response = session.get(endpoint, params=params, timeout=config.get("request_timeout_seconds", 20))
    response.raise_for_status()
    data = response.json()
    rows = data[1:] if data and isinstance(data[0], list) else data
    snapshots: List[Snapshot] = []
    seen: set[Tuple[str, str]] = set()
    for row in rows:
        if len(row) < 2:
            continue
        timestamp, original = row[0], row[1]
        key = (timestamp, original)
        if key in seen:
            continue
        seen.add(key)
        snapshots.append(Snapshot(timestamp=timestamp, original_url=original))
    return snapshots


def extract_main_text(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "form"]):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = "\n\n".join(lines)
    return title, cleaned


def classify_page(url: str, title: str, text: str) -> str:
    u = url.lower()
    t = (title + " " + text[:500]).lower()
    if any(token in u for token in ["/project", "/portfolio", "/works"]):
        return "projects" if "/project" in u or "/works" in u else "portfolio"
    if any(token in t for token in ["проект", "портфолио", "case", "кейс"]):
        return "projects" if "проект" in t or "case" in t or "кейс" in t else "portfolio"
    if len(text) > 200:
        return "other-pages"
    return "unmatched"


def find_image_urls(html: str, base_url: str, domain: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        full = urljoin(base_url, src)
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        if domain not in parsed.netloc:
            continue
        urls.append(full)

    deduped: List[str] = []
    seen = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)
    return deduped


def write_text(path: Path, title: str, text: str) -> None:
    content = f"# {title or 'Untitled'}\n\n{text}\n"
    path.write_text(content, encoding="utf-8")


def download_image(
    session: requests.Session,
    image_url: str,
    timestamp: str,
    destination: Path,
    timeout: int,
) -> Tuple[str, bool]:
    arch_url = archive_url(timestamp, image_url)
    try:
        r = session.get(arch_url, timeout=timeout)
        r.raise_for_status()
        if not r.content:
            return arch_url, False
        destination.write_bytes(r.content)
        return arch_url, True
    except requests.RequestException:
        return arch_url, False


def process_snapshot(
    session: requests.Session,
    snapshot: Snapshot,
    config: Dict,
    output_root: Path,
    seen_hashes: Dict[str, str],
    dry_run: bool,
) -> Optional[Dict]:
    timeout = config.get("request_timeout_seconds", 20)
    domain = config["domain"]

    page_archive_url = archive_url(snapshot.timestamp, snapshot.original_url)
    try:
        response = session.get(page_archive_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return None

    html = response.text
    title, text = extract_main_text(html)
    if not text.strip():
        return None

    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if content_hash in seen_hashes:
        return None
    seen_hashes[content_hash] = snapshot.original_url

    category = classify_page(snapshot.original_url, title, text)
    slug = slugify(urlparse(snapshot.original_url).path or snapshot.original_url)
    page_id = f"{category}-{snapshot.timestamp}-{slug}"[:120]

    page_dir = output_root / category / page_id
    text_path = page_dir / "text.md"
    metadata_path = page_dir / "metadata.json"
    images_dir = page_dir / "images"

    image_urls = find_image_urls(html, snapshot.original_url, domain)
    max_images = config.get("max_images_per_page", 15)

    images_meta = []
    if not dry_run:
        images_dir.mkdir(parents=True, exist_ok=True)

    for idx, image_url in enumerate(image_urls[:max_images], start=1):
        ext = Path(urlparse(image_url).path).suffix.lower()
        if not ext or len(ext) > 5:
            ext = ".jpg"
        filename = f"{idx:03d}{ext}"
        saved_path = images_dir / filename

        downloaded = False
        img_archive_url = archive_url(snapshot.timestamp, image_url)
        if not dry_run:
            img_archive_url, downloaded = download_image(session, image_url, snapshot.timestamp, saved_path, timeout)

        images_meta.append(
            {
                "source_url": image_url,
                "archive_url": img_archive_url,
                "saved_path": str(saved_path.as_posix()),
                "downloaded": downloaded,
            }
        )

    metadata = {
        "id": page_id,
        "source_url": snapshot.original_url,
        "archive_url": page_archive_url,
        "timestamp": snapshot.timestamp,
        "title": title,
        "category": category,
        "content_hash": content_hash,
        "text_path": str(text_path.as_posix()),
        "metadata_path": str(metadata_path.as_posix()),
        "images": images_meta,
        "notes": {
            "deduplication": "Exact text hash only; near-duplicate logic planned.",
            "classification": "Rule-based URL/title/text heuristics; manual refinement planned.",
        },
    }

    if not dry_run:
        page_dir.mkdir(parents=True, exist_ok=True)
        write_text(text_path, title, text)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return metadata


def save_manifest(config: Dict, entries: List[Dict], path: Path, domain: str, dry_run: bool) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": domain,
        "notes": {
            "deduplication": "Current implementation uses exact text hashing. Future improvement: semantic dedup + temporal grouping.",
            "classification": "Current implementation is rule-based. Future improvement: stronger heuristics and optional manual QA layer.",
        },
        "pages": entries,
    }
    if dry_run:
        print(json.dumps({"dry_run_manifest_preview_count": len(entries)}, ensure_ascii=False))
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract archived platerra.ru text and images from Wayback snapshots.")
    parser.add_argument("--config", required=True, type=Path, help="Path to JSON config file")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of snapshots to process")
    parser.add_argument("--dry-run", action="store_true", help="Do not write recovered files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    session = requests.Session()
    session.headers.update({"User-Agent": config.get("user_agent", "platerra-archive-extractor/0.1")})

    try:
        snapshots = list_snapshots(session, config)
    except requests.RequestException as exc:
        print(f"Failed to enumerate snapshots from Wayback CDX API: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if args.limit is not None:
        snapshots = snapshots[: args.limit]

    output_root = Path(config.get("output_root", "recovered"))
    manifest_path = Path(config.get("manifest_output", "manifests/manifest.latest.json"))
    domain = config["domain"]

    entries: List[Dict] = []
    seen_hashes: Dict[str, str] = {}
    delay = float(config.get("delay_seconds_between_pages", 0.0))

    for snapshot in snapshots:
        entry = process_snapshot(session, snapshot, config, output_root, seen_hashes, args.dry_run)
        if entry:
            entries.append(entry)
        if delay > 0:
            time.sleep(delay)

    save_manifest(config, entries, manifest_path, domain, args.dry_run)
    print(f"Processed snapshots: {len(snapshots)}")
    print(f"Saved pages: {len(entries)}")
    if not args.dry_run:
        print(f"Manifest: {manifest_path.as_posix()}")


if __name__ == "__main__":
    main()
