"""
Product image scraper — reads a categorized item-list spreadsheet and
downloads one product image per item into category-wise folders.

USAGE
-----
    # Test run first — 10 items from two categories, see the README before a full run
    python main.py --limit 10 --categories "Snacks" "Dairy"

    # Full run across every category sheet
    python main.py

    # Re-running is safe: already-downloaded items are skipped automatically
    # (tracked in output/_progress.csv). Just run the same command again.

OUTPUT
------
    output/
        _progress.csv              <- one row per attempted item (resume log)
        Snacks/
            Banana Chips_001675.jpg
            ...
        Dairy/
            Amul Butter_002772.jpg
            ...

See README.md for setup, rate-limiting notes, and troubleshooting.
"""
import argparse
import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

import config
from scrapers import flipkart, amazon, bing_images
from scrapers.matching import ranked_candidates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SOURCE_FUNCTIONS = {
    "flipkart": flipkart.search_candidates,
    "amazon": amazon.search_candidates,
    "bing": bing_images.search_candidates,
}

PROGRESS_HEADER = ["barcode", "category", "item", "status", "source", "match_score", "matched_title", "file", "error"]

INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    cleaned = "".join(c for c in str(name) if c not in INVALID_FILENAME_CHARS)
    cleaned = " ".join(cleaned.split())  # collapse whitespace
    cleaned = cleaned.strip(" .")  # trailing dot/space breaks on Windows
    return cleaned[:maxlen] if cleaned else "unnamed_item"


def load_completed_barcodes(progress_path: Path) -> set:
    done = set()
    if progress_path.exists():
        with open(progress_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "success":
                    done.add(row["barcode"])
    return done


def append_progress(progress_path: Path, row: dict):
    write_header = not progress_path.exists()
    with open(progress_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROGRESS_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def download_image(url: str, dest_no_ext: Path, referer: str = None) -> Path:
    headers = {"User-Agent": config.USER_AGENTS[0]}
    if referer:
        headers["Referer"] = referer

    resp = requests.get(url, headers=headers, timeout=config.TIMEOUT, stream=True, allow_redirects=True)
    resp.raise_for_status()

    data = resp.content
    if len(data) < config.MIN_IMAGE_BYTES:
        raise ValueError(f"Image too small ({len(data)} bytes) — likely a placeholder/icon")

    # Trust actual file bytes over the Content-Type header — some CDNs omit
    # it or send a generic "application/octet-stream", which would otherwise
    # cause a perfectly good image to be rejected.
    content_type = resp.headers.get("Content-Type", "")
    ext = _sniff_extension(data) or _extension_from_content_type(content_type)
    if not ext:
        raise ValueError(f"Response doesn't look like an image (Content-Type: {content_type or 'none'})")

    dest = dest_no_ext.with_suffix(ext)
    dest.write_bytes(data)
    return dest


def _sniff_extension(data: bytes):
    """Identify common image formats from their file signature (magic bytes)."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    return None


def _extension_from_content_type(content_type: str):
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "gif" in content_type:
        return ".gif"
    return None


def process_item(category: str, item_name: str, barcode: str, cat_dir: Path, delay: float) -> dict:
    """
    Tries each source in order. For each source, fetches several candidate
    images (not just the first result), ranks every candidate that passes
    matching.py's brand + keyword checks, and attempts to download the
    top few in score order — falling through to the next candidate if one
    fails to download (dead link, hotlink-blocked, etc.) before giving up on
    that source entirely. Only moves to the next source if nothing from this
    one both matched AND downloaded successfully.
    """
    safe_name = sanitize_filename(item_name)
    dest_stub = cat_dir / f"{safe_name}_{barcode}"
    last_error = "no confidently-matching image found from any source"

    for source in config.SOURCES_ORDER:
        search_fn = SOURCE_FUNCTIONS[source]
        candidates = []
        for attempt in range(config.MAX_RETRIES):
            try:
                candidates = search_fn(item_name)
                break
            except Exception as e:
                last_error = f"[{source}] search failed: {e}"
                log.debug(f"[{source}] attempt {attempt + 1} failed for '{item_name}': {e}")
                time.sleep(delay)

        if not candidates:
            time.sleep(delay)
            continue

        ranked = ranked_candidates(item_name, candidates, category=category, min_score=config.MIN_MATCH_SCORE)
        if not ranked:
            log.debug(f"[{source}] {len(candidates)} candidate(s) for '{item_name}' but none passed matching")
            time.sleep(delay)
            continue

        referer = config.REFERERS.get(source)
        for image_url, matched_title, score in ranked[:config.MAX_DOWNLOAD_ATTEMPTS_PER_SOURCE]:
            try:
                saved_path = download_image(image_url, dest_stub, referer=referer)
                return {
                    "barcode": barcode, "category": category, "item": item_name,
                    "status": "success", "source": source,
                    "match_score": f"{score:.2f}", "matched_title": matched_title,
                    "file": str(saved_path), "error": "",
                }
            except Exception as e:
                last_error = f"[{source}] download failed: {e}"
                log.debug(f"[{source}] download failed for '{item_name}' ({image_url}): {e}")

        time.sleep(delay)

    return {
        "barcode": barcode, "category": category, "item": item_name,
        "status": "failed", "source": "", "match_score": "", "matched_title": "",
        "file": "", "error": last_error,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default=config.INPUT_XLSX, help="Path to the source .xlsx")
    parser.add_argument("--output", default=config.OUTPUT_DIR, help="Output root folder")
    parser.add_argument("--categories", nargs="*", default=None, help="Only process these sheet/category names")
    parser.add_argument("--limit", type=int, default=None, help="Max items per category (for test runs)")
    parser.add_argument("--delay", type=float, default=config.REQUEST_DELAY, help="Seconds between requests")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (keep low to avoid bans)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        return

    out_root = Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)
    progress_path = out_root / "_progress.csv"
    completed = load_completed_barcodes(progress_path)
    log.info(f"{len(completed)} items already completed previously — will be skipped")

    xls = pd.ExcelFile(input_path)
    sheets = [s for s in xls.sheet_names if s not in config.SKIP_SHEETS]
    if args.categories:
        wanted = set(args.categories)
        sheets = [s for s in sheets if s in wanted]

    tasks = []
    for sheet in sheets:
        df = pd.read_excel(xls, sheet_name=sheet)
        cat_dir = out_root / sanitize_filename(sheet)
        cat_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for _, row in df.iterrows():
            if args.limit is not None and count >= args.limit:
                break
            barcode = str(row.get("Barcode", "")).strip()
            item_name = str(row.get("Item Description", "")).strip()
            if not item_name or item_name.lower() == "nan":
                continue
            if barcode in completed:
                continue
            tasks.append((sheet, item_name, barcode, cat_dir))
            count += 1

    log.info(f"{len(tasks)} items queued across {len(sheets)} categories")

    def _log_result(result):
        score_note = f", score {result['match_score']}" if result.get("match_score") else ""
        log.info(
            f"[{result['status'].upper()}] {result['category']} / {result['item']} "
            f"({result['source'] or 'none'}{score_note})"
        )

    if args.workers <= 1:
        for category, item_name, barcode, cat_dir in tasks:
            result = process_item(category, item_name, barcode, cat_dir, args.delay)
            append_progress(progress_path, result)
            _log_result(result)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(process_item, category, item_name, barcode, cat_dir, args.delay): item_name
                for category, item_name, barcode, cat_dir in tasks
            }
            for future in as_completed(futures):
                result = future.result()
                append_progress(progress_path, result)
                _log_result(result)

    log.info(f"Done. Progress log: {progress_path}")


if __name__ == "__main__":
    main()
