"""
ThinkSpain scraper — uses __NEXT_DATA__ JSON embedded in HTML pages.
EVOMI residential proxy (same as Fotocasa/Idealista). Pagination via ?page=N.
"""
import json
import re
import logging
import time
import random
import requests

from config import SITES_THINKSPAIN, MAX_PAGES_PER_SITE, MAX_CONSECUTIVE_ERRORS, EVOMI_USER, EVOMI_PASS_BASE
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, dedup_hash, parse_price, parse_surface, is_solar_listing
from modules.cities import normalize
from scrapers.base import fetch_html, human_delay, new_listing, soup

log = logging.getLogger(__name__)
SITE = "thinkspain"


def _extract_next_data(html: str) -> dict | None:
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _parse_listing_urls(html: str) -> list[str]:
    """Extract property detail URLs from search result page."""
    urls = []

    # ThinkSpain is server-side rendered — extract /property-for-sale/NNNNNN links
    for href in re.findall(r'href=["\'](/property-for-sale/\d+)["\']', html):
        full = f"https://www.thinkspain.com{href}"
        if full not in urls:
            urls.append(full)

    # Fallback: __NEXT_DATA__ if ever added
    if not urls:
        data = _extract_next_data(html)
        if data:
            try:
                props = data["props"]["pageProps"]
                results = (
                    props.get("searchResults", {}).get("hits") or
                    props.get("properties") or []
                )
                for item in results:
                    ref = item.get("id") or item.get("ref") or item.get("propertyId")
                    if ref:
                        urls.append(f"https://www.thinkspain.com/property-for-sale/{ref}")
            except (KeyError, TypeError):
                pass

    return list(dict.fromkeys(urls))


def _scrape_detail(url: str, session: requests.Session, prop_type: str) -> dict | None:
    html = fetch_html(url, session)
    if not html:
        return None

    bs = soup(html)

    # Title
    title = ""
    for sel in ["h1.property-title", "h1[class*='title']", "h1"]:
        el = bs.select_one(sel)
        if el:
            title = clean_text(el.get_text())
            break

    # Price
    prix_raw = ""
    for sel in [".property-price", "[class*='price']", "[itemprop='price']"]:
        el = bs.select_one(sel)
        if el:
            prix_raw = clean_text(el.get_text())
            break

    # Try JSON-LD
    data = _extract_next_data(html)
    if data:
        try:
            p = data["props"]["pageProps"]["property"]
            title = title or p.get("title", "")
            if not prix_raw:
                prix_raw = str(p.get("price", ""))
        except (KeyError, TypeError):
            pass

    prix_eur, prix_display = parse_price(prix_raw)

    # Description
    desc = ""
    for sel in [".property-description", "[class*='description']", ".listing-description"]:
        el = bs.select_one(sel)
        if el:
            desc = clean_text(el.get_text())
            break

    if is_solar_listing(desc):
        log.debug("Skipping solar listing: %s", url)
        return None

    # Surfaces (cap at realistic limits to avoid grabbing price values)
    terrain_m2 = None
    construction_m2 = None
    for el in bs.select("[class*='feature'], [class*='detail'], li"):
        text = el.get_text()
        tl = text.lower()
        if any(w in tl for w in ["plot", "terreno", "parcela"]):
            v = parse_surface(text)
            if v and v < 9_999_999:
                terrain_m2 = v
        if any(w in tl for w in ["built", "construida", "habitable"]) and "plot" not in tl:
            v = parse_surface(text)
            if v and v < 99_999:
                construction_m2 = v

    # City
    ville = ""
    for sel in [".property-location", "[class*='location']", "[itemprop='addressLocality']"]:
        el = bs.select_one(sel)
        if el:
            ville = clean_text(el.get_text())
            break
    ville_canonical = normalize(ville)

    # Images
    img = cover_image(html, SITE)
    photos = list({src for img_tag in bs.select("img[src]") for src in [img_tag.get("src", "")] if "thinkspain" in src or "propertyimages" in src})

    listing = new_listing(
        url=url,
        site=SITE,
        site_family=SITE,
        type=prop_type,
        title=title,
        prix_eur=prix_eur,
        prix_display=prix_display or prix_raw,
        ville=ville,
        ville_canonical=ville_canonical,
        terrain_m2=terrain_m2,
        construction_m2=construction_m2,
        description_raw=desc,
        description_clean=desc,
        cover_image_url=img,
        photos=photos[:20],
    )

    return listing


def run(dry_run: bool = False, limit: int = 0) -> list[dict]:
    session = requests.Session()
    _proxy = f"http://{EVOMI_USER}:{EVOMI_PASS_BASE}@core-residential.evomi.com:1000"
    session.proxies = {"http": _proxy, "https": _proxy}
    results = []

    for site_config in SITES_THINKSPAIN:
        name = site_config["name"]
        base_url = site_config["url"]
        prop_type = site_config["type"]

        processed = load_processed_urls(name)
        log.info("[ThinkSpain] %s — starting", name)

        detail_urls = []
        consecutive_errors = 0

        for page in range(1, MAX_PAGES_PER_SITE + 1):
            url = base_url if page == 1 else f"{base_url}&page={page}"
            html = fetch_html(url, session)
            if not html:
                break
            page_urls = _parse_listing_urls(html)
            if not page_urls:
                log.info("[ThinkSpain] %s — no more listings on page %d", name, page)
                break
            detail_urls.extend(u for u in page_urls if u not in processed)
            log.info("[ThinkSpain] page %d: +%d URLs", page, len(page_urls))
            human_delay()

        if limit:
            detail_urls = detail_urls[:limit]
        log.info("[ThinkSpain] %s — %d new detail URLs to scrape", name, len(detail_urls))

        for i, url in enumerate(detail_urls):
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.warning("[ThinkSpain] Too many errors, stopping")
                break

            log.info("[ThinkSpain] [%d/%d] %s", i + 1, len(detail_urls), url)

            listing = _scrape_detail(url, session, prop_type)
            if listing is None:
                consecutive_errors += 1
                continue

            consecutive_errors = 0
            results.append(listing)
            if not dry_run:
                append_listing(name, listing)
            human_delay()

    return results
