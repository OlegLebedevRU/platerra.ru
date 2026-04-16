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
from typing import Dict, List, Optional, Union
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


MAX_PAGE_ID_LENGTH = 120


@dataclass
class BlogPage:
    url: str
    title: str
    content: str
    timestamp: str
    image_urls: List[str]


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^a-z0-9а-яё/_-]+", "-", value)
    value = value.replace("/", "-")
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "page"


def extract_blog_page(html: str, url: str) -> Optional[BlogPage]:
    soup = BeautifulSoup(html, "html.parser")

    body_text = soup.get_text(" ", strip=True)
    if "Страница не найдена" in body_text:
        return None
    if any(blocked in body_text for blocked in ["Access Denied", "Blocked", "You don't have permission"]):
        return None

    title_elem = soup.find("h1", class_="aentry-post__title")
    if not title_elem:
        return None
    title_span = title_elem.find("span", class_="aentry-post__title-text")
    title = title_span.get_text(strip=True) if title_span else title_elem.get_text(strip=True)

    content_div = soup.find("div", class_="aentry-post__content")
    if not content_div:
        possible_divs = soup.find_all("div", attrs={"class": re.compile("content|entry|post", re.I)})
        for div in possible_divs:
            if len(div.get_text(strip=True)) > 100:
                content_div = div
                break
        if not content_div:
            return None

    content = content_div.get_text("\n", strip=True)
    if len(content) < 50:
        return None

    img_tags = content_div.find_all("img")
    image_urls = []
    for img in img_tags:
        src = img.get("src")
        if src:
            full_url = urljoin(url, src)
            image_urls.append(full_url)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return BlogPage(url=url, title=title, content=content, timestamp=timestamp, image_urls=image_urls)


def write_text(path: Path, title: str, text: str) -> None:
    content = f"# {title or 'Untitled'}\n\n{text}\n"
    path.write_text(content, encoding="utf-8")


def download_image(session: requests.Session, img_url: str, save_path: Path, timeout: tuple) -> bool:
    try:
        response = session.get(img_url, timeout=timeout)
        response.raise_for_status()
        if response.content:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(response.content)
            return True
    except Exception as e:
        print(f"❌ Failed to download image {img_url}: {e}", file=sys.stderr)
    return False


def generate_page_ids(config: Dict) -> List[int]:
    page_ids = set()
    ranges = config["livejournal_blog"]["page_ranges"]

    for item in ranges:
        if isinstance(item, int):
            page_ids.add(item)
        elif isinstance(item, str) and "-" in item:
            start_str, end_str = item.split("-")
            start, end = int(start_str.strip()), int(end_str.strip())
            page_ids.update(range(start, end + 1))
    return sorted(page_ids)


def download_blog_range(config: Dict, output_root: Path, dry_run: bool) -> List[Dict]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    session.verify = bool(config.get("verify_tls", True))

    base_url = "https://platerra.livejournal.com"
    timeout = (config.get("connect_timeout_seconds", 20), config.get("read_timeout_seconds", 20))
    delay = float(config.get("delay_seconds_between_pages", 0.5))

    entries = []
    seen_hashes = {}
    page_ids = generate_page_ids(config)

    for page_id in page_ids:
        url = f"{base_url}/{page_id}.html"
        try:
            response = session.get(url, timeout=timeout)
            status = response.status_code
            if status == 200:
                print(f"✅ 200 - OK: {url}", file=sys.stderr)
            elif status == 403:
                print(f"🚫 403 - Forbidden: {url}", file=sys.stderr)
            else:
                continue  # Пропускаем всё, кроме 200 и 403

            if status != 200:
                continue

            page = extract_blog_page(response.text, url)
            if not page:
                continue

            content_hash = hashlib.sha256(page.content.encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes[content_hash] = url

            category = "blog-posts"
            prefix = f"{category}-{page.timestamp}-"
            slug = slugify(page.title or f"post-{page_id}")
            max_slug_length = max(1, MAX_PAGE_ID_LENGTH - len(prefix))
            page_id_str = f"{prefix}{slug[:max_slug_length]}"

            page_dir = output_root / category / page_id_str
            images_dir = page_dir / "images"
            text_path = page_dir / "text.md"
            metadata_path = page_dir / "metadata.json"

            image_metadata = []
            if page.image_urls and not dry_run:
                images_dir.mkdir(parents=True, exist_ok=True)
                for i, img_url in enumerate(page.image_urls, start=1):
                    ext = Path(img_url).suffix
                    if not ext or len(ext) > 5:
                        ext = ".jpg"
                    img_path = images_dir / f"{i:03d}{ext}"
                    downloaded = download_image(session, img_url, img_path, timeout)
                    image_metadata.append({
                        "source_url": img_url,
                        "saved_path": str(img_path.as_posix()),
                        "downloaded": downloaded
                    })

            metadata = {
                "id": page_id_str,
                "source_url": url,
                "timestamp": page.timestamp,
                "title": page.title,
                "category": category,
                "content_hash": content_hash,
                "text_path": str(text_path.as_posix()),
                "metadata_path": str(metadata_path.as_posix()),
                "images": image_metadata,
                "notes": {
                    "source": "Direct scrape from platerra.livejournal.com"
                },
            }

            if not dry_run:
                page_dir.mkdir(parents=True, exist_ok=True)
                write_text(text_path, page.title, page.content)
                metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

            entries.append(metadata)

        except Exception as e:
            print(f"💥 Error processing {url}: {e}", file=sys.stderr)

        if delay > 0:
            time.sleep(delay)

    return entries


def save_manifest(entries: List[Dict], path: Path, domain: str, dry_run: bool) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": domain,
        "notes": {
            "deduplication": "Exact content hashing via SHA256.",
            "extraction_source": "Direct scraping from platerra.livejournal.com"
        },
        "pages": entries,
    }
    if dry_run:
        print(json.dumps({"dry_run_manifest_preview_count": len(entries)}, ensure_ascii=False))
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract blog posts from platerra.livejournal.com.")
    parser.add_argument("--config", required=True, type=Path, help="Path to JSON config file")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files, only show results")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        raise SystemExit(1)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    output_root = Path(config.get("output_root", "recovered_lj"))
    manifest_path = Path(config.get("manifest_output", "manifests/manifest.lj.json"))

    print(f"Scraping LiveJournal blog with specified pages and ranges...", file=sys.stderr)
    entries = download_blog_range(config, output_root, args.dry_run)
    save_manifest(entries, manifest_path, "platerra.livejournal.com", args.dry_run)

    print(f"✅ Scraping completed. Saved blog posts: {len(entries)}")
    if not args.dry_run:
        print(f"📄 Manifest saved: {manifest_path.as_posix()}")


if __name__ == "__main__":
    main()