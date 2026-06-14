"""
JS-rendered regional agencies scraper (SITES_JS_NOPRX).
Uses system Playwright without proxy (most of these are small agencies that don't block).

14 sites across several JS frameworks:
  - EgoRealEstate API  (LaCentral, RusticMar)
  - Witei SaaS         (ViaAugusta)
  - Generic SPA        (HomeIn, Abonport, Elimari, ImmoMax, LaPlana, PrimeInmo, DeltaEbro rural)
"""
import re
import json
import time
import random
import logging
from urllib.parse import urljoin, urlparse

from config import (
    SITES_JS_NOPRX, MAX_PAGES_PER_SITE, MAX_CONSECUTIVE_ERRORS,
)
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, parse_price, parse_surface, is_solar_listing
from modules.cities import normalize, from_url_slug
from scrapers.base import new_listing, soup

log = logging.getLogger(__name__)

_PW_TIMEOUT = 30_000  # ms


def _get_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    return pw, browser


def _fetch_js(browser, url: str, wait_selector: str = None, timeout: int = _PW_TIMEOUT) -> str | None:
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0",
        locale="es-ES",
        viewport={"width": 1280, "height": 900},
    )
    ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webp}", lambda r: r.abort())
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=timeout)
            except Exception:
                pass
        else:
            page.wait_for_timeout(3000)
        return page.content()
    except Exception as e:
        log.warning("[regional] fetch error %s: %s", url, e)
        return None
    finally:
        ctx.close()


def _base_domain(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _scrape_detail_generic(browser, url: str, site_name: str) -> dict | None:
    html = _fetch_js(browser, url)
    if not html:
        return None

    bs = soup(html)
    base = _base_domain(url)

    # Title
    title = ""
    for sel in ["h1.ficha-title", "h1[class*='titulo']", "h1[class*='title']",
                ".property-title", ".inmueble-title", "h1"]:
        el = bs.select_one(sel)
        if el and len(el.get_text(strip=True)) > 4:
            title = clean_text(el.get_text())
            break

    # Price — JSON-LD first
    prix_eur, prix_display = None, ""
    for ld in bs.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(ld.string or "")
            items = d if isinstance(d, list) else [d]
            for item in items:
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    v = float(str(offers.get("price", 0)).replace(",", "."))
                    if v > 1000:
                        prix_eur = int(v)
                        prix_display = f"{int(v):,} €"
                        break
            if prix_eur:
                break
        except Exception:
            pass

    if not prix_eur:
        for sel in [".precio", ".price", "[class*='precio']", "[itemprop='price']"]:
            el = bs.select_one(sel)
            if el:
                prix_eur, prix_display = parse_price(clean_text(el.get_text()))
                if prix_eur:
                    break

    # Description
    desc = ""
    for sel in [".descripcion", ".description", "[class*='descripcion']", "[itemprop='description']"]:
        el = bs.select_one(sel)
        if el:
            c = clean_text(el.get_text())
            if len(c) > 40:
                desc = c
                break

    if not desc:
        for ld in bs.find_all("script", type="application/ld+json"):
            try:
                d = json.loads(ld.string or "")
                items = d if isinstance(d, list) else [d]
                for item in items:
                    if len(item.get("description", "")) > 40:
                        desc = clean_text(item["description"])
                        break
                if desc:
                    break
            except Exception:
                pass

    if is_solar_listing(desc):
        log.debug("[regional] skip solar: %s", url)
        return None

    # Surfaces
    terrain_m2 = None
    construction_m2 = None
    for line in bs.get_text("\n").split("\n"):
        l = line.lower().strip()
        if not l or len(l) > 200:
            continue
        if any(w in l for w in ["parcela", "terreno", "solar", "finca", "suelo"]):
            v = parse_surface(line)
            if v and 10 < v < 9_999_999:
                terrain_m2 = v
        if any(w in l for w in ["construida", "construidos", "habitable", "edificada"]):
            v = parse_surface(line)
            if v and 10 < v < 99_999:
                construction_m2 = v

    # City
    ville = ""
    for sel in ["[itemprop='addressLocality']", "[class*='localidad']", "[class*='ciudad']", ".location"]:
        el = bs.select_one(sel)
        if el:
            ville = clean_text(el.get_text().split(",")[0])
            break

    if not ville:
        parts = url.rstrip("/").split("/")
        for part in reversed(parts[:-1]):
            if len(part) > 3 and not part.isdigit() and part not in ("es", "en", "venta", "alquiler"):
                ville = from_url_slug(part)
                break

    # Images
    img = cover_image(html, "regional")
    photos = []
    for tag in bs.find_all("img", src=True):
        src = urljoin(base, tag["src"])
        if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]) and len(src) > 30:
            photos.append(src)
    photos = list(dict.fromkeys(photos))[:20]

    return new_listing(
        url=url,
        site=site_name,
        site_family="regional_js",
        type="finca",
        title=title,
        prix_eur=prix_eur,
        prix_display=prix_display,
        ville=ville,
        ville_canonical=normalize(ville),
        terrain_m2=terrain_m2,
        construction_m2=construction_m2,
        description_raw=desc,
        description_clean=desc,
        cover_image_url=img,
        photos=photos,
        ref="",
    )


def _collect_links_generic(browser, listing_url: str) -> list[str]:
    """Collect detail links from a paginated listing page."""
    html = _fetch_js(browser, listing_url)
    if not html:
        return []

    bs = soup(html)
    base = _base_domain(listing_url)
    links = []

    for a in bs.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base, href)
        # Must be a detail page (longer URL than root + listing path)
        if full.startswith(base) and len(href) > 20 and href not in ("/", listing_url):
            # Exclude pagination, filter, and nav links
            if not re.search(r"[?&](page|pag|p)=", href) and "#" not in href:
                if full not in links:
                    links.append(full)

    return links


def _collect_links_witei(browser, url: str) -> list[str]:
    """Witei SaaS: listings are in JSON embedded in window.__NUXT__ or via API."""
    html = _fetch_js(browser, url, wait_selector=".property-card, [class*='inmueble']")
    if not html:
        return []

    links = []
    base = _base_domain(url)
    bs = soup(html)

    for a in bs.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/(inmueble|property|ficha|detalle)/", href):
            full = urljoin(base, href)
            if full not in links:
                links.append(full)

    return links


def _run_site_js(site_config: dict, browser, dry_run: bool, limit: int = 0) -> int:
    name = site_config["name"]
    base_url = site_config["url"]
    base = _base_domain(base_url)
    processed = load_processed_urls(name)
    added = 0
    consecutive = 0

    log.info("[regional] %s — collecting links", name)
    all_detail_urls: list[str] = []

    for page in range(1, MAX_PAGES_PER_SITE + 1):
        if page == 1:
            purl = base_url
        else:
            sep = "&" if "?" in base_url else "?"
            # Try common pagination patterns
            purl = f"{base_url}{sep}page={page}"

        links = _collect_links_generic(browser, purl)
        if not links:
            break

        new_links = [l for l in links if l not in processed and l not in all_detail_urls]
        if not new_links:
            break

        all_detail_urls.extend(new_links)
        log.info("[regional] %s page %d: +%d links", name, page, len(new_links))
        time.sleep(random.uniform(2, 4))

    if limit:
        all_detail_urls = all_detail_urls[:limit]
    log.info("[regional] %s: %d new detail URLs", name, len(all_detail_urls))

    for i, url in enumerate(all_detail_urls):
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            log.warning("[regional] %s: too many errors, stopping", name)
            break

        log.info("[regional] %s [%d/%d] %s", name, i + 1, len(all_detail_urls), url[-60:])
        listing = _scrape_detail_generic(browser, url, name)

        if listing is None:
            consecutive += 1
            time.sleep(random.uniform(3, 6))
            continue

        consecutive = 0
        if not dry_run:
            append_listing(name, listing)
        added += 1
        time.sleep(random.uniform(3, 6))

    return added


def run(dry_run: bool = False, limit: int = 0) -> list[dict]:
    pw, browser = _get_browser()
    total = 0

    try:
        log.info("═" * 60)
        log.info("REGIONAL JS — %d sites", len(SITES_JS_NOPRX))
        for site in SITES_JS_NOPRX:
            log.info("→ %s", site["name"])
            try:
                total += _run_site_js(site, browser, dry_run, limit)
            except Exception as e:
                log.error("[regional] %s FAILED: %s", site["name"], e, exc_info=True)
    finally:
        browser.close()
        pw.stop()

    log.info("═" * 60)
    log.info("REGIONAL JS DONE: %d listings", total)
    return []
