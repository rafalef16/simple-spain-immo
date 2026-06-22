#!/usr/bin/env python3
"""
scrape_v2 — Moteur de scraping DÉCOUPLÉ (Phase A: découverte d'URLs → Phase B: extraction).

Principe directeur ("the one thing"): on extrait le JSON-LD embarqué
(<script type="application/ld+json">), pas le DOM visuel. Les classes CSS cassent,
les clés JSON-LD ne bougent jamais (Google en dépend).

Stratégie par site (réduction max de la data exploitée):
  - thinkspain / kyero : requests + EVOMI, JSON-LD pur (zéro navigateur).
  - fotocasa / idealista : Playwright + EVOMI (anti-bot), JSON-LD puis fallback DOM.
  - finquesmar (Mobilia) : Playwright sans proxy (SPA React, agence locale).

Anti-détection: rotation hardsession EVOMI tous les N, délais humains aléatoires,
blocage images/fonts/media, navigator.webdriver masqué, cookies auto, détection captcha.

Usage:
  python3 scrape_v2.py --site all --limit 10
  python3 scrape_v2.py --site kyero --phase discover
  python3 scrape_v2.py --site idealista --phase extract   # consomme data/seeds/idealista.txt
"""
import os
import re
import json
import time
import random
import string
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

BASE = Path(__file__).parent
load_dotenv(BASE / ".env", override=True)  # charge .env avant tout os.getenv()
SEEDS_DIR = BASE / "data" / "seeds"
OUT_DIR = BASE / "data" / "v2"
SEEDS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scrape_v2")

# ── EVOMI ───────────────────────────────────────────────────────────────────
EVOMI_SERVER = "core-residential.evomi.com:1000"
EVOMI_USER = os.getenv("EVOMI_USER", "samueldomi6")
EVOMI_PASS_BASE = os.getenv("EVOMI_PASS", "DSfzAOkqIjfgPqQhcD5h_country-ES")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

ROTATE_EVERY = 10        # switch d'IP EVOMI toutes les N annonces
MAX_DISCOVERY_PAGES = 60  # garde-fou pagination profonde


def _session_id() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def _evomi_pass(hard: bool = True) -> str:
    return f"{EVOMI_PASS_BASE}_hardsession-{_session_id()}" if hard else EVOMI_PASS_BASE


def _requests_session(hard: bool = True) -> requests.Session:
    s = requests.Session()
    pw = _evomi_pass(hard)
    proxy = f"http://{EVOMI_USER}:{pw}@{EVOMI_SERVER}"
    s.proxies = {"http": proxy, "https": proxy}
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.es/",
    })
    return s


def human_delay(a: float = 2.0, b: float = 5.0):
    time.sleep(random.uniform(a, b))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
#  COUCHE RÉSEAU DATADOME-AWARE : Spear (curl_cffi, TLS spoof) + Shield (browser)
#  Le Spear fait des requêtes HTTP légères (économie proxy max). Si un portail
#  bloque (403 / challenge DataDome), le Shield lance un navigateur, passe le
#  challenge (2captcha si nécessaire), récolte le cookie 'datadome', puis le Spear
#  réessaie avec ce cookie. Inactif sur les sites sans anti-bot (ThinkSpain/Kyero).
# ══════════════════════════════════════════════════════════════════════════════
import threading
from curl_cffi import requests as cffi

TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY") or ""
IMPERSONATE = "chrome"
SESSION_POOL = OUT_DIR / "session_pool.json"
_pool_lock = threading.Lock()


def _load_pool() -> dict:
    if SESSION_POOL.exists():
        try:
            return json.loads(SESSION_POOL.read_text())
        except Exception:
            return {}
    return {}


def _save_session(site: str, cookies: dict, ua: str, proxy_pw: str | None = None):
    with _pool_lock:
        pool = _load_pool()
        pool[site] = {"cookies": cookies, "ua": ua, "ts": now_iso()}
        if proxy_pw:
            pool[site]["proxy_pw"] = proxy_pw  # même IP obligatoire pour les cookies DataDome
        SESSION_POOL.write_text(json.dumps(pool, ensure_ascii=False, indent=2))


def _spear_get(url: str, cookies: dict | None, ua: str | None, proxy_pw: str | None = None):
    # Si on a un proxy_pw sauvegardé par le Shield, on DOIT le réutiliser (même IP = même DataDome cookie)
    pw = proxy_pw or _evomi_pass(True)
    proxy = f"http://{EVOMI_USER}:{pw}@{EVOMI_SERVER}"
    headers = {
        "User-Agent": ua or UA,
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.es/",
    }
    return cffi.get(url, impersonate=IMPERSONATE, headers=headers,
                    cookies=cookies or {}, proxies={"http": proxy, "https": proxy},
                    timeout=30)


def net_get(url: str, site: str, _retry: bool = True) -> str | None:
    """Fetch unifié. Renvoie le HTML ou None. Déclenche le Shield si bloqué."""
    pool = _load_pool().get(site, {})
    try:
        r = _spear_get(url, pool.get("cookies"), pool.get("ua"), pool.get("proxy_pw"))
    except Exception as e:
        log.warning("[%s] spear err: %s", site, e)
        return None
    if r.status_code == 404:
        log.warning("[%s] 404 (annonce supprimée): %s", site, url)
        return None  # pas un blocage — ne pas déclencher Shield
    if r.status_code == 200 and not _is_blocked(r.text):
        return r.text
    if not _retry:
        log.warning("[%s] toujours bloqué après Shield (status=%s)", site, r.status_code)
        return None
    log.warning("[%s] bloqué (status=%s) → activation Shield", site, r.status_code)
    if not shield_refresh(site, url):
        return None
    return net_get(url, site, _retry=False)


def _apply_stealth(page):
    """Applique playwright-stealth + patches manuels anti-DataDome."""
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
    except Exception:
        pass
    page.add_init_script("""
        Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
        Object.defineProperty(navigator,'languages',{get:()=>['es-ES','es','en']});
        Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>8});
        Object.defineProperty(navigator,'deviceMemory',{get:()=>8});
        Object.defineProperty(navigator,'platform',{get:()=>'MacIntel'});
        Object.defineProperty(screen,'width',{get:()=>1920});
        Object.defineProperty(screen,'height',{get:()=>1080});
        Object.defineProperty(screen,'colorDepth',{get:()=>24});
        const originalQuery=window.navigator.permissions.query;
        window.navigator.permissions.query=(parameters)=>(
            parameters.name==='notifications'
                ? Promise.resolve({state:Notification.permission})
                : originalQuery(parameters)
        );
        window.chrome={runtime:{}};
    """)


def shield_refresh(site: str, url: str) -> dict | None:
    """Navigateur furtif Chrome réel + stealth : passe DataDome, récolte les cookies."""
    from playwright.sync_api import sync_playwright
    sid = _session_id()
    proxy_pw = _evomi_pass(True)
    with sync_playwright() as p:
        # Chrome réel headless=False : GPU réel → passe DataDome i.js fingerprinting
        try:
            ctx = p.chromium.launch_persistent_context(
                f"/tmp/shield_{sid}", headless=False, channel="chrome",
                proxy={"server": f"http://{EVOMI_SERVER}", "username": EVOMI_USER,
                       "password": proxy_pw},
                locale="es-ES", timezone_id="Europe/Madrid", user_agent=UA,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                      "--disable-dev-shm-usage", "--window-position=0,0",
                      "--window-size=1280,900"])
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                f"/tmp/shield_{sid}b", headless=False,
                proxy={"server": f"http://{EVOMI_SERVER}", "username": EVOMI_USER,
                       "password": proxy_pw},
                locale="es-ES", timezone_id="Europe/Madrid", user_agent=UA,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        page = ctx.new_page()
        _apply_stealth(page)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(8)
            _accept_cookies(page)
            if _is_blocked(page.content()):
                if not TWOCAPTCHA_API_KEY:
                    log.error("[%s] Shield: challenge DataDome mais TWOCAPTCHA_API_KEY absente", site)
                    return None
                if not _solve_datadome(page, url, proxy_pw):
                    log.error("[%s] Shield: échec résolution 2captcha", site)
                    return None
                time.sleep(3)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(4)
            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            _save_session(site, cookies, UA, proxy_pw=proxy_pw)
            log.info("[%s] Shield: session OK (%d cookies)", site, len(cookies))
            return cookies
        except Exception as e:
            log.error("[%s] Shield err: %s", site, e)
            return None
        finally:
            ctx.close()


def _solve_datadome(page, page_url: str, proxy_pw: str | None = None) -> bool:
    """Résout un challenge DataDome via 2captcha (datadome method).
    proxy_pw doit être le MÊME password que celui utilisé par le navigateur (même IP)."""
    try:
        from twocaptcha import TwoCaptcha
    except Exception:
        log.error("SDK 2captcha absent → pip install 2captcha-python")
        return False
    # Attendre que DataDome charge son iframe (async JS post-DOM)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(3)
    content = page.content()
    challenge_url = None
    # 1) Chercher dans le HTML brut
    m = re.search(r'(https://geo\.captcha-delivery\.com/captcha/\?[^"\'\s<>]+)', content)
    if m:
        challenge_url = m.group(1)
    if not challenge_url:
        # 2) Chercher dans les frames (DataDome charge souvent via iframe)
        for frame in page.frames:
            if "captcha-delivery.com" in frame.url:
                challenge_url = frame.url
                break
    if not challenge_url:
        # 3) Chercher dans les requêtes réseau interceptées via JS
        try:
            challenge_url = page.evaluate("""() => {
                const iframes = document.querySelectorAll('iframe[src*="captcha-delivery"]');
                return iframes.length ? iframes[0].src : null;
            }""")
        except Exception:
            pass
    if not challenge_url:
        log.error("URL de challenge DataDome introuvable (HTML + frames + DOM)")
        return False
    log.info("2captcha: soumission challenge %s...", challenge_url[:80])
    # Utiliser le MÊME proxy que le navigateur (même IP = même session DataDome)
    pw = proxy_pw or _evomi_pass(True)
    solver = TwoCaptcha(TWOCAPTCHA_API_KEY)
    solver.default_timeout = 300   # DataDome peut prendre jusqu'à 3-4min
    solver.recaptcha_timeout = 300
    try:
        res = solver.datadome(
            captcha_url=challenge_url, pageurl=page_url, userAgent=UA,
            proxy={"type": "HTTP", "uri": f"{EVOMI_USER}:{pw}@{EVOMI_SERVER}"})
        token = res.get("code") if isinstance(res, dict) else None
        if token:
            domain = re.sub(r'^https?://(www\.)?', '', page_url).split("/")[0]
            page.context.add_cookies([{
                "name": "datadome", "value": token,
                "domain": "." + domain, "path": "/"}])
            log.info("2captcha: token DataDome injecté (domaine=%s)", domain)
            return True
        log.error("2captcha: réponse sans token: %s", res)
    except Exception as e:
        log.error("2captcha datadome err: %s", e)
    return False


# ── JSON-LD : le "one thing" ──────────────────────────────────────────────────
def extract_jsonld(html: str) -> list[dict]:
    """Retourne tous les objets JSON-LD d'une page (à plat)."""
    out = []
    for block in re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                out.extend(x for x in data["@graph"] if isinstance(x, dict))
            else:
                out.append(data)
    return out


def jsonld_of_type(blocks: list[dict], *types: str) -> dict | None:
    want = {t.lower() for t in types}
    for b in blocks:
        t = b.get("@type", "")
        tl = [t.lower()] if isinstance(t, str) else [x.lower() for x in t]
        if want & set(tl):
            return b
    return None


def parse_int(s) -> int | None:
    if s is None:
        return None
    m = re.search(r'(\d[\d.\s]*)', str(s).replace(",", ""))
    if not m:
        return None
    try:
        return int(re.sub(r'[^\d]', '', m.group(1)))
    except Exception:
        return None


def first_price_eur(html: str) -> int | None:
    """Trouve un prix € plausible dans le HTML (fallback DOM)."""
    for m in re.findall(r'(\d{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*€', html):
        v = parse_int(m)
        if v and 5_000 <= v <= 9_000_000:
            return v
    return None


# ── Playwright helper ─────────────────────────────────────────────────────────
def _new_context(p, use_proxy: bool, hard: bool = True, proxy_pw: str | None = None):
    kwargs = dict(
        headless=True,
        ignore_https_errors=True,
        locale="es-ES",
        timezone_id="Europe/Madrid",
        user_agent=UA,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    if use_proxy:
        pw = proxy_pw or _evomi_pass(hard)
        kwargs["proxy"] = {
            "server": f"http://{EVOMI_SERVER}",
            "username": EVOMI_USER,
            "password": pw,
        }
    ctx = p.chromium.launch_persistent_context(f"/tmp/v2_{_session_id()}", **kwargs)
    return ctx


def _new_page(ctx):
    page = ctx.new_page()
    # Réduction data + non-détection : on coupe images/fonts/media
    page.route("**/*", lambda r: (
        r.abort() if r.request.resource_type in ("image", "font", "media") else r.continue_()
    ))
    page.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return page


def _accept_cookies(page):
    for sel in ["#didomi-notice-agree-button", "#onetrust-accept-btn-handler",
                "button#aceptar", "[data-testid='TcfAccept']"]:
        try:
            page.click(sel, timeout=2500)
            return
        except Exception:
            pass
    for name in ("Aceptar todas", "Aceptar", "Aceptar y cerrar", "Aceptar todo", "Accept"):
        try:
            page.get_by_role("button", name=re.compile(name, re.I)).click(timeout=2000)
            return
        except Exception:
            pass


def _is_blocked(html: str) -> bool:
    """Détecte une page de challenge DataDome — pas juste la présence du script tracker.
    "datadome" apparaît sur TOUTES les pages qui l'utilisent (tracking JS) → faux positif.
    On cible les indicateurs du challenge réel : iframe captcha-delivery, messages d'erreur."""
    h = html.lower()
    if len(html) < 1500:  # réponse tronquée / blocage HTTP
        return True
    if "geo.captcha-delivery.com" in h:  # iframe/URL du challenge DataDome
        return True
    if "sentimos la interrup" in h or "unusual traffic" in h:
        return True
    if 'class="dd-' in h and len(html) < 8000:  # page challenge DataDome (dd-desktop, dd-mobile)
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE A — DÉCOUVERTE D'URLS (par site)
# ══════════════════════════════════════════════════════════════════════════════
LISTING_URLS = {
    "finquesmar": "https://finquesmar.es",
}


def discover_thinkspain(limit: int) -> list[str]:
    import config
    urls = []
    for site_cfg in config.SITES_THINKSPAIN:
        base = site_cfg["url"]
        for pg in range(1, MAX_DISCOVERY_PAGES + 1):
            u = base + (f"&page={pg}" if pg > 1 else "")
            html = net_get(u, "thinkspain")
            if not html:
                break
            found = [f"https://www.thinkspain.com{p}"
                     for p in re.findall(r'href="(/property-for-sale/\d+)"', html)]
            new = [x for x in dict.fromkeys(found) if x not in urls]
            if not new:
                log.info("[thinkspain] %s p%d: 0 nouvelle URL → fin", site_cfg["name"], pg)
                break
            urls.extend(new)
            log.info("[thinkspain] %s p%d: +%d (cumul %d)", site_cfg["name"], pg, len(new), len(urls))
            if limit and len(urls) >= limit:
                break
        if limit and len(urls) >= limit:
            break
        human_delay()
    return urls[:limit] if limit else urls


def discover_kyero(limit: int) -> list[str]:
    import config
    urls = []
    for site_cfg in config.SITES_KYERO:
        base = site_cfg["url"]
        for pg in range(1, MAX_DISCOVERY_PAGES + 1):
            u = base + (f"?page={pg}" if pg > 1 else "")
            html = net_get(u, "kyero")
            if not html:
                break
            found = [f"https://www.kyero.com{p}" if p.startswith("/") else p
                     for p in re.findall(r'href="(/[a-z]{2}/property/\d+[^"]*)"', html)]
            new = [x for x in dict.fromkeys(found) if x not in urls]
            if not new:
                log.info("[kyero] %s p%d: 0 nouvelle URL → fin", site_cfg["name"], pg)
                break
            urls.extend(new)
            log.info("[kyero] %s p%d: +%d (cumul %d)", site_cfg["name"], pg, len(new), len(urls))
            if limit and len(urls) >= limit:
                break
        if limit and len(urls) >= limit:
            break
        human_delay()
    return urls[:limit] if limit else urls


def discover_fotocasa(limit: int) -> list[str]:
    from playwright.sync_api import sync_playwright
    import config
    urls = []
    with sync_playwright() as p:
        ctx = _new_context(p, use_proxy=True)
        page = _new_page(ctx)
        try:
            for site_cfg in config.SITES_FOTOCASA:
                base = site_cfg["url"]
                for pg in range(1, MAX_DISCOVERY_PAGES + 1):
                    # pagination /l/N en insérant /N après /l (avant la query string)
                    pg_url = base if pg == 1 else re.sub(r'/l(\?|$)', f'/l/{pg}\\1', base)
                    page.goto(pg_url, wait_until="domcontentloaded", timeout=60000)
                    human_delay(3, 5)
                    _accept_cookies(page)
                    for _ in range(4):
                        page.mouse.wheel(0, 3000)
                        human_delay(1, 2)
                    if _is_blocked(page.content()):
                        log.warning("[fotocasa] bloqué %s p%d", site_cfg["name"], pg)
                        break
                    hrefs = page.eval_on_selector_all(
                        "a[href]", "els=>els.map(e=>e.getAttribute('href'))")
                    before = len(urls)
                    for h in hrefs:
                        if not h:
                            continue
                        m = re.search(r'(/es/comprar/[^/]+/[^/]+/[^/]+/\d+)/d', h)
                        if m:
                            full = "https://www.fotocasa.es" + m.group(1) + "/d"
                            if full not in urls:
                                urls.append(full)
                    added = len(urls) - before
                    log.info("[fotocasa] %s p%d: +%d (cumul %d)",
                             site_cfg["name"], pg, added, len(urls))
                    if added == 0:
                        break
                    if limit and len(urls) >= limit:
                        break
                if limit and len(urls) >= limit:
                    break
        finally:
            ctx.close()
    return urls[:limit] if limit else urls


def discover_finquesmar(limit: int) -> list[str]:
    from playwright.sync_api import sync_playwright
    urls = []
    with sync_playwright() as p:
        ctx = _new_context(p, use_proxy=False)  # agence locale, pas d'anti-bot
        page = _new_page(ctx)
        try:
            page.goto(LISTING_URLS["finquesmar"], wait_until="networkidle", timeout=45000)
            human_delay(3, 5)
            # SPA : scroll progressif jusqu'à stabilisation du nb de liens (infinite scroll)
            # On filtre sur /es/propiedad/<slug>-<id> (singulier, avec numéro d'ID final)
            pat = re.compile(r'/es/propiedad/[a-z0-9-]+-\d+$', re.I)
            last = -1
            for _ in range(MAX_DISCOVERY_PAGES):
                hrefs = page.eval_on_selector_all("a[href]", "els=>els.map(e=>e.href)")
                cur = [h.split("?")[0] for h in dict.fromkeys(hrefs)
                       if pat.search(h.split("?")[0]) and "finquesmar.es" in h]
                if len(cur) == last:
                    break
                last = len(cur)
                page.mouse.wheel(0, 5000)
                human_delay(1, 2)
            urls = cur
            log.info("[finquesmar] %d URLs candidates (scroll stabilisé)", len(urls))
        finally:
            ctx.close()
    return urls[:limit] if limit else urls


IDEALISTA_SEARCH_URLS = [
    # Polygone Catalogne ciblé — chalets indépendants + maisons de village
    "https://www.idealista.com/areas/venta-viviendas/con-chalets-independientes,casas-de-pueblo/?shape=%28%28snruFciw%40gsoAor%40%7B%7D%7C%40spd%40miLytyDrpq%40ePfcyBxwiEiwOhrV%29%29",
    # Maisons rurales de village
    "https://www.idealista.com/areas/venta-viviendas/con-casas-de-pueblo/?shape=%28%28snruFciw%40gsoAor%40%7B%7D%7C%40spd%40miLytyDrpq%40ePfcyBxwiEiwOhrV%29%29",
    # Terrains rusticos > 5000m²
    "https://www.idealista.com/areas/venta-terrenos/con-metros-cuadrados-mas-de_5000,terrenos-no-urbanizables/?shape=%28%28snruFciw%40gsoAor%40%7B%7D%7C%40spd%40miLytyDrpq%40ePfcyBxwiEiwOhrV%29%29",
]

_IDEALISTA_WARMUP = [
    "https://www.idealista.com/",
    "https://www.idealista.com/areas/venta-viviendas/con-casas-de-pueblo/?shape=%28%28snruFciw%40gsoAor%40%7B%7D%7C%40spd%40miLytyDrpq%40ePfcyBxwiEiwOhrV%29%29",
]


def _idealista_extract_links(page) -> list[str]:
    hrefs = page.eval_on_selector_all("a[href]", "els=>els.map(e=>e.getAttribute('href'))")
    found = []
    for h in hrefs:
        if not h:
            continue
        m = re.search(r'(/inmueble/\d+/)', h)
        if m:
            full = "https://www.idealista.com" + m.group(1)
            if full not in found:
                found.append(full)
    return found


def discover_idealista(limit: int) -> list[str]:
    """Découverte Idealista via Chrome+stealth (warm-up homepage → search)."""
    from playwright.sync_api import sync_playwright
    seed = SEEDS_DIR / "idealista.txt"
    known = []
    if seed.exists():
        known = [l.strip() for l in seed.read_text().splitlines()
                 if l.strip().startswith("http")]

    urls: list[str] = list(known)

    with sync_playwright() as p:
        _cur_proxy_pw = None  # découverte sans proxy : IP réelle Mac
        sid = _session_id()
        # headless=False : le vrai Chrome avec GPU passe le fingerprinting DataDome i.js
        # (headless=True expose SwiftShader GPU + fonts manquants → score bot trop élevé)
        try:
            ctx = p.chromium.launch_persistent_context(
                f"/tmp/idealista_{sid}", headless=False, channel="chrome",
                locale="es-ES", timezone_id="Europe/Madrid", user_agent=UA,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                      "--disable-dev-shm-usage", "--window-position=0,0",
                      "--window-size=1280,900"])
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                f"/tmp/idealista_{sid}b", headless=False,
                locale="es-ES", timezone_id="Europe/Madrid", user_agent=UA,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        page = _new_page(ctx)
        _apply_stealth(page)
        try:
            # Warm-up : homepage → comportement humain avant d'attaquer la recherche
            for wu_url in _IDEALISTA_WARMUP:
                try:
                    page.goto(wu_url, wait_until="domcontentloaded", timeout=45000)
                    human_delay(4, 7)
                    _accept_cookies(page)
                    # Simuler une lecture humaine : scroll
                    for _ in range(3):
                        page.mouse.wheel(0, random.randint(300, 800))
                        human_delay(1, 2)
                    # Extraire des liens même sur la homepage (peut avoir des fiches)
                    for link in _idealista_extract_links(page):
                        if link not in urls:
                            urls.append(link)
                    if _is_blocked(page.content()):
                        log.warning("[idealista] warm-up bloqué sur %s", wu_url)
                        break
                except Exception as e:
                    log.warning("[idealista] warm-up err: %s", e)

            # Sauvegarder la session warm-up (cookies DataDome)
            warmup_cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            _save_session("idealista", warmup_cookies, UA, proxy_pw=_cur_proxy_pw)

            if limit and len(urls) >= limit:
                return urls[:limit]

            # Recherche paginée
            for base in IDEALISTA_SEARCH_URLS:
                if limit and len(urls) >= limit:
                    break
                for pg in range(1, MAX_DISCOVERY_PAGES + 1):
                    pg_url = base if pg == 1 else base + f"pagina-{pg}.htm"
                    try:
                        page.goto(pg_url, wait_until="domcontentloaded", timeout=60000)
                    except Exception as e:
                        log.warning("[idealista] goto err: %s", e)
                        break
                    human_delay(5, 10)
                    _accept_cookies(page)
                    content = page.content()
                    if _is_blocked(content):
                        log.warning("[idealista] bloqué sur search p%d", pg)
                        break
                    before = len(urls)
                    for link in _idealista_extract_links(page):
                        if link not in urls:
                            urls.append(link)
                    added = len(urls) - before
                    log.info("[idealista] search p%d: +%d (cumul %d)", pg, added, len(urls))
                    if added == 0:
                        break
                    if limit and len(urls) >= limit:
                        break
                    human_delay(8, 15)

        except Exception as e:
            log.error("[idealista] découverte err: %s", e)
        finally:
            ctx.close()

    if not urls:
        log.warning("[idealista] 0 URL découvertes")
    return urls[:limit] if limit else urls


DISCOVERERS = {
    "thinkspain": discover_thinkspain,
    "kyero": discover_kyero,
    "fotocasa": discover_fotocasa,
    "finquesmar": discover_finquesmar,
    "idealista": discover_idealista,
}


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE B — EXTRACTION (par site) — JSON-LD first
# ══════════════════════════════════════════════════════════════════════════════
def _base_record(url: str, site: str) -> dict:
    return {
        "url": url, "site": site, "title": None, "price_eur": None,
        "surface_m2": None, "built_m2": None, "terrain_m2": None,
        "bedrooms": None, "bathrooms": None,
        "lat": None, "lon": None, "ref": None, "description": None,
        "image": None, "date_posted": None, "scrap_ts": now_iso(),
    }


def _clean_ville(raw) -> str | None:
    """Ville canonique : on ne garde QUE le texte avant la 1ère virgule, nettoyé.
    Ex: « Tortosa, Tarragona, Catalonia, España » → « Tortosa »."""
    if not raw:
        return None
    v = _strip_tags(str(raw)).split(",")[0].strip()
    v = re.sub(r"\s+", " ", v).strip(" -·|")
    return v.title() if v else None


def parse_idealista_html(html: str, url: str) -> dict | None:
    """Extraction DOM Idealista (pas de JSON-LD sur les fiches)."""
    from bs4 import BeautifulSoup
    bs = BeautifulSoup(html, "html.parser")
    rec = _base_record(url, "idealista")

    el = bs.select_one(".info-data-price")
    if el:
        rec["price_eur"] = parse_int(el.get_text())
        log.debug("[idealista] prix: %s€", rec["price_eur"])
    el = bs.select_one(".main-info__title-main") or bs.select_one("h1")
    if el:
        rec["title"] = el.get_text(" ", strip=True)
        log.debug("[idealista] title: %s", rec["title"][:60])
    # Ville : <span class="main-info__title-minor">Tortosa</span>
    el = bs.select_one(".main-info__title-minor")
    if el:
        rec["ville"] = _clean_ville(el.get_text(" ", strip=True))
        log.debug("[idealista] ville: %s", rec["ville"])
    el = bs.select_one(".comment") or bs.select_one("div.adCommentsLanguage")
    if el:
        rec["description"] = el.get_text(" ", strip=True)
    if not rec["description"]:
        rec["description"] = extract_description(html)

    # Surfaces / pièces depuis la liste de caractéristiques
    for li in bs.select(".details-property-feature-one li, [class*=feature] li"):
        t = li.get_text(" ", strip=True).lower()
        if "construido" in t and rec["built_m2"] is None:
            rec["built_m2"] = parse_int(t)
        if ("parcela" in t or "terreno" in t or "suelo" in t) and rec["terrain_m2"] is None:
            rec["terrain_m2"] = parse_int(t)
        if "habitacion" in t and rec["bedrooms"] is None:
            rec["bedrooms"] = parse_int(t)
        if ("baño" in t or "bano" in t) and rec["bathrooms"] is None:
            rec["bathrooms"] = parse_int(t)
    _apply_surfaces(rec)

    m = re.search(r'/inmueble/(\d+)', url)
    rec["ref"] = m.group(1) if m else None
    img = bs.select_one("meta[property='og:image']")
    if img and img.get("content"):
        rec["image"] = img["content"]
    return rec


def parse_thinkspain_html(html: str, url: str) -> dict | None:
    prod = jsonld_of_type(extract_jsonld(html), "Product")
    if not prod:
        return None
    rec = _base_record(url, "thinkspain")
    rec["title"] = prod.get("name")
    rec["description"] = prod.get("description")
    # Description complète : <p class="property-description"> (le JSON-LD est tronqué
    # par le bouton "Read More"). On garde la plus longue des deux.
    pm = re.search(r'<p[^>]*class=["\'][^"\']*property-description[^"\']*["\'][^>]*>(.*?)</p>',
                   html, re.I | re.S)
    if pm:
        full = _strip_tags(pm.group(1).replace("<br>", " ").replace("<br/>", " "))
        if len(full) > len(rec["description"] or ""):
            rec["description"] = full
    rec["image"] = prod.get("image")
    rec["ref"] = prod.get("productID")
    offer = prod.get("offers") or {}
    rec["price_eur"] = parse_int(offer.get("price"))
    # Ville : <span class="locationProximity">Tortosa, Tarragone</span> → avant virgule
    vm = re.search(r'<span[^>]*class=["\'][^"\']*locationProximity[^"\']*["\'][^>]*>(.*?)</span>',
                   html, re.I | re.S)
    if vm:
        rec["ville"] = _clean_ville(vm.group(1))
    _apply_surfaces(rec)
    return rec


def parse_kyero_html(html: str, url: str) -> dict | None:
    blocks = extract_jsonld(html)
    res = jsonld_of_type(blocks, "SingleFamilyResidence", "Residence", "House", "Product")
    if not res:
        return None
    rec = _base_record(url, "kyero")
    rec["title"] = res.get("name")
    rec["description"] = res.get("description")
    rec["image"] = res.get("image")
    rec["lat"] = res.get("latitude")
    rec["lon"] = res.get("longitude")
    rec["bedrooms"] = parse_int(res.get("numberOfBedrooms"))
    rec["bathrooms"] = parse_int(res.get("numberOfBathroomsTotal"))
    fs = res.get("floorSize") or {}
    built_jsonld = parse_int(fs.get("value") if isinstance(fs, dict) else fs)
    # floorSize Kyero = surface bâtie ; classer selon la règle <400/>400
    if built_jsonld and built_jsonld <= 400:
        rec["built_m2"] = built_jsonld
    elif built_jsonld:
        rec["terrain_m2"] = built_jsonld
    listing = jsonld_of_type(blocks, "RealEstateListing")
    if listing and listing.get("datePosted"):
        rec["date_posted"] = listing["datePosted"]
    mp = re.search(r'"price"\s*:\s*"?(\d{4,8})', html)
    rec["price_eur"] = parse_int(mp.group(1)) if mp else first_price_eur(html)
    # Ville : <p>Tortosa, Tarragona, Catalonia, España</p> → avant virgule.
    # JSON-LD address en priorité (plus fiable), sinon le <p> de localisation.
    addr = res.get("address") if isinstance(res, dict) else None
    if isinstance(addr, dict) and addr.get("addressLocality"):
        rec["ville"] = _clean_ville(addr["addressLocality"])
    if not rec.get("ville"):
        vm = re.search(r'<p[^>]*>\s*([^<,]+),\s*Tarragona\s*,\s*Catal', html, re.I)
        if vm:
            rec["ville"] = _clean_ville(vm.group(1))
    _apply_surfaces(rec)
    return rec


def parse_fotocasa_html(html: str, url: str) -> dict | None:
    from bs4 import BeautifulSoup
    bs = BeautifulSoup(html, "html.parser")
    rec = _base_record(url, "fotocasa")
    h1 = bs.select_one("h1")
    if h1:
        rec["title"] = h1.get_text(" ", strip=True)
    # Ville : <p class="re-DetailHeader-municipalityTitle">Tortosa</p>
    vt = bs.select_one(".re-DetailHeader-municipalityTitle, [class*=municipalityTitle]")
    if vt:
        rec["ville"] = _clean_ville(vt.get_text(" ", strip=True))
    desc = bs.select_one(".re-DetailDescriptionContainer, [class*=DetailDescription]")
    if desc:
        rec["description"] = desc.get_text(" ", strip=True)
    if not rec["description"]:
        rec["description"] = extract_description(html)
    rec["price_eur"] = first_price_eur(html)
    photos = list(dict.fromkeys(
        re.findall(r'https://static\.fotocasa\.es/images/ads/[a-z0-9-]+', html)))
    if photos:
        rec["image"] = photos[0] + "?rule=web_948x542_ar"
    m = re.search(r'/(\d+)/d', url)
    rec["ref"] = m.group(1) if m else None
    # surfaces depuis le bloc de features
    for li in bs.select(".re-DetailFeaturesList li, [class*=Features] li, [class*=feature] li"):
        t = li.get_text(" ", strip=True).lower()
        if any(w in t for w in ("terreno", "parcela", "suelo")) and rec["terrain_m2"] is None:
            rec["terrain_m2"] = parse_int(t)
        if "construid" in t and rec["built_m2"] is None:
            rec["built_m2"] = parse_int(t)
    _apply_surfaces(rec)
    return rec


# Parsers HTML par site (consommés via net_get → couche DataDome-aware)
HTML_PARSERS = {
    "thinkspain": parse_thinkspain_html,
    "kyero": parse_kyero_html,
    "fotocasa": parse_fotocasa_html,
    "idealista": parse_idealista_html,
}


def _extract_via_playwright(url: str, site: str, use_proxy: bool, ctx) -> dict | None:
    page = _new_page(ctx)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        human_delay(3, 6)
        _accept_cookies(page)
        html = page.content()
        if _is_blocked(html):
            log.warning("[%s] bloqué: %s", site, url)
            return None
        if site == "idealista":
            return parse_idealista_html(html, url)
        rec = _base_record(url, site)
        blocks = extract_jsonld(html)
        obj = jsonld_of_type(blocks, "Product", "SingleFamilyResidence",
                             "Residence", "House", "Place", "Offer")
        if obj:
            rec["title"] = obj.get("name")
            rec["description"] = obj.get("description")
            img = obj.get("image")
            rec["image"] = img[0] if isinstance(img, list) and img else img
            offer = obj.get("offers") or {}
            rec["price_eur"] = parse_int(offer.get("price")) if isinstance(offer, dict) else None
        # Fallbacks DOM
        if not rec["price_eur"]:
            rec["price_eur"] = first_price_eur(html)
        if not rec["title"]:
            h1 = page.locator("h1")
            if h1.count():
                rec["title"] = h1.first.inner_text().strip()
        if site == "fotocasa":
            photos = list(dict.fromkeys(re.findall(
                r'https://static\.fotocasa\.es/images/ads/[a-z0-9-]+', html)))
            if photos:
                rec["image"] = photos[0] + "?rule=web_948x542_ar"
        return rec
    except Exception as e:
        log.warning("[%s] erreur %s: %s", site, url, e)
        return None
    finally:
        page.close()


def extract_playwright_site(site: str, urls: list[str], use_proxy: bool) -> list[dict]:
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        ctx = _new_context(p, use_proxy=use_proxy)
        try:
            for i, url in enumerate(urls):
                if i and i % ROTATE_EVERY == 0 and use_proxy:
                    ctx.close()
                    ctx = _new_context(p, use_proxy=True)  # switch IP EVOMI
                    log.info("[%s] rotation IP EVOMI", site)
                rec = _extract_via_playwright(url, site, use_proxy, ctx)
                if rec:
                    out.append(rec)
                    log.info("[%s] [%d/%d] OK prix=%s", site, i + 1, len(urls), rec.get("price_eur"))
                else:
                    log.info("[%s] [%d/%d] vide", site, i + 1, len(urls))
                human_delay(2, 5)
        finally:
            ctx.close()
    return out


def extract_net_site(site: str, urls: list[str]) -> list[dict]:
    """Extraction via couche DataDome-aware (curl_cffi + Shield). Économie proxy max.
    Idealista : on ne rotate PAS le proxy (cookie DataDome lié à l'IP du Shield)."""
    parser = HTML_PARSERS[site]
    out = []
    for i, url in enumerate(urls):
        html = net_get(url, site)
        if not html:
            log.info("[%s] [%d/%d] vide/bloqué", site, i + 1, len(urls))
            human_delay()
            continue
        try:
            rec = parser(html, url)
        except Exception as e:
            log.warning("[%s] [%d/%d] parse err: %s", site, i + 1, len(urls), e)
            rec = None
        if rec:
            out.append(rec)
            log.info("[%s] [%d/%d] OK prix=%s", site, i + 1, len(urls), rec.get("price_eur"))
        else:
            log.info("[%s] [%d/%d] vide", site, i + 1, len(urls))
        # délai gaussien : plus long si match exploitable (comportement humain)
        human_delay(8, 12) if (rec and is_exploitable(rec)) else human_delay(4, 8)
    return out


# ── Validation : on jette les lignes non exploitables ─────────────────────────
def is_exploitable(rec: dict) -> bool:
    filled = sum(bool(rec.get(k)) for k in ("price_eur", "surface_m2", "description"))
    return filled >= 2 or bool(rec.get("price_eur"))


# ══════════════════════════════════════════════════════════════════════════════
#  CATÉGORIE MOBILIA — 37 agences locales (FinquesMar + autres), pattern identique.
#  Extraction EN UNE PASSE depuis la page de résultats (prix/titre/url/ref déjà
#  présents) : curl_cffi sans proxy → rapide et économique. Aucun navigateur.
#    Groupe A (FICHA) : blocs <article> + href contenant /ficha/
#    Groupe B (SEO)   : liens ...-es{N}.html
#  URLs EXACTES (règle stricte, reprises du batch fourni).
# ══════════════════════════════════════════════════════════════════════════════
MOBILIA_FICHA = [
    ("FinquesMar", "https://www.finquesmar.es/index.php?limtipos=6299,6799,899,3699,499,4999,6499,6799&buscador=1"),
    ("HomeIn", "https://www.homein.cat/es/venta-chalets-chalets_independientes"),   # WAF → Couche 3 Evomi
    ("PrimeInmo", "http://www.primeinmo.com/es/venta-chalets~parcela-chalets_independientes~masias~fincas_rusticas"),  # WAF → Couche 3 Evomi
    ("Abonport", "https://www.abonport.es/inmuebles/venta/finca-rustica/tarragona/"),
    ("Prodeltamar_V", "https://www.prodeltamar.es/propiedadesenventa/villas"),
    ("Prodeltamar_R", "https://www.prodeltamar.es/propiedadesenventa/fincasrusticas"),
    ("Elimari", "https://www.grupoelimari.com/inmobiliaria-sant-carles-de-la-rapita-inm.html"),
    ("FinquesRoca", "https://www.finquesroca.com/index.php?limtipos=3699,899,10999,4099&buscador=1"),
    ("ActiveHouse_C", "https://www.activehouseinmo.es/buscador/chalet_rustico/?IdTipoOperacion=0"),
    ("ActiveHouse_R", "https://www.activehouseinmo.es/buscador/finca_rustica/?IdTipoOperacion=0"),
    ("FinquesFarnos", "https://www.finquesfarnos.com/index.php?limtipos=3699,4599,4999,399,499,4099&buscador=1"),
    ("EbreTaxacions", "https://www.ebretaxacions.com/index.php?limtipos=3699,4599,899&buscador=1"),
    ("Esteller", "https://www.estellerconsulting.com/index.php?limtipos=7599,3699,6299,6199,399,499,4099&av=1"),
    ("EbroRiver_1", "https://www.ebroriver.com/es/properties.html?nbreal_category_id=2&type=8"),
    ("EbroRiver_2", "https://www.ebroriver.com/es/properties.html?nbreal_category_id=9&type=8"),
    ("EbroRiver_3", "https://www.ebroriver.com/es/properties.html?nbreal_category_id=1&type=8"),
    ("ViaAugusta_L", "https://www.finquesviaaugusta.com/find/?kind=land&selling=true"),
    ("ViaAugusta_H", "https://www.finquesviaaugusta.com/find/?kind=housing&selling=true"),
    ("Rieres", "https://www.rieres.com/index.php?limtipos=4599,7599,3699,399,499,4999&buscador=1"),
    ("JCInmo_R", "https://www.jcimmobiliaria.cat/buscador/en_venta/finca_rustica/"),
    ("JCInmo_C", "https://www.jcimmobiliaria.cat/buscador/en_venta/chalet/"),
    ("EbrePisos_R", "https://ebrepisos.com/es/aaa?field_type_tid=161"),
    ("ImmoMax_R", "https://www.immomax.es/es/venta-chalets~parcela-casas~fincas_rusticas/en-tarragona-aldover~alfara_de_carles~batea~benifallet~bitem~calafell~camarles~horta_de_sant_joan~jesus~lampolla~pauls~pinell_de_brai_el~raval_de_cristo~reguers_els~roquetes~tivenys~tortosa~ulldecona~xerta"),
    ("LaPlana_R", "https://www.laplanaimmobiliaria.com/inmuebles?key_tipo=finca_rustica"),
    ("DeltaEbro_R", "https://inmobiliaria-deltadelebro.com/es/rustica/venta"),
    ("LaCentral_F", "https://www.lacentralimmobiliaria.com/es-es/pisos-casas-venta-alquiler/fincas?srt=2"),
    ("RusticMar_F", "https://www.rusticmar.info/inmuebles?type=191"),
    ("EbrePisos_53", "https://ebrepisos.com/es/aaa?field_type_tid=53"),
    ("EbrePisos_54", "https://ebrepisos.com/es/aaa?field_type_tid=54"),
    ("EbrePisos_55", "https://ebrepisos.com/es/aaa?field_type_tid=55"),
    ("JCInmo_CR", "https://www.jcimmobiliaria.cat/buscador/en_venta/chalet_rustico/"),
    ("JCInmo_M", "https://www.jcimmobiliaria.cat/buscador/en_venta/masia/"),
    ("ImmoMax_C", "https://www.immomax.es/es/venta-chalets-chalets_independientes"),
    ("LaPlana_C", "https://www.laplanaimmobiliaria.com/inmuebles?key_tipo=finca_rustica_casa"),
    ("LaCentral_V", "https://www.lacentralimmobiliaria.com/es-es/pisos-casas-venta-alquiler/viviendas-casas?srt=2"),
]

MOBILIA_SEO = [
    ("Stanza", "https://www.stanza.es/results/?id_tipo_operacion=1&type%5B%5D=3&type%5B%5D=16&type%5B%5D=9"),
    ("EstebanInmo", "https://www.estebanimmobiliaria.com/results/?id_tipo_operacion=1&type=3%2C9"),
    ("FinquesEbre", "https://www.finquesebre.com/results/?id_tipo_operacion=1&type=3%2C16%2C9"),
]

MOBILIA_WAF = ["HomeIn", "PrimeInmo"]  # WAF bloque datacenter → proxy résidentiel Evomi requis

MOBILIA_MAX_PAGES = 20
# Prix : caractère € OU entité HTML &euro; (certains CMS encodent l'entité)
_PRICE_RE = r"([\d.]+)(?:&nbsp;|\s)*(?:€|&euro;)"


def _mobilia_fetch(url: str, cookies: dict | None = None) -> str | None:
    """GET léger sans proxy (curl_cffi, TLS spoof). Économie maximale.
    `cookies` permet de forcer la langue (ex: JC Inmobiliaria en catalan → es)."""
    try:
        r = cffi.get(url, impersonate=IMPERSONATE,
                     headers={"User-Agent": UA,
                              "Accept-Language": "es-ES,es;q=0.9",
                              "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                     cookies=cookies, timeout=30)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        log.warning("[mobilia] fetch err %s: %s", url, e)
        return None


def _mobilia_fetch_proxy(url: str) -> str | None:
    """GET via proxy résidentiel Evomi (même hardsession que les autres sites).
    Utilisé uniquement pour les WAF qui bloquent les IPs datacenter."""
    try:
        pw = _evomi_pass(hard=True)
        proxy = f"http://{EVOMI_USER}:{pw}@{EVOMI_SERVER}"
        r = cffi.get(url, impersonate=IMPERSONATE,
                     headers={"User-Agent": UA,
                              "Accept-Language": "es-ES,es;q=0.9",
                              "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                     proxies={"http": proxy, "https": proxy},
                     timeout=30)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        log.warning("[mobilia] fetch_proxy err %s: %s", url, e)
        return None


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", s)).strip()


# ── Extraction description complète (générique, multi-CMS, anti-bruit) ──────────
# Phrases qui trahissent un bloc juridique / cookies / formulaire (≠ description bien).
_DESC_NOISE_RE = re.compile(
    r"(\bcookies?\b|t[eé]cnicas?\s+de\s+rastreo"
    r"|pol[ií]tica\s+de\s+(cookies|privacidad|privacitat)"
    r"|utilizamos?\s+cookies|uso\s+de\s+(las\s+)?cookies|preferenc(ias|es)\s+de\s+cookies"
    r"|consentimiento|consentiment|RGPD|GDPR|responsable\s+del\s+tratamiento"
    r"|ficheros?\s+log|archivos?\s+como\s+cookies|deshabilitar\s+las\s+cookies"
    r"|al\s+pulsar\s+el\s+bot[oó]n|acepta\s+las\s+condiciones|t[eé]rminos\s+y\s+condiciones"
    r"|ens\s+preocupa\s+la\s+teva|navegaci[oó]n\s+de\s+los\s+usuarios"
    r"|aviso\s+legal|todos\s+los\s+derechos\s+reservados|newsletter|suscr[ií]b)",
    re.I,
)
# Tokens qui trahissent du code JS capturé par erreur.
_DESC_CODE_TOKENS = ("function(", "});", "var ", "=>", "addeventlistener",
                     "document.", "window.", "$(", "();")


def _desc_is_clean(t: str) -> bool:
    """True si le texte ressemble à une vraie description (pas de bruit légal/JS)."""
    if not t or len(t) < 30:
        return False
    low = t.lower()
    if _DESC_NOISE_RE.search(t):
        return False
    if any(tok in low for tok in _DESC_CODE_TOKENS):
        return False
    # densité de mots réels (évite les listes de specs tabulaires)
    letters = sum(c.isalpha() for c in t)
    return letters >= len(t) * 0.45


def extract_description(html: str) -> str | None:
    """Description COMPLÈTE d'une fiche, nettoyée du header/footer/cookies/JS.
    Stratégie multi-source : og:description (souvent tronqué) + bloc par classe/id
    descriptif + bloc suivant un titre « Descripción » + plus long bloc-feuille propre.
    On retient le plus LONG candidat propre → texte intégral garanti."""
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None
    bs = BeautifulSoup(html, "html.parser")
    for tag in bs(["script", "style", "nav", "header", "footer", "form",
                   "noscript", "aside", "button", "select"]):
        tag.decompose()

    cands: list[str] = []

    og = bs.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        cands.append(og["content"])

    # Blocs identifiés par classe/id (le plus fiable quand présent)
    cls_re = re.compile(r"desc|detall|observ|contenido|cuerpo|texto-?fic|"
                        r"property-?desc|comentario|comment|ad-?comment", re.I)
    for el in bs.find_all(["div", "section", "article", "p"],
                          attrs={"class": cls_re}):
        cands.append(el.get_text(" ", strip=True))
    for el in bs.find_all(["div", "section", "article", "p"],
                          attrs={"id": cls_re}):
        cands.append(el.get_text(" ", strip=True))

    # Bloc qui SUIT un titre « Descripción / Descripció / Description »
    head_re = re.compile(r"descripci|descripci[oó]|description|observacion", re.I)
    for hd in bs.find_all(string=head_re):
        par = hd.find_parent()
        if not par:
            continue
        for nxt in (hd.find_next_sibling(), par.find_next_sibling(),
                    par.find_next(["p", "div", "section"])):
            if nxt is not None and hasattr(nxt, "get_text"):
                cands.append(nxt.get_text(" ", strip=True))

    # Plus longs blocs-feuilles (fallback générique)
    for el in bs.find_all(["p", "div", "td", "section"]):
        if el.find(["p", "div", "td", "section"]):
            continue
        txt = el.get_text(" ", strip=True)
        if len(txt) > 120:
            cands.append(txt)

    best = None
    for c in cands:
        c = re.sub(r"\s+", " ", (c or "")).strip()
        if not _desc_is_clean(c):
            continue
        if best is None or len(c) > len(best):
            best = c
    return best[:6000] if best else None


# ── Extraction des deux surfaces : bâti (casita, <400 m²) et terrain (>400 m²) ──
def extract_surfaces(text: str) -> tuple[int | None, int | None]:
    """Renvoie (built_m2, terrain_m2). Règle métier : valeur ≤ 400 m² = casa/casita
    (bâti), valeur > 400 m² = terrain. On prend la plus grande de chaque classe."""
    if not text:
        return None, None
    vals: list[int] = []
    for m in re.finditer(r"(\d[\d.\s]{0,12})\s*m[²2]\b", text, re.I):
        v = parse_int(m.group(1))
        if v and 5 <= v <= 5_000_000:
            vals.append(v)
    # hectares → m²
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:ha\b|hect[aá]rea)", text, re.I):
        try:
            v = int(float(m.group(1).replace(",", ".")) * 10_000)
            if 400 < v <= 5_000_000:
                vals.append(v)
        except Exception:
            pass
    if not vals:
        return None, None
    built = max((v for v in vals if v <= 400), default=None)
    terrain = max((v for v in vals if v > 400), default=None)
    return built, terrain


def _apply_surfaces(rec: dict) -> None:
    """Remplit built_m2 / terrain_m2 / surface_m2 depuis description+titre (in-place).
    Ne pas écraser une valeur déjà extraite d'un champ structuré (JSON-LD/DOM)."""
    src = " ".join(filter(None, [rec.get("description"), rec.get("title")]))
    built, terrain = extract_surfaces(src)
    if built and not rec.get("built_m2"):
        rec["built_m2"] = built
    if terrain and not rec.get("terrain_m2"):
        rec["terrain_m2"] = terrain
    if not rec.get("surface_m2"):
        rec["surface_m2"] = rec.get("terrain_m2") or rec.get("built_m2")


# Segments d'URL à ne jamais confondre avec une ville (types, provinces, langues…).
_VILLE_URL_SKIP = {
    "es", "ca", "en", "fr", "de", "venta", "alquiler", "en_venta", "en-venta",
    "detalle", "detalles-es", "ficha", "ficha1", "inmueble", "inmuebles", "propietat",
    "propiedad", "property", "house", "obra", "ref", "rustica", "rural", "centro",
    "tarragona", "cataluna", "catalunya", "barcelona", "buscador", "recursos",
    "finca", "finca_rustica", "chalet", "casa", "masia", "terreno", "parcela",
}


def _deslug(s: str) -> str | None:
    """« la-rapita » / « sant_carles » → « La Rapita » / « Sant Carles »."""
    if not s:
        return None
    s = re.sub(r"[_\-]+", " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.title() if s and not s.isdigit() else None


def _mobilia_ville_from_url(url: str) -> str | None:
    """Ville depuis l'URL (fiable quand le slug la contient explicitement)."""
    u = url.lower()
    pats = [
        r'-en-([a-zà-ÿ\-]+?)-es\d',                       # SEO InmoWeb : -en-{ville}-esN.html
        r'-en-venta-en-([a-zà-ÿ\-]+?)-(?:de|con|ref|\d)', # Abonport : ...en-venta-en-{ville}-de-
        r'/detalle/[^/]+/[^/]+/[^/]+/([a-zà-ÿ_\-]+?)/',   # JCInmo : /detalle/op/type/prov/{ville}/
        r'/ficha/[^/]+/([a-zà-ÿ\-]+?)/',                  # Mobilia ficha : /ficha/type/{ville}/
        r'/(?:rustica|rural)/venta/([a-zà-ÿ\-]+?)/',      # DeltaEbro : /rustica/venta/{ville}/
        r'-(?:en|a)-([a-zà-ÿ\-]+?)-costa',                # FinquesMar : ...-{ville}-costa-dorada-
    ]
    for p in pats:
        m = re.search(p, u)
        if m:
            cand = m.group(1).split("_")[0]
            if cand not in _VILLE_URL_SKIP and len(cand) > 2:
                return _deslug(cand)
    return None


# Libellés CMS qui précèdent la ville sur la fiche (fallback page, très fiable).
_VILLE_LABEL_RE = re.compile(
    r"(?:Poblaci[oó]n|Localidad|Municipio|Ubicaci[oó]n|Ciudad|Zona|Localitat|Poblaci[oó])"
    r"\s*:?\s*([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\.\- ]{1,40})", re.I)


def _mobilia_ville_from_page(text: str) -> str | None:
    """Ville depuis un libellé « Población: … » de la fiche (texte déjà détagué)."""
    m = _VILLE_LABEL_RE.search(text)
    if m:
        return _clean_ville(m.group(1))
    return None


def _mobilia_record(agence: str, url: str, price_eur, title, ref, typ, loc) -> dict:
    rec = _base_record(url, "mobilia")
    rec["agence"] = agence
    rec["price_eur"] = price_eur
    rec["title"] = title
    rec["ref"] = ref
    rec["type"] = typ
    rec["localisation"] = loc
    # Ville : d'abord le slug d'URL (souvent présent), sinon le `loc` extrait, sinon
    # complétée à l'enrichissement depuis la fiche (« Población: … »).
    rec["ville"] = _mobilia_ville_from_url(url) or _clean_ville(_deslug(loc) if loc else None)
    return rec


def _mobilia_abs(domain: str, path: str) -> str:
    if path.startswith("http"):
        return path
    return domain + ("" if path.startswith("/") else "/") + path


def _is_detail_href(href: str) -> bool:
    """Lien vers une fiche bien (générique, multi-CMS)."""
    h = href.lower()
    if any(k in h for k in ("ficha", "detalle", "/propiedad", "/propietat",
                            "/inmueble", "/property", "/obra")):
        return True
    if re.search(r"-es\d+\.html$", h):
        return True
    if re.search(r"/\d{3,}/?$", h):   # se termine par un id numérique
        return True
    if re.search(r"/\d{4,}-", h):     # segment id-slug (ex: /house/4248500-casa-...)
        return True
    if re.search(r"/ref-\d+", h):    # ImmoMax pattern (/ref-12636)
        return True
    return False


_IMG_NOISE = ("logo", "icon", "sprite", "blank", "placeholder", "flag",
              "banner", "bandera", "pixel", "avatar", "whatsapp")


def _img_near(html: str, pos: int, base: str, span: int = 1400) -> str | None:
    """URL de la vignette la plus proche d'une position (pairing lien↔image).
    Chemin le plus rapide et fiable pour l'image principale d'une annonce Mobilia."""
    window = html[max(0, pos - span): pos + span]
    for m in re.finditer(
            r"""(?:data-src|data-lazy|data-original|src)=["']([^"']+\.(?:jpg|jpeg|webp|png))""",
            window, re.I):
        u = m.group(1)
        if not any(x in u.lower() for x in _IMG_NOISE):
            return urljoin(base, u)
    return None


def _mobilia_parse_generic(agence: str, base: str, html: str, limit: int) -> list[dict]:
    """Parse générique multi-CMS : liens-fiche + prix le plus proche.
    `base` = URL réelle de la page/frame (résolution correcte des liens relatifs).
    Utilisé sur HTML curl ET sur HTML rendu par navigateur (fallback, multi-frames)."""
    price_pos = [(m.start(), parse_int(m.group(1)))
                 for m in re.finditer(_PRICE_RE, html)]
    out: list[dict] = []
    for m in re.finditer(r"""href=["']([^"']+)["']""", html):
        href = m.group(1)
        if not _is_detail_href(href):
            continue
        furl = urljoin(base, href)
        if any(r["url"] == furl for r in out):
            continue
        if not price_pos:
            break
        pos, price = min(price_pos, key=lambda p: abs(p[0] - m.start()))
        if price is None or abs(pos - m.start()) > 2000:
            continue
        rm = re.search(r"(\d{3,})", furl[::-1])  # dernier id numérique
        ref = rm.group(1)[::-1] if rm else None
        rec = _mobilia_record(agence, furl, price, None, ref, None, None)
        rec["image"] = _img_near(html, m.start(), base)
        out.append(rec)
        if limit and len(out) >= limit:
            break
    return out


def _mobilia_scrape_generic(agence: str, base: str, limit: int) -> list[dict]:
    """Générique via curl (page 1, accès direct sans paramètre)."""
    html = _mobilia_fetch(base)
    if not html:
        return []
    return _mobilia_parse_generic(agence, base, html, limit)


def _mobilia_scrape_browser_batch(sites: list[tuple], limit: int) -> dict:
    """Fallback navigateur (Playwright headless SANS proxy) pour les CMS JS-rendus.
    Une seule session navigateur pour toutes les agences échouées (économie max).
    Réutilise le parse générique sur le HTML rendu (€ décodé, liens injectés)."""
    from playwright.sync_api import sync_playwright
    results: dict = {}
    with sync_playwright() as p:
        ctx = _new_context(p, use_proxy=False)  # agences locales, pas d'anti-bot
        # Page SANS route-blocking : certains widgets Mobilia (iframe buscador.php)
        # ne se peuplent pas si on coupe les ressources. Pas de proxy → coût nul.
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        for agence, base in sites:
            recs = []
            try:
                page.goto(base, wait_until="domcontentloaded", timeout=15000)
                human_delay(2, 3)
                # Cookie : clic JS instantané (évite ~20s de timeouts de sélecteurs)
                try:
                    page.evaluate(
                        "['#didomi-notice-agree-button','#onetrust-accept-btn-handler',"
                        "'button#aceptar'].forEach(s=>document.querySelector(s)?.click())")
                except Exception:
                    pass
                for _ in range(3):  # réveiller le lazy-loading SPA
                    page.mouse.wheel(0, 2500)
                    human_delay(1, 2)
                # Parser TOUTES les frames : certains sites Mobilia injectent les
                # annonces dans une iframe (ex: Elimari → recursos/buscador.php).
                recs = []
                for fr in page.frames:
                    try:
                        fh = fr.content()
                    except Exception:
                        continue
                    fbase = fr.url if (fr.url and fr.url.startswith("http")) else base
                    for r in _mobilia_parse_generic(agence, fbase, fh, limit):
                        if not any(x["url"] == r["url"] for x in recs):
                            recs.append(r)
                    if limit and len(recs) >= limit:
                        recs = recs[:limit]
                        break
            except Exception as e:
                log.warning("[mobilia] %s browser err: %s", agence, type(e).__name__)
            results[agence] = recs
        ctx.close()
    return results


def _mobilia_scrape_ficha(agence: str, base: str, limit: int) -> list[dict]:
    """Groupe A : blocs <article> + lien /ficha/. Pagination &idio=1&pag=N."""
    domain = "/".join(base.split("/")[0:3])
    sep = "&" if "?" in base else "?"
    out: list[dict] = []
    for pg in range(1, MOBILIA_MAX_PAGES + 1):
        html = _mobilia_fetch(f"{base}{sep}idio=1&pag={pg}")
        if not html or "<article" not in html:
            break
        new = 0
        for b in re.findall(r"<article[^>]*>(.*?)</article>", html, re.DOTALL):
            pm = re.search(_PRICE_RE, b)
            if not pm:
                continue
            price = parse_int(pm.group(1))
            hm = re.search(r"""href=["']([^"']*?ficha[^"']*)["']""", b, re.I)
            if not hm:
                continue
            path = hm.group(1)
            furl = path if path.startswith("http") else domain + ("" if path.startswith("/") else "/") + path
            if any(r["url"] == furl for r in out):
                continue
            tm = re.search(r"<h[23][^>]*>(.*?)</h[23]>", b, re.S | re.I)
            title = _strip_tags(tm.group(1)) if tm else None
            typ = loc = ref = None
            mm = re.search(r"ficha/([^/]+)/([^/]+)/(?:[^/]+/)?(?:[^/]+/)?(\d+)/", furl)
            if mm:
                typ, loc, ref = mm.group(1), mm.group(2), mm.group(3)
            rec = _mobilia_record(agence, furl, price, title, ref, typ, loc)
            rec["image"] = _img_near(b, 0, domain, span=len(b) + 10)
            out.append(rec)
            new += 1
            if limit and len(out) >= limit:
                return out
        if new == 0:
            break
        time.sleep(0.2)
    return out


def _mobilia_scrape_seo(agence: str, base: str, limit: int) -> list[dict]:
    """Groupe B : liens SEO ...-es{N}.html, prix dans le contexte suivant."""
    domain = "/".join(base.split("/")[0:3])
    out: list[dict] = []
    seen: set[str] = set()
    for pg in range(1, MOBILIA_MAX_PAGES + 1):
        html = _mobilia_fetch(f"{base}&idio=1&pag={pg}")
        if not html or not re.search(r"-es\d+\.html", html):
            break
        new = 0
        for m in re.finditer(r"""href=["']([^"']+?-es(\d+)\.html)["']""", html):
            path, ref = m.group(1), m.group(2)
            if ref in seen:
                continue
            window = html[m.end():m.end() + 1500]
            pm = re.search(_PRICE_RE, window)
            if not pm:
                continue
            seen.add(ref)
            price = parse_int(pm.group(1))
            furl = path if path.startswith("http") else domain + ("" if path.startswith("/") else "/") + path
            typ = loc = None
            tlm = re.search(r"([^/]+)-en-([^/]+)-es", path)
            if tlm:
                typ, loc = tlm.group(1), tlm.group(2).replace("-", " ")
            tm = re.search(r"<h[23][^>]*>(.*?)</h[23]>", window, re.S | re.I)
            title = _strip_tags(tm.group(1)) if tm else None
            rec = _mobilia_record(agence, furl, price, title, ref, typ, loc)
            rec["image"] = _img_near(html, m.start(), domain)
            out.append(rec)
            new += 1
            if limit and len(out) >= limit:
                return out
        if new == 0:
            break
        time.sleep(0.2)
    return out


def _mobilia_enrich_detail(rec: dict, use_proxy: bool = False) -> None:
    """Ouvre la fiche et complète description / surface / chambres / image (in-place).
    Règle surface : <400 m² → construit · >400 m² → terrain. Ne remplit que le vide."""
    url = rec["url"]
    # JC Inmobiliaria tourne en catalan par défaut → forcer l'espagnol via cookie.
    cookies = {"idioma_web": "es", "lang": "es", "idioma": "es"} \
        if "jcimmobiliaria" in url else None
    html = _mobilia_fetch_proxy(url) if use_proxy else _mobilia_fetch(url, cookies)
    if not html:
        return
    clean_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)

    # Description COMPLÈTE (helper générique anti-bruit). On remplace la teaser
    # tronquée éventuelle par la version intégrale si elle est plus longue.
    full = extract_description(html)
    if full and len(full) > len(rec.get("description") or ""):
        rec["description"] = full
        log.debug("[%s] desc enrichie: %d chars", rec.get("agence", "?"), len(full))

    # Ville : si l'URL n'a rien donné, on lit le libellé « Población: … » de la fiche.
    if not rec.get("ville"):
        rec["ville"] = _mobilia_ville_from_page(_strip_tags(clean_html))
        if rec.get("ville"):
            log.debug("[%s] ville détectée: %s", rec.get("agence", "?"), rec["ville"])

    # Surfaces : bâti (casita ≤400 m²) + terrain (>400 m²), règle métier.
    # On lit d'abord dans la description (fiable) puis, à défaut, dans la page.
    built, terrain = extract_surfaces(rec.get("description") or "")
    if not (built or terrain):
        built, terrain = extract_surfaces(_strip_tags(clean_html))
    if built and not rec.get("built_m2"):
        rec["built_m2"] = built
        log.debug("[%s] bâti: %d m²", rec.get("agence", "?"), built)
    if terrain and not rec.get("terrain_m2"):
        rec["terrain_m2"] = terrain
        log.debug("[%s] terrain: %d m²", rec.get("agence", "?"), terrain)
    # surface_m2 (compat) = terrain si dispo sinon bâti
    if not rec.get("surface_m2"):
        rec["surface_m2"] = rec.get("terrain_m2") or rec.get("built_m2")

    # Chambres / salles de bain (présentes seulement sur le bâti)
    if not rec.get("bedrooms"):
        bm = re.search(r'(\d+)\s*(?:habitacion|dormitor|hab\b|quartos?)', clean_html, re.I)
        if bm:
            rec["bedrooms"] = parse_int(bm.group(1))
    if not rec.get("bathrooms"):
        bm = re.search(r'(\d+)\s*(?:ba[ñn]os?|aseos?)', clean_html, re.I)
        if bm:
            rec["bathrooms"] = parse_int(bm.group(1))
    # Image : fallback fiche si la vignette liste a manqué
    if not rec.get("image"):
        ogi = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
        if ogi and not any(x in ogi.group(1).lower() for x in _IMG_NOISE):
            rec["image"] = ogi.group(1)


def run_mobilia(limit: int) -> dict:
    """Scrape les 37 agences Mobilia. Couche 1 = curl (rapide/économique).
    Couche 2 = navigateur sans proxy pour les CMS JS-rendus. limit = annonces/agence."""
    records: list[dict] = []
    failed: list[tuple] = []

    # ── Couche 1 : curl pur (FICHA → générique) ──
    for nom, base in MOBILIA_FICHA:
        recs = _mobilia_scrape_ficha(nom, base, limit)
        mode = "FICHA"
        if not recs:
            recs = _mobilia_scrape_generic(nom, base, limit)
            mode = "GENER"
        if recs:
            log.info("[mobilia] %-16s %s → %d annonces", nom, mode, len(recs))
            records.extend(recs)
        else:
            failed.append((nom, base))
    for nom, base in MOBILIA_SEO:
        recs = _mobilia_scrape_seo(nom, base, limit)
        if recs:
            log.info("[mobilia] %-16s SEO   → %d annonces", nom, len(recs))
            records.extend(recs)
        else:
            failed.append((nom, base))

    # ── Couche 2 : fallback navigateur (sans proxy) pour les échecs curl ──
    still_failed: list[tuple] = []
    if failed:
        log.info("[mobilia] fallback navigateur pour %d agences JS-rendues...", len(failed))
        browser_results = _mobilia_scrape_browser_batch(failed, limit)
        for nom, recs in browser_results.items():
            log.info("[mobilia] %-16s BROWSER → %d annonces", nom, len(recs))
            if recs:
                records.extend(recs)
            elif nom in MOBILIA_WAF:
                still_failed.append(next(t for t in failed if t[0] == nom))

    # ── Couche 3 : proxy résidentiel Evomi pour les WAF (HomeIn, PrimeInmo) ──
    if still_failed:
        log.info("[mobilia] couche Evomi pour %d sites WAF-bloqués...", len(still_failed))
        for nom, base in still_failed:
            html = _mobilia_fetch_proxy(base)
            recs = _mobilia_parse_generic(nom, base, html, limit) if html else []
            log.info("[mobilia] %-16s EVOMI → %d annonces", nom, len(recs))
            records.extend(recs)

    # ── Enrichissement détail : description / surface / chambres / image ──
    log.info("[mobilia] enrichissement détail de %d annonces...", len(records))
    for r in records:
        try:
            _mobilia_enrich_detail(r, use_proxy=(r.get("agence") in MOBILIA_WAF))
        except Exception as e:
            log.warning("[mobilia] enrich %s: %s", r.get("url", "")[:50], e)

    good = [r for r in records if is_exploitable(r)]
    ok_sites = len(set(r["agence"] for r in good))
    out_file = OUT_DIR / "mobilia.json"
    out_file.write_text(json.dumps(good, ensure_ascii=False, indent=2))
    total_sites = len(MOBILIA_FICHA) + len(MOBILIA_SEO)
    log.info("[mobilia] %d/%d agences OK → %d annonces exploitables → %s",
             ok_sites, total_sites, len(good), out_file)
    return {"site": "mobilia", "urls": len(records), "records": len(records),
            "exploitable": len(good)}


# ── Orchestration ─────────────────────────────────────────────────────────────
SITES = ["thinkspain", "kyero", "fotocasa", "idealista", "finquesmar", "mobilia"]


def run_site(site: str, limit: int, phase: str) -> dict:
    # Mobilia : 37 agences en une passe (curl_cffi, sans proxy). limit = annonces/agence.
    if site == "mobilia":
        return run_mobilia(limit)

    seed_file = SEEDS_DIR / f"{site}.txt"

    # PHASE A
    if phase in ("discover", "all"):
        if site == "idealista":
            urls = discover_idealista(limit)
        else:
            urls = DISCOVERERS[site](limit)
        if urls:
            seed_file.write_text("\n".join(urls))
        log.info("[%s] PHASE A → %d URLs (%s)", site, len(urls), seed_file)
    else:
        urls = [l.strip() for l in seed_file.read_text().splitlines()
                if l.strip().startswith("http")] if seed_file.exists() else []

    if limit:
        urls = urls[:limit]
    if phase == "discover":
        return {"site": site, "urls": len(urls), "records": 0, "exploitable": 0}

    # PHASE B
    if not urls:
        return {"site": site, "urls": 0, "records": 0, "exploitable": 0}

    if site in HTML_PARSERS:
        # 4 portails → couche DataDome-aware (curl_cffi + Shield)
        recs = extract_net_site(site, urls)
    elif site == "finquesmar":
        recs = extract_playwright_site(site, urls, use_proxy=False)
    else:
        recs = []

    good = [r for r in recs if is_exploitable(r)]
    out_file = OUT_DIR / f"{site}.json"
    out_file.write_text(json.dumps(good, ensure_ascii=False, indent=2))
    log.info("[%s] PHASE B → %d records, %d exploitables → %s",
             site, len(recs), len(good), out_file)
    return {"site": site, "urls": len(urls), "records": len(recs), "exploitable": len(good)}


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="all")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--phase", choices=["discover", "extract", "all"], default="all")
    ap.add_argument("--verbose", action="store_true", help="Logs ultra-détaillés en temps réel")
    args = ap.parse_args()

    # Verbose mode : logs en temps réel (détail complet extrait par extrait)
    if args.verbose:
        log.setLevel(logging.DEBUG)
        for handler in log.handlers:
            handler.setLevel(logging.DEBUG)
        log.info("🔍 MODE VERBOSE : logs ultra-détaillés activés")

    sites = SITES if args.site == "all" else [args.site]
    summary = []
    for site in sites:
        try:
            summary.append(run_site(site, args.limit, args.phase))
        except Exception as e:
            log.error("[%s] ÉCHEC: %s", site, e)
            summary.append({"site": site, "urls": 0, "records": 0, "exploitable": 0, "error": str(e)})

    print("\n" + "=" * 60)
    print("  RÉSUMÉ")
    print("=" * 60)
    for s in summary:
        tag = "✅" if s.get("exploitable") else ("⚠️" if s.get("urls") else "❌")
        extra = f" — {s['error']}" if s.get("error") else ""
        print(f"  {tag} {s['site']:12} URLs={s['urls']:3}  records={s['records']:3}  "
              f"exploitables={s['exploitable']:3}{extra}")
    print("=" * 60)


if __name__ == "__main__":
    main()
