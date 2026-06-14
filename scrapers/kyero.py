"""
Kyero scraper — static HTML, no proxy needed.
Pagination via ?page=N or /page/N.
"""
import re
import logging
import requests

from config import SITES_KYERO, MAX_PAGES_PER_SITE, MAX_CONSECUTIVE_ERRORS
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, dedup_hash, parse_price, parse_surface, is_solar_listing
from modules.cities import normalize
from scrapers.base import fetch_html, human_delay, new_listing, soup

log = logging.getLogger(__name__)
SITE = "kyero"


def _parse_listing_urls(html: str, base_url: str) -> list[str]:
    bs = soup(html)
    urls = []

    for a in bs.select("a[href]"):
        href = a.get("href", "")
        if re.search(r'/\d{5,}/?$', href) or '/property/' in href or '/annonce/' in href or '/propriete/' in href:
            full = href if href.startswith("http") else f"https://www.kyero.com{href}"
            if full not in urls:
                urls.append(full)

    # Also try JSON-LD on listing page
    import json
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("Product", "RealEstateListing", "Offer"):
                    url = item.get("url") or item.get("@id")
                    if url and "kyero" in url:
                        urls.append(url)
        except Exception:
            pass

    return list(dict.fromkeys(urls))


def _has_next_page(html: str, current_page: int) -> bool:
    bs = soup(html)
    next_link = bs.select_one('a[rel="next"], .pagination .next, [class*="next-page"]')
    return next_link is not None


def _scrape_detail(url: str, session: requests.Session) -> dict | None:
    html = fetch_html(url, session)
    if not html:
        return None

    bs = soup(html)

    # Title
    title = ""
    for sel in ["h1.property-title", "h1[class*='title']", "[class*='property-name']", "h1"]:
        el = bs.select_one(sel)
        if el:
            title = clean_text(el.get_text())
            break

    # Price
    prix_raw = ""
    for sel in ["[class*='price']", "[itemprop='price']", ".listing-price"]:
        el = bs.select_one(sel)
        if el:
            prix_raw = clean_text(el.get_text())
            break
    prix_eur, prix_display = parse_price(prix_raw)

    # Description
    desc = ""
    for sel in ["[class*='description']", ".property-description", "[itemprop='description']"]:
        el = bs.select_one(sel)
        if el:
            desc = clean_text(el.get_text())
            break

    if is_solar_listing(desc):
        log.debug("Skipping solar listing: %s", url)
        return None

    # Surfaces
    terrain_m2 = None
    construction_m2 = None
    full_text = bs.get_text()
    for line in full_text.split("\n"):
        l = line.lower()
        if any(w in l for w in ["plot", "terreno", "parcela", "land"]):
            v = parse_surface(line)
            if v:
                terrain_m2 = v
        if any(w in l for w in ["built", "construida", "build", "habitable", "interior"]):
            v = parse_surface(line)
            if v:
                construction_m2 = v

    # City
    ville = ""
    for sel in ["[class*='location']", "[itemprop='addressLocality']", ".property-location"]:
        el = bs.select_one(sel)
        if el:
            ville = clean_text(el.get_text().split(",")[0])
            break
    ville_canonical = normalize(ville)

    img = cover_image(html, SITE)
    photos = [
        t.get("src") for t in bs.select("img[src]")
        if t.get("src", "") and "kyero" in t.get("src", "")
    ][:20]

    ref_m = re.search(r'/(\d{5,})', url)
    ref = ref_m.group(1) if ref_m else None

    return new_listing(
        url=url,
        site=SITE,
        site_family=SITE,
        type="finca",
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
        photos=photos,
        ref=ref,
    )


def run(dry_run: bool = False) -> list[dict]:
    session = requests.Session()
    results = []

    for site_config in SITES_KYERO:
        name = site_config["name"]
        base_url = site_config["url"]

        processed = load_processed_urls(name)
        log.info("[Kyero] %s — starting", name)

        detail_urls = []
        consecutive_errors = 0

        for page in range(1, MAX_PAGES_PER_SITE + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            html = fetch_html(url, session)
            if not html:
                break
            page_urls = _parse_listing_urls(html, base_url)
            if not page_urls:
                log.info("[Kyero] no more listings on page %d", page)
                break
            detail_urls.extend(u for u in page_urls if u not in processed)
            if not _has_next_page(html, page):
                break
            human_delay()

        log.info("[Kyero] %d new detail URLs", len(detail_urls))

        for i, url in enumerate(detail_urls):
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.warning("[Kyero] too many errors, stopping")
                break

            log.info("[Kyero] [%d/%d] %s", i + 1, len(detail_urls), url)
            listing = _scrape_detail(url, session)

            if listing is None:
                consecutive_errors += 1
                continue

            consecutive_errors = 0
            results.append(listing)
            if not dry_run:
                append_listing(name, listing)
            human_delay()

    return results
