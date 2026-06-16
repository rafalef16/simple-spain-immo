import re
import shelve
import time
import random
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, REQUEST_TIMEOUT
from modules.cleanup import clean_text, cover_image, dedup_hash, parse_price, parse_surface
from modules.cities import from_url_slug

log = logging.getLogger(__name__)

EXCLUDE_URL_PATTERNS = re.compile(
    r'/(login|register|contact|about|blog|news|ayuda|help|faq|legal|cookies|privacy|'
    r'sitemap|404|error|auth|account|user|admin|search\?|tag/|category/)',
    re.IGNORECASE,
)

_CACHE_PATH = str(Path(__file__).parent.parent / "data" / ".url_cache")
_CACHE_TTL = 3600 * 6  # 6 hours


def pre_filter_urls(urls: list[str]) -> list[str]:
    """Remove URLs matching noise patterns before HTTP fetch."""
    return [u for u in urls if not EXCLUDE_URL_PATTERNS.search(u)]


def fetch_html_cached(
    url: str,
    session: Optional[requests.Session] = None,
    ttl: int = _CACHE_TTL,
) -> Optional[str]:
    """Fetch with shelve-based ETag/content cache. Returns None on HTTP error."""
    key = hashlib.md5(url.encode()).hexdigest()
    now = time.time()

    try:
        with shelve.open(_CACHE_PATH) as db:
            entry = db.get(key)
            if entry and (now - entry.get("ts", 0)) < ttl:
                return entry["html"]
    except Exception:
        pass

    html = fetch_html(url, session)
    if html:
        try:
            with shelve.open(_CACHE_PATH) as db:
                db[key] = {"html": html, "ts": now}
        except Exception:
            pass
    return html


EMPTY_LISTING = {
    "id": None,
    "url": None,
    "site": None,
    "site_family": None,
    "type": None,
    "title": None,
    "prix_eur": None,
    "prix_display": None,
    "ville": None,
    "ville_canonical": None,
    "terrain_m2": None,
    "construction_m2": None,
    "description_raw": None,
    "description_clean": None,
    "cover_image_url": None,
    "photos": [],
    "ref": None,
    "scrap_timestamp": None,
    "valide": True,
}


def new_listing(**kwargs) -> dict:
    item = EMPTY_LISTING.copy()
    item["scrap_timestamp"] = datetime.utcnow().isoformat()
    item.update(kwargs)
    if item.get("url") and item.get("description_clean") is not None:
        item["id"] = dedup_hash(item["url"], item["description_clean"])
    return item


def fetch_html(url: str, session: Optional[requests.Session] = None, retries: int = 3) -> Optional[str]:
    s = session or requests.Session()
    s.headers.update(HEADERS)
    for attempt in range(retries):
        try:
            resp = s.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            elif resp.status_code == 404:
                log.debug("404 %s", url)
                return None
            log.warning("HTTP %d for %s (attempt %d)", resp.status_code, url, attempt + 1)
        except Exception as e:
            log.warning("Fetch error %s: %s", url, e)
        time.sleep(random.uniform(2, 5))
    return None


def human_delay():
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")
