import time
import random
import logging
from datetime import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, REQUEST_TIMEOUT
from modules.cleanup import clean_text, cover_image, dedup_hash, parse_price, parse_surface
from modules.cities import from_url_slug

log = logging.getLogger(__name__)


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
