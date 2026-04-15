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
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MAX_PAGE_ID_LENGTH = 120
DEDUPLICATION_NOTE = "Current implementation uses exact text hashing. Future improvement: semantic dedup + temporal grouping."
CLASSIFICATION_NOTE = "Current implementation is rule-based. Future improvement: stronger heuristics and optional manual QA layer."


@dataclass
class Snapshot:
    timestamp: str
    original_url: str


class WaybackEnumerationError(RuntimeError):
    pass


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


def request_timeout(config: Dict) -> Tuple[int, int]:
    base_timeout = int(config.get("request_timeout_seconds", 20))
    connect_timeout = int(config.get("connect_timeout_seconds", base_timeout))
    read_timeout = int(config.get("read_timeout_seconds", base_timeout))
    return connect_timeout, read_timeout


def cdx_request_timeout(config: Dict) -> Tuple[int, int]:
    wayback_cfg = config.get("wayback", {})
    connect_timeout, read_timeout = request_timeout(config)
    cdx_timeout = int(wayback_cfg.get("request_timeout_seconds", max(read_timeout, 60)))
    cdx_connect_timeout = int(wayback_cfg.get("connect_timeout_seconds", connect_timeout))
    cdx_read_timeout = int(wayback_cfg.get("read_timeout_seconds", cdx_timeout))
    return cdx_connect_timeout, cdx_read_timeout


def get_json_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: Dict,
    timeout: Tuple[int, int],
    attempts: int,
    backoff_seconds: float,
) -> List:
    last_error: Optional[requests.RequestException] = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise WaybackEnumerationError(f"Unexpected CDX response type from {url}: {type(data).__name__}")
            return data
        except ValueError as exc:
            raise WaybackEnumerationError(f"Failed to decode CDX JSON response from {url}: {exc}") from exc
        except requests.HTTPError:
            raise
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.SSLError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(backoff_seconds * attempt)

    assert last_error is not None
    raise last_error


def resolve_cdx_endpoints(config: Dict) -> List[str]:
    wayback_cfg = config.get("wayback", {})
    endpoints = wayback_cfg.get("cdx_endpoints") or [wayback_cfg.get("cdx_endpoint", "https://web.archive.org/cdx/search/cdx")]
    cleaned: List[str] = []
    seen: Set[str] = set()
    for endpoint in endpoints:
        if not endpoint:
            continue
        endpoint = str(endpoint).strip()
        if not endpoint or endpoint in seen:
            continue
        seen.add(endpoint)
        cleaned.append(endpoint)
    return cleaned or ["https://web.archive.org/cdx/search/cdx"]


def cdx_base_params(config: Dict) -> Dict:
    wayback_cfg = config.get("wayback", {})
    return {
        "url": f"*.{config['domain']}/*",
        "output": "json",
        "fl": "timestamp,original,mimetype,statuscode",
        "filter": ["statuscode:200", "mimetype:text/html"],
        "collapse": wayback_cfg.get("collapse", "digest"),
    }


def parse_cdx_rows(data: List) -> List[Snapshot]:
    rows = data
    if data and isinstance(data[0], list):
        first_cell = str(data[0][0]).lower() if data[0] else ""
        if first_cell == "timestamp":
            rows = data[1:]
    snapshots: List[Snapshot] = []
    seen: Set[Tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        timestamp, original = row[0], row[1]
        key = (timestamp, original)
        if key in seen:
            continue
        seen.add(key)
        snapshots.append(Snapshot(timestamp=timestamp, original_url=original))
    return snapshots


def enumerate_years(config: Dict) -> List[int]:
    wayback_cfg = config.get("wayback", {})
    current_year = datetime.now(timezone.utc).year
    start_year = int(wayback_cfg.get("year_start", 1996))
    end_year = int(wayback_cfg.get("year_end", current_year))
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    return list(range(start_year, end_year + 1))


def list_snapshots(session: requests.Session, config: Dict) -> List[Snapshot]:
    wayback_cfg = config.get("wayback", {})
    attempts = max(1, int(wayback_cfg.get("retries", 3)))
    backoff_seconds = float(wayback_cfg.get("retry_backoff_seconds", 2.0))
    timeout = cdx_request_timeout(config)
    params = cdx_base_params(config)
    endpoints = resolve_cdx_endpoints(config)
    bulk_errors: List[str] = []

    for endpoint in endpoints:
        try:
            data = get_json_with_retries(
                session,
                endpoint,
                params=params,
                timeout=timeout,
                attempts=attempts,
                backoff_seconds=backoff_seconds,
            )
            return parse_cdx_rows(data)
        except (WaybackEnumerationError, requests.RequestException) as exc:
            bulk_errors.append(f"{endpoint}: {exc}")

    if not wayback_cfg.get("segment_by_year_on_error", True):
        raise WaybackEnumerationError(" | ".join(bulk_errors))

    snapshots: List[Snapshot] = []
    segmented_errors: List[str] = []

    for year in enumerate_years(config):
        year_params = dict(params)
        year_params["from"] = str(year)
        year_params["to"] = str(year)
        year_error: Optional[str] = None

        for endpoint in endpoints:
            try:
                data = get_json_with_retries(
                    session,
                    endpoint,
                    params=year_params,
                    timeout=timeout,
                    attempts=attempts,
                    backoff_seconds=backoff_seconds,
                )
                snapshots.extend(parse_cdx_rows(data))
                year_error = None
                break
            except (WaybackEnumerationError, requests.RequestException) as exc:
                year_error = f"{year} via {endpoint}: {exc}"

        if year_error:
            segmented_errors.append(year_error)

    deduped = parse_cdx_rows([[s.timestamp, s.original_url] for s in snapshots])
    if deduped:
        if segmented_errors:
            print(
                f"Warning: some yearly CDX requests failed, but enumeration still recovered {len(deduped)} snapshots.",
                file=sys.stderr,
            )
        return deduped

    message = [
        "Wayback CDX enumeration failed.",
        "Bulk attempts:",
        *[f"- {error}" for error in bulk_errors],
        "Yearly fallback attempts:",
        *[f"- {error}" for error in segmented_errors],
        "Consider increasing wayback.request_timeout_seconds or providing alternative wayback.cdx_endpoints in the config.",
    ]
    raise WaybackEnumerationError("\n".join(message))


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
    if "/project" in u or "/works" in u:
        return "projects"
    if "/portfolio" in u:
        return "portfolio"
    if "проект" in t or "case" in t or "кейс" in t:
        return "projects"
    if "портфолио" in t:
        return "portfolio"
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
    timeout: Tuple[int, int],
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
    timeout = request_timeout(config)
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
    prefix = f"{category}-{snapshot.timestamp}-"
    max_slug_length = max(1, MAX_PAGE_ID_LENGTH - len(prefix))
    page_id = f"{prefix}{slug[:max_slug_length]}"

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
            "deduplication": DEDUPLICATION_NOTE,
            "classification": CLASSIFICATION_NOTE,
        },
    }

    if not dry_run:
        page_dir.mkdir(parents=True, exist_ok=True)
        write_text(text_path, title, text)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return metadata


def save_manifest(entries: List[Dict], path: Path, domain: str, dry_run: bool) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": domain,
        "notes": {
            "deduplication": DEDUPLICATION_NOTE,
            "classification": CLASSIFICATION_NOTE,
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
    session.verify = bool(config.get("verify_tls", True))

    try:
        snapshots = list_snapshots(session, config)
    except (WaybackEnumerationError, requests.RequestException) as exc:
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

    save_manifest(entries, manifest_path, domain, args.dry_run)
    print(f"Processed snapshots: {len(snapshots)}")
    print(f"Saved pages: {len(entries)}")
    if not args.dry_run:
        print(f"Manifest: {manifest_path.as_posix()}")


if __name__ == "__main__":
    main()
