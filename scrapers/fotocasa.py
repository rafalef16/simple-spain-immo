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
        pg_url = base_url if pg == 1 else re.sub(r'/l(/\d+)?$', f'/l/{pg}', base_url)
        if pg > 1 and pg_url == base_url:
            pg_url = base_url.rstrip("/") + f"/{pg}"
        try:
            page.goto(pg_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(random.uniform(3, 5))

            # Accept cookies once
            try:
                page.get_by_role("button", name=re.compile("Aceptar", re.IGNORECASE)).click(timeout=3000)
            except Exception:
                pass

            html = page.content()
            # Property URLs: /es/comprar/<type>/<zone>/<id>
            page_urls = re.findall(r'"(https://www\.fotocasa\.es/es/(?:comprar|alquiler)/[^"]+/\d+)"', html)
            page_urls = [u for u in page_urls if not u.endswith("/l")]
            page_urls = list(dict.fromkeys(page_urls))

            if not page_urls:
                log.info("[Fotocasa] No listings on page %d, stopping pagination", pg)
                break

            urls.extend(page_urls)
            log.info("[Fotocasa] Page %d: +%d URLs", pg, len(page_urls))

            # Check pagination link — Playwright test: 'Siguiente' or 'Ir a la siguiente página'
            has_next = False
            for next_name in ["Siguiente", "Ir a la siguiente página"]:
                if page.get_by_role("link", name=next_name).count() > 0:
                    has_next = True
                    break
            if not has_next:
                log.info("[Fotocasa] No next-page link, stopping after page %d", pg)
                break

        except Exception as e:
            log.warning("[Fotocasa] Error collecting page %d: %s", pg, e)
            break

    return list(dict.fromkeys(urls))


def _scrape_detail(page, url: str, prop_type: str) -> dict | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000, referer="https://www.google.es/")
        page.evaluate("() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}) }")
        time.sleep(random.uniform(4, 6))

        # Description — Playwright test: click 'Leer más' button then read text
        try:
            page.get_by_role("button", name="Leer más").click(timeout=3000)
            time.sleep(1)
        except Exception:
            try:
                page.evaluate('''() => {
                    document.querySelector(".re-DetailDescription-button, [class*='description'] button")?.click();
                }''')
                time.sleep(1)
            except Exception:
                pass

        html = page.content()

        # Description text — try multiple selectors
        desc = ""
        for sel in [".re-DetailDescriptionContainer", ".re-DetailDescription",
                    "[class*='DetailDescription']", "[class*='description-text']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = clean_text(el.first.inner_text())
                if len(t) > 30:
                    desc = t
                    break

        if is_solar_listing(desc):
            log.debug("[Fotocasa] Skipping solar: %s", url)
            return None

        # Price — Playwright test: page.locator('span').filter({ hasText: '€' })
        prix_raw = ""
        for sel in [".re-DetailHeader-price", "[class*='DetailHeader-price']",
                    "[class*='price']", "span[class*='price']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = clean_text(el.first.inner_text())
                if any(c.isdigit() for c in t):
                    prix_raw = t
                    break
        if not prix_raw:
            spans = page.locator("span").all()
            for sp in spans[:60]:
                t = sp.inner_text()
                if "€" in t and any(c.isdigit() for c in t):
                    prix_raw = clean_text(t)
                    break
        prix_eur, prix_display = parse_price(prix_raw)

        # Surfaces — Playwright test: 'habs.6 baños394 m²37258 m² terreno' in one block
        terrain_m2 = None
        construction_m2 = None
        for sel in [".re-DetailFeaturesList li", "[class*='Features'] li",
                    "[class*='feature'] li", "li[class*='detail']"]:
            items = page.locator(sel).all()
            if items:
                for it in items:
                    text = it.inner_text().lower()
                    if any(w in text for w in ["terreno", "parcela", "suelo", "solar"]):
                        v = parse_surface(text)
                        if v and terrain_m2 is None:
                            terrain_m2 = v
                    if any(w in text for w in ["construida", "útil", "habitable"]):
                        v = parse_surface(text)
                        if v and construction_m2 is None:
                            construction_m2 = v
                if terrain_m2 or construction_m2:
                    break
        # Fallback: parse stats block text (e.g. '394 m²37258 m² terreno')
        if terrain_m2 is None:
            stats_text = ""
            for sel in ["[class*='topContainer']", "[data-testid*='topContainer']", "[class*='Features']"]:
                el = page.locator(sel)
                if el.count() > 0:
                    stats_text = el.first.inner_text()
                    break
            if stats_text:
                m2_matches = re.findall(r'([\d\.]+)\s*m²\s*(terreno|suelo|parcela)?', stats_text.lower())
                for val, label in m2_matches:
                    v = parse_surface(val + " m²")
                    if label and terrain_m2 is None:
                        terrain_m2 = v
                    elif not label and construction_m2 is None:
                        construction_m2 = v

        # City — Playwright test: getByTestId('re-ContentDetail-topContainer--main').getByText('Reus')
        ville = ""
        city_el = page.get_by_test_id("re-ContentDetail-topContainer--main")
        if city_el.count() > 0:
            raw = clean_text(city_el.first.inner_text())
            # Take last non-empty line (usually city)
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            if lines:
                ville = lines[-1].split(",")[0].strip()
        if not ville:
            for sel in ["[class*='DetailLocation']", "[class*='location']", "address"]:
                el = page.locator(sel)
                if el.count() > 0:
                    ville = clean_text(el.first.inner_text().split(",")[0])
                    break
        if not ville:
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


def run(dry_run: bool = False, limit: int = 0) -> list[dict]:
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
            if limit:
                new_urls = new_urls[:limit]
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
