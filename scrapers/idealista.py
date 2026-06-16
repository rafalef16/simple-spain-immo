"""
Idealista scraper — Playwright + EVOMI proxy.
Applies tourist license filter on the dedicated search URL.
Very aggressive anti-bot: long delays, single context.
"""
import re
import time
import random
import logging
from playwright.sync_api import sync_playwright

from config import (
    SITES_IDEALISTA, EVOMI_SERVER, EVOMI_USER, EVOMI_PASS_BASE,
    TOURIST_KEYWORDS, MAX_CONSECUTIVE_ERRORS, MAX_PAGES_PER_SITE,
)
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, parse_price, parse_surface, is_solar_listing
from modules.cities import normalize
from scrapers.base import new_listing

log = logging.getLogger(__name__)
SITE = "idealista"


def _is_valid_tourist_property(title: str, desc: str) -> bool:
    combined = (title + " " + desc).lower()
    return any(kw in combined for kw in TOURIST_KEYWORDS)


def _collect_urls(page, base_url: str, max_pages: int) -> list[str]:
    urls = []
    for pg in range(1, max_pages + 1):
        pg_url = base_url if pg == 1 else re.sub(r'/$', '', base_url) + f"/{pg}/"
        try:
            page.goto(pg_url, wait_until="networkidle", timeout=60000)
            time.sleep(random.uniform(8, 15))

            # Handle cookie consent
            try:
                page.click("#didomi-notice-agree-button", timeout=5000)
                time.sleep(2)
            except Exception:
                pass

            html = page.content()
            if "captcha" in html.lower() or "bloqueo" in html.lower():
                log.warning("[Idealista] Possible block on page %d", pg)
                break

            page_urls = re.findall(r'href="(/inmueble/\d+/)"', html)
            if not page_urls:
                break
            full_urls = [f"https://www.idealista.com{u}" for u in page_urls]
            urls.extend(full_urls)
            log.info("[Idealista] Page %d: +%d URLs", pg, len(full_urls))
        except Exception as e:
            log.warning("[Idealista] Error on page %d: %s", pg, e)
            break

    return list(dict.fromkeys(urls))


def _scrape_detail(page, url: str, site_config: dict) -> dict | None:
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(random.uniform(6, 12))

        html = page.content()
        if "captcha" in html.lower():
            log.warning("[Idealista] Captcha on %s", url)
            return None

        # Title
        title = ""
        for sel in ["h1.main-info__title", "h1[class*='title']", "h1.detail-info__title", "h1"]:
            el = page.locator(sel)
            if el.count() > 0:
                title = clean_text(el.first.inner_text())
                break

        # Price — Playwright test: page.getByText('460.000', {exact:true})
        prix_raw = ""
        for sel in [".info-data-price span", ".price-features__price", ".info-data-price",
                    "[class*='price-features']", "[class*='price']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = clean_text(el.first.inner_text())
                if any(c.isdigit() for c in t):
                    prix_raw = t
                    break
        prix_eur, prix_display = parse_price(prix_raw)

        # Description — Playwright test: click 'Leer comentario completo' link first
        try:
            page.get_by_role("link", name="Leer comentario completo").click(timeout=4000)
            time.sleep(1)
        except Exception:
            try:
                page.locator("a.more-description, a[class*='more'], a[class*='description-link']").click(timeout=2000)
                time.sleep(1)
            except Exception:
                pass

        desc = ""
        for sel in [".comment .description", "#details .comment", ".adCommentsLanguage",
                    "[class*='description']", ".comment", "#detailedComment"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = clean_text(el.first.inner_text())
                if len(t) > 30:
                    desc = t
                    break

        if is_solar_listing(desc):
            return None

        # Tourist filter on dedicated search
        if site_config.get("tourist_filter") and not _is_valid_tourist_property(title, desc):
            log.debug("[Idealista] Not tourist property, skipping: %s", url)
            return None

        # Surfaces — Playwright test: page.getByText('446 m²').nth(1) for terrain
        terrain_m2 = None
        construction_m2 = None
        for sel in [".details-property-feature-one li", ".details-property_features li",
                    ".details-property li", "li[class*='feature']"]:
            items = page.locator(sel).all()
            if items:
                for it in items:
                    text = it.inner_text().lower()
                    if any(w in text for w in ["parcela", "terreno", "solar", "finca"]):
                        v = parse_surface(text)
                        if v and terrain_m2 is None:
                            terrain_m2 = v
                    if any(w in text for w in ["construida", "útil", "construidos", "habitable"]):
                        v = parse_surface(text)
                        if v and construction_m2 is None:
                            construction_m2 = v
                break
        # Fallback: regex on full page text for m² patterns
        if terrain_m2 is None or construction_m2 is None:
            page_text = page.inner_text("body")
            for line in page_text.split("\n"):
                ll = line.lower()
                if terrain_m2 is None and any(w in ll for w in ["parcela", "terreno", "finca"]):
                    v = parse_surface(line)
                    if v:
                        terrain_m2 = v
                if construction_m2 is None and any(w in ll for w in ["construida", "útil", "habitable"]):
                    v = parse_surface(line)
                    if v:
                        construction_m2 = v

        # City — Playwright test: page.getByText('Llevant, Reus') near main title
        ville = ""
        for sel in [".main-info__title-minor", ".ide-primary-title + *", "[class*='location']",
                    ".main-info__subtitle", "address", "[class*='address']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = clean_text(el.first.inner_text().split(",")[0])
                if t:
                    ville = t
                    break
        ville_canonical = normalize(ville)

        # Images — Playwright test: .main-image_first > picture, #gallery img
        img = cover_image(html, SITE)
        if not img:
            for sel in [".main-image_first picture img", "#gallery img", ".images-slider img"]:
                el = page.locator(sel)
                if el.count() > 0:
                    src = el.first.get_attribute("src") or el.first.get_attribute("data-src") or ""
                    if src.startswith("http"):
                        img = src
                        break
        photos = list(dict.fromkeys(
            re.findall(r'https://[^"\']+idealista[^"\']+\.(jpg|jpeg|webp)', html)
        ))[:20]

        ref_m = re.search(r'/inmueble/(\d+)/', url)
        ref = ref_m.group(1) if ref_m else None

        return new_listing(
            url=url,
            site=SITE,
            site_family=SITE,
            type=site_config.get("type", ""),
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

    except Exception as e:
        log.warning("[Idealista] Error on %s: %s", url, e)
        return None


def run(dry_run: bool = False, limit: int = 0) -> list[dict]:
    results = []

    with sync_playwright() as p:
        proxy_pass = f"{EVOMI_PASS_BASE}_hardsession-IDEALISTA01"
        context = p.chromium.launch_persistent_context(
            "/tmp/idealista_profile",
            headless=True,
            proxy={"server": EVOMI_SERVER, "username": EVOMI_USER, "password": proxy_pass},
            ignore_https_errors=True,
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}", lambda r: r.abort())

        for site_config in SITES_IDEALISTA:
            name = site_config["name"]
            processed = load_processed_urls(name)
            log.info("[Idealista] %s — starting", name)

            all_urls = _collect_urls(page, site_config["url"], MAX_PAGES_PER_SITE)
            new_urls = [u for u in all_urls if u not in processed]
            if limit:
                new_urls = new_urls[:limit]
            log.info("[Idealista] %s — %d new listings", name, len(new_urls))

            consecutive_errors = 0
            for i, url in enumerate(new_urls):
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    log.warning("[Idealista] Too many errors, stopping")
                    break

                log.info("[Idealista] [%d/%d] %s", i + 1, len(new_urls), url)
                listing = _scrape_detail(page, url, site_config)

                if listing is None:
                    consecutive_errors += 1
                    time.sleep(random.uniform(5, 10))
                    continue

                consecutive_errors = 0
                results.append(listing)
                if not dry_run:
                    append_listing(name, listing)
                time.sleep(random.uniform(8, 15))

        context.close()

    return results
