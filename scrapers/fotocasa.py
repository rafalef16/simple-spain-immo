"""
Fotocasa scraper — Playwright + EVOMI residential proxy.
Context rotated every 40 requests. Stop after 15 consecutive errors.
"""
import re
import time
import random
import string
import logging
from playwright.sync_api import sync_playwright, BrowserContext

from config import (
    SITES_FOTOCASA, EVOMI_SERVER, EVOMI_USER, EVOMI_PASS_BASE,
    MAX_CONSECUTIVE_ERRORS, MAX_PAGES_PER_SITE,
)
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, parse_price, parse_surface, is_solar_listing
from modules.cities import from_url_slug
from scrapers.base import new_listing

log = logging.getLogger(__name__)
SITE = "fotocasa"


def _session_id() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def _make_context(p, hard_session: bool = False) -> BrowserContext:
    session = _session_id() if hard_session else "SHARED"
    proxy_pass = f"{EVOMI_PASS_BASE}_hardsession-{session}"
    return p.chromium.launch_persistent_context(
        f"/tmp/fotocasa_profile_{session}",
        headless=True,
        proxy={"server": EVOMI_SERVER, "username": EVOMI_USER, "password": proxy_pass},
        ignore_https_errors=True,
        locale="es-ES",
        timezone_id="Europe/Madrid",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )


def _collect_listing_urls(page, base_url: str) -> list[str]:
    """Collect all listing URLs from search result pages."""
    urls = []
    for pg in range(1, MAX_PAGES_PER_SITE + 1):
        url = base_url if pg == 1 else f"{base_url}&pg={pg}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(3, 5))

            # Accept cookies once
            try:
                page.get_by_role("button", name=re.compile("Aceptar", re.IGNORECASE)).click(timeout=3000)
            except Exception:
                pass

            html = page.content()
            page_urls = re.findall(r'href="(https://www\.fotocasa\.es/es/comprar/[^"]+/\d+)"', html)
            page_urls = list(dict.fromkeys(page_urls))

            if not page_urls:
                log.info("[Fotocasa] No listings on page %d, stopping pagination", pg)
                break

            urls.extend(page_urls)
            log.info("[Fotocasa] Page %d: +%d URLs", pg, len(page_urls))
        except Exception as e:
            log.warning("[Fotocasa] Error collecting page %d: %s", pg, e)
            break

    return list(dict.fromkeys(urls))


def _scrape_detail(page, url: str, prop_type: str) -> dict | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000, referer="https://www.google.es/")
        page.evaluate("() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}) }")
        time.sleep(random.uniform(4, 6))

        try:
            page.evaluate('''() => {
                const btn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.includes("Leer más"));
                if (btn) btn.click();
                else document.querySelector(".re-DetailDescription-button")?.click();
            }''')
            time.sleep(1)
        except Exception:
            pass

        html = page.content()

        desc_el = page.locator(".re-DetailDescriptionContainer")
        desc = clean_text(desc_el.inner_text()) if desc_el.count() > 0 else ""

        if is_solar_listing(desc):
            log.debug("[Fotocasa] Skipping solar: %s", url)
            return None

        prix_raw = ""
        prix_el = page.locator(".re-DetailHeader-price")
        if prix_el.count() > 0:
            prix_raw = clean_text(prix_el.first.inner_text())
        prix_eur, prix_display = parse_price(prix_raw)

        # Surfaces from features list
        terrain_m2 = None
        construction_m2 = None
        features = page.locator(".re-DetailFeaturesList li")
        for i in range(features.count()):
            text = features.nth(i).inner_text().lower()
            if "terreno" in text or "parcela" in text or "suelo" in text:
                terrain_m2 = parse_surface(text)
            if "construida" in text or "útil" in text or "habitable" in text:
                construction_m2 = parse_surface(text)

        # City from URL
        parts = url.split("/")
        ville_slug = parts[6] if len(parts) > 6 else ""
        ville = from_url_slug(ville_slug)

        img = cover_image(html, SITE)
        photos = list({
            f"{u}?rule=web_948x542_ar"
            for u in re.findall(r'https://static\.fotocasa\.es/images/ads/[a-z0-9/-]+', html)
        })[:20]

        title_el = page.locator("h1")
        title = clean_text(title_el.first.inner_text()) if title_el.count() > 0 else ""

        return new_listing(
            url=url,
            site=SITE,
            site_family=SITE,
            type=prop_type,
            title=title,
            prix_eur=prix_eur,
            prix_display=prix_display or prix_raw,
            ville=ville,
            ville_canonical=ville,
            terrain_m2=terrain_m2,
            construction_m2=construction_m2,
            description_raw=desc,
            description_clean=desc,
            cover_image_url=img,
            photos=photos,
        )

    except Exception as e:
        log.warning("[Fotocasa] Error on %s: %s", url, e)
        return None


def run(dry_run: bool = False) -> list[dict]:
    results = []

    with sync_playwright() as p:
        for site_config in SITES_FOTOCASA:
            name = site_config["name"]
            base_url = site_config["url"]
            prop_type = site_config["type"]

            processed = load_processed_urls(name)
            log.info("[Fotocasa] %s — starting", name)

            context = _make_context(p, hard_session=False)
            page = context.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda r: r.abort())

            # Collect listing URLs
            all_urls = _collect_listing_urls(page, base_url)
            new_urls = [u for u in all_urls if u not in processed]
            log.info("[Fotocasa] %s — %d new listings", name, len(new_urls))

            consecutive_errors = 0

            for i, url in enumerate(new_urls):
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    log.warning("[Fotocasa] Too many errors, stopping")
                    break

                # Rotate context every 40 requests
                if i > 0 and i % 40 == 0:
                    context.close()
                    context = _make_context(p, hard_session=True)
                    page = context.new_page()
                    page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda r: r.abort())

                log.info("[Fotocasa] [%d/%d] %s", i + 1, len(new_urls), url)
                listing = _scrape_detail(page, url, prop_type)

                if listing is None:
                    consecutive_errors += 1
                    page.close()
                    page = context.new_page()
                    page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda r: r.abort())
                    continue

                consecutive_errors = 0
                results.append(listing)
                if not dry_run:
                    append_listing(name, listing)

                time.sleep(random.uniform(1, 3))

            context.close()

    return results
