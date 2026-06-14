"""
Regional agencies scraper — 7 distinct CMS families detected by live audit:

  MOBILIA_A      : /ficha/ relative links   — FinquesRoca, FinquesFarnos, EbreTaxacions, Esteller, Rieres
  MOBILIA_DETALLE: /detalle/ links           — JCInmo x4
  EBRORIVER      : /detalles-es/property/   — EbroRiver x3
  EBREPISOS      : Drupal /propietat/ref/   — EbrePisos x4
  DELTAEBRO      : /es/rustica/venta/city/  — DeltaEbro x1
  ACTIVEHOUSE    : JSON-LD embedded Product  — ActiveHouse x2
  INMOWEB_SEO    : data-url -esNNNNNN.html  — Stanza, EstebanInmo, FinquesEbre

Pagination:
  MOBILIA_A / EBRORIVER / INMOWEB_SEO → &pag=N
  MOBILIA_DETALLE                     → ?p=N
  EBREPISOS                           → &page=N  (0-indexed, page=0 = first page)
  DELTAEBRO                           → ?page=N
  ACTIVEHOUSE                         → no pagination (12-20 listings per page)
"""
import re
import json
import time
import random
import logging
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

from config import (
    SITES_MOBILIA_A, SITES_MOBILIA_DETALLE, SITES_EBRORIVER,
    SITES_EBREPISOS, SITES_DELTAEBRO, SITES_ACTIVEHOUSE, SITES_INMOWEB_SEO,
    MAX_PAGES_PER_SITE, MAX_CONSECUTIVE_ERRORS, HEADERS,
)
from modules.db import load_processed_urls, append_listing
from modules.cleanup import clean_text, cover_image, parse_price, parse_surface, is_solar_listing
from modules.cities import from_url_slug, normalize
from scrapers.base import fetch_html, human_delay, new_listing, soup

log = logging.getLogger(__name__)


def _base_domain(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _page_url(base_url: str, page: int, param: str, first_page: int = 1) -> str:
    """Build paginated URL.
    1-indexed: page 1 = base_url unchanged; page 2+ appends &param=N.
    0-indexed (Drupal): first_page=0; page 0 appends &page=0."""
    if page == 1 and first_page == 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{param}={page}"


# ── DETAIL PAGE SCRAPER (generic, covers all families) ────────────────────

def _scrape_detail(url: str, session: requests.Session, site_name: str) -> dict | None:
    html = fetch_html(url, session)
    if not html:
        return None

    bs = soup(html)
    base = _base_domain(url)

    # TITLE
    title = ""
    for sel in ["h1.ficha-title", "h1[class*='titulo']", "h1[class*='title']",
                "#titulo_inmueble", ".detail-title h1", ".property-title", "h1"]:
        el = bs.select_one(sel)
        if el and len(el.get_text(strip=True)) > 4:
            title = clean_text(el.get_text())
            break

    # PRICE — try JSON-LD first, then CSS
    prix_eur, prix_display = None, ""
    for ld_script in bs.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(ld_script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                offers = item.get("offers", {})
                if isinstance(offers, dict) and offers.get("price"):
                    v = float(str(offers["price"]).replace(",", "."))
                    if v > 1000:
                        prix_eur = int(v)
                        prix_display = f"{int(v):,} €"
                        break
            if prix_eur:
                break
        except Exception:
            pass

    if not prix_eur:
        for sel in [".precio", "#precio", ".price", "[class*='precio']", "[class*='price']",
                    ".ficha-precio", ".property-price", "[itemprop='price']"]:
            el = bs.select_one(sel)
            if el:
                raw = clean_text(el.get_text())
                prix_eur, prix_display = parse_price(raw)
                if prix_eur and prix_eur > 1000:
                    break

    # DESCRIPTION
    desc = ""
    for sel in [".descripcion", "#descripcion", ".description", "[class*='descripcion']",
                "[class*='description']", ".obs", ".detail-description", "[itemprop='description']"]:
        el = bs.select_one(sel)
        if el:
            candidate = clean_text(el.get_text())
            if len(candidate) > 40:
                desc = candidate
                break

    if not desc:
        for ld_script in bs.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(ld_script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    d = item.get("description", "")
                    if d and len(d) > 40:
                        desc = clean_text(d)
                        break
                if desc:
                    break
            except Exception:
                pass

    if is_solar_listing(desc):
        log.debug("[Mobilia] Skip solar: %s", url)
        return None

    # SURFACES
    terrain_m2 = None
    construction_m2 = None
    for line in bs.get_text("\n").split("\n"):
        l = line.lower().strip()
        if not l or len(l) > 200:
            continue
        if any(w in l for w in ["parcela", "terreno", "solar", "finca", "suelo", "superficie total"]):
            v = parse_surface(line)
            if v and 10 < v < 9_999_999:
                terrain_m2 = v
        if any(w in l for w in ["construida", "construidos", "útiles", "habitable", "vivienda", "edificada"]):
            v = parse_surface(line)
            if v and 10 < v < 99_999:
                construction_m2 = v

    # CITY — from URL slug or HTML
    ville = ""
    parts = url.rstrip("/").split("/")
    if "/ficha/" in url:
        try:
            idx = next(i for i, p in enumerate(parts) if p == "ficha")
            ville = from_url_slug(parts[idx + 2]) if idx + 2 < len(parts) else ""
        except (StopIteration, IndexError):
            pass
    elif "/detalle/" in url or "/detalles-es/" in url or "/rustica/venta/" in url:
        # city is usually parts[-3] or -4
        for part in reversed(parts[:-2]):
            if len(part) > 3 and not part.isdigit() and part not in ("es", "en", "fr", "venta", "detalles"):
                ville = from_url_slug(part)
                break

    if not ville:
        for sel in ["[class*='municipio']", "[class*='localidad']", "[class*='ciudad']",
                    "[itemprop='addressLocality']", ".location", ".city"]:
            el = bs.select_one(sel)
            if el:
                ville = clean_text(el.get_text().split(",")[0])
                break

    # REF
    ref = ""
    ref_el = bs.select_one("[class*='ref'], [class*='referencia'], #ref, .reference")
    if ref_el:
        ref = re.sub(r"[^\d]", "", ref_el.get_text())
    if not ref:
        m = re.search(r"/(\d{5,})(?:/[^/]+)?/?$", url)
        if m:
            ref = m.group(1)

    # IMAGES
    img = cover_image(html, "mobilia")
    photos = []
    for img_tag in bs.find_all("img", src=True):
        src = urljoin(base, img_tag["src"])
        if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]) and len(src) > 30:
            photos.append(src)
    photos = list(dict.fromkeys(photos))[:20]

    return new_listing(
        url=url,
        site=site_name,
        site_family="mobilia",
        type="finca",
        title=title,
        prix_eur=prix_eur,
        prix_display=prix_display or str(prix_eur or ""),
        ville=ville,
        ville_canonical=normalize(ville),
        terrain_m2=terrain_m2,
        construction_m2=construction_m2,
        description_raw=desc,
        description_clean=desc,
        cover_image_url=img,
        photos=photos,
        ref=ref,
    )


# ── LINK COLLECTORS (one per family) ──────────────────────────────────────

def _links_mobilia_a(html: str, base: str) -> list[str]:
    """/ficha/ relative or absolute links."""
    urls = []
    bs = soup(html)
    for a in bs.find_all("a", href=True):
        href = a["href"]
        if "ficha" in href.lower() and len(href) > 15:
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)
    return urls


def _links_jcinmo(html: str, base: str) -> list[str]:
    """/detalle/ links."""
    urls = []
    bs = soup(html)
    for a in bs.find_all("a", href=True):
        href = a["href"]
        if "/detalle/" in href and len(href) > 20:
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)
    return urls


def _links_ebroriver(html: str, base: str) -> list[str]:
    """/detalles-es/property/ links."""
    urls = []
    bs = soup(html)
    for a in bs.find_all("a", href=True):
        href = a["href"]
        if "/detalles-es/" in href or "/detalles-en/" in href:
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)
    return urls


def _links_ebrepisos(html: str, base: str) -> list[str]:
    """/propietat/ref/ links (Drupal)."""
    urls = []
    bs = soup(html)
    for a in bs.find_all("a", href=True):
        href = a["href"]
        if "/propietat/" in href or "/propiedad/" in href:
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)
    return urls


def _links_deltaebro(html: str, base: str) -> list[str]:
    """Custom slug /es/rustica/venta/{city}/{slug}/{ID}."""
    urls = []
    bs = soup(html)
    for a in bs.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/(?:rustica|rural|venta)/[^/]+/.+/\d+$", href):
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)
    return urls


def _links_activehouse(html: str, base: str) -> list[str]:
    """Extract listing URLs from JSON-LD + card anchors."""
    urls = []
    bs = soup(html)

    # Approach: card anchors are #NNNNNNNN → build URL as /buscador/?ref=NNNNNNNN
    cards = bs.select(".card")
    for card in cards:
        for a in card.find_all("a", href=True):
            href = a["href"]
            m = re.match(r"#(\d{6,})", href)
            if m:
                ref_id = m.group(1)
                # ActiveHouse detail URL pattern
                detail_url = f"{base}/propiedad/{ref_id}/"
                if detail_url not in urls:
                    urls.append(detail_url)

    return urls


def _listings_activehouse_from_jsonld(html: str, site_name: str, base_url: str) -> list[dict]:
    """
    ActiveHouse embeds full JSON-LD per listing on the search page.
    Extract directly without needing detail page requests.
    """
    bs = soup(html)
    listings = []
    base = _base_domain(base_url)

    product_data = {}  # name -> Product data
    residence_data = {}  # name -> Residence data

    for s in bs.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
            graph = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in (graph if isinstance(graph, list) else [graph]):
                name = item.get("name", "")
                if item.get("@type") == "Product" and name:
                    product_data[name] = item
                elif item.get("@type") == "Residence" and name:
                    residence_data[name] = item
        except Exception:
            pass

    # Match Product + Residence by name
    for name, prod in product_data.items():
        res = residence_data.get(name, {})

        offers = prod.get("offers", {})
        if isinstance(offers, str):
            try:
                offers = eval(offers)
            except Exception:
                offers = {}

        prix_raw = str(offers.get("price", "")) if isinstance(offers, dict) else ""
        prix_eur, prix_display = parse_price(prix_raw)

        # Fix price if it looks wrong (< 1000 → likely in thousands or malformed)
        if prix_eur and prix_eur < 1000:
            prix_eur = prix_eur * 1000
            prix_display = f"{prix_eur:,} €"

        desc = clean_text(prod.get("description", "") or "")
        if is_solar_listing(desc):
            continue

        # Address from Residence
        addr = res.get("address", {})
        if isinstance(addr, str):
            try:
                addr = eval(addr)
            except Exception:
                addr = {}
        ville = addr.get("addressLocality", "") if isinstance(addr, dict) else ""

        # Photo
        photos_raw = res.get("photo", [])
        if isinstance(photos_raw, str):
            try:
                photos_raw = eval(photos_raw)
            except Exception:
                photos_raw = []
        photos = []
        for p in (photos_raw if isinstance(photos_raw, list) else []):
            if isinstance(p, dict) and p.get("contentUrl"):
                photos.append(p["contentUrl"])
            elif isinstance(p, str) and p.startswith("http"):
                photos.append(p)

        # Surfaces from description
        terrain_m2 = None
        for line in desc.split("."):
            v = parse_surface(line)
            if v and 100 < v < 9_999_999:
                terrain_m2 = v
                break

        # Construct URL from logo path (contains agency ID) + card ref
        listing_url = prod.get("url") or prod.get("@id") or base_url
        logo = prod.get("logo", "")
        logo_match = re.search(r"/imgs/w(\d+)/", logo)
        agency_id = logo_match.group(1) if logo_match else ""

        listing = new_listing(
            url=listing_url,
            site=site_name,
            site_family="mobilia",
            type="finca",
            title=clean_text(name),
            prix_eur=prix_eur,
            prix_display=prix_display,
            ville=ville,
            ville_canonical=normalize(ville),
            terrain_m2=terrain_m2,
            construction_m2=None,
            description_raw=desc,
            description_clean=desc,
            cover_image_url=photos[0] if photos else None,
            photos=photos[:20],
            ref=agency_id,
        )
        listings.append(listing)

    return listings


def _links_inmoweb_seo(html: str, base: str) -> list[str]:
    """InmoWeb data-url with -esNNNNNN.html pattern."""
    urls = []
    bs_html = soup(html)

    for a in bs_html.find_all("a", href=True):
        href = a["href"]
        if re.search(r"-es\d{5,}[.]html", href):
            full = urljoin(base, href)
            if full not in urls:
                urls.append(full)

    for m in re.findall(r'data-url=["\']([^"\']*-es\d{5,}[.]html)["\']', html):
        full = urljoin(base, m)
        if full not in urls:
            urls.append(full)

    return urls


# ── GENERIC SITE SCRAPER ───────────────────────────────────────────────────

def _run_site(site_config: dict, link_fn, page_param: str,
              session: requests.Session, dry_run: bool, page0: int = 1) -> int:
    """Generic runner: collect links via pagination → scrape each detail page."""
    name = site_config["name"]
    base_url = site_config["url"]
    base = _base_domain(base_url)
    processed = load_processed_urls(name)
    added = 0

    detail_urls: list[str] = []
    for page in range(page0, page0 + MAX_PAGES_PER_SITE):
        url = _page_url(base_url, page, page_param, first_page=page0)

        html = fetch_html(url, session)
        if not html:
            break
        links = link_fn(html, base)
        new_links = [l for l in links if l not in processed and l not in detail_urls]
        if not links:
            break
        detail_urls.extend(new_links)
        log.debug("[%s] page %d: +%d links", name, page, len(new_links))
        time.sleep(random.uniform(1.5, 3.0))

    if limit:
        detail_urls = detail_urls[:limit]
    log.info("[%s] %d new detail URLs", name, len(detail_urls))
    consecutive = 0

    for i, url in enumerate(detail_urls):
        if consecutive >= MAX_CONSECUTIVE_ERRORS:
            log.warning("[%s] too many errors, stopping", name)
            break

        log.info("[%s] [%d/%d] %s", name, i + 1, len(detail_urls), url[-60:])
        listing = _scrape_detail(url, session, name)

        if listing is None:
            consecutive += 1
            time.sleep(random.uniform(2, 4))
            continue

        consecutive = 0
        if not dry_run:
            append_listing(name, listing)
        added += 1
        time.sleep(random.uniform(2.0, 4.0))

    return added


# ── PUBLIC ENTRY POINT ────────────────────────────────────────────────────

def run(dry_run: bool = False, limit: int = 0) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36", "Accept-Language": "es-ES"})
    total = 0

    log.info("═" * 60)
    log.info("MOBILIA_A — True /ficha/ sites (%d)", len(SITES_MOBILIA_A))
    for site in SITES_MOBILIA_A:
        log.info("→ %s", site["name"])
        total += _run_site(site, _links_mobilia_a, "pag", session, dry_run)

    log.info("═" * 60)
    log.info("MOBILIA_DETALLE — JCInmo /detalle/ sites (%d)", len(SITES_MOBILIA_DETALLE))
    for site in SITES_MOBILIA_DETALLE:
        log.info("→ %s", site["name"])
        total += _run_site(site, _links_jcinmo, "p", session, dry_run)

    log.info("═" * 60)
    log.info("EBRORIVER — /detalles-es/ sites (%d)", len(SITES_EBRORIVER))
    for site in SITES_EBRORIVER:
        log.info("→ %s", site["name"])
        total += _run_site(site, _links_ebroriver, "pag", session, dry_run)

    log.info("═" * 60)
    log.info("EBREPISOS — Drupal /propietat/ sites (%d)", len(SITES_EBREPISOS))
    for site in SITES_EBREPISOS:
        log.info("→ %s", site["name"])
        # Drupal pagination is 0-indexed: page=0 = first, page=1 = second
        total += _run_site(site, _links_ebrepisos, "page", session, dry_run, page0=0)

    log.info("═" * 60)
    log.info("DELTAEBRO — Custom CMS (%d)", len(SITES_DELTAEBRO))
    for site in SITES_DELTAEBRO:
        log.info("→ %s", site["name"])
        total += _run_site(site, _links_deltaebro, "page", session, dry_run)

    log.info("═" * 60)
    log.info("ACTIVEHOUSE — JSON-LD embedded (%d)", len(SITES_ACTIVEHOUSE))
    for site in SITES_ACTIVEHOUSE:
        log.info("→ %s", site["name"])
        name = site["name"]
        processed = load_processed_urls(name)
        for page in range(1, MAX_PAGES_PER_SITE + 1):
            url = _page_url(site["url"], page, "pag")
            html = fetch_html(url, session)
            if not html:
                break
            listings = _listings_activehouse_from_jsonld(html, name, site["url"])
            if not listings:
                break
            for listing in listings:
                if listing.get("url") not in processed:
                    if not dry_run:
                        append_listing(name, listing)
                    total += 1
            time.sleep(random.uniform(2, 4))

    log.info("═" * 60)
    log.info("INMOWEB_SEO — data-url -esNNNNN.html (%d)", len(SITES_INMOWEB_SEO))
    for site in SITES_INMOWEB_SEO:
        log.info("→ %s", site["name"])
        total += _run_site(site, _links_inmoweb_seo, "pag", session, dry_run)

    log.info("═" * 60)
    log.info("MOBILIA ALL STATIC: %d listings added", total)
    return []
