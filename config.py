import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── PROXY CREDENTIALS ─────────────────────────────────────────────────────
EVOMI_SERVER    = "http://core-residential.evomi.com:1000"
EVOMI_USER      = os.getenv("EVOMI_USER", "samueldomi6")
EVOMI_PASS_BASE = os.getenv("EVOMI_PASS", "DSfzAOkqIjfgPqQhcD5h_country-ES")

BRIGHTDATA_SERVER = "http://brd.superproxy.io:33335"
BRIGHTDATA_USER   = os.getenv("BRIGHTDATA_USER", "brd-customer-hl_3d097701-zone-residential_proxy1")
BRIGHTDATA_PASS   = os.getenv("BRIGHTDATA_PASS", "vkq79impgjd6")

# ── THINKSPAIN ────────────────────────────────────────────────────────────
SITES_THINKSPAIN = [
    {"name": "thinkspain_fincas",  "url": "https://www.thinkspain.com/property-for-sale/tortosa/fincas-country-houses?radius=75",   "type": "finca"},
    {"name": "thinkspain_terrain", "url": "https://www.thinkspain.com/property-for-sale/tortosa/undeveloped-lands?radius=75",        "type": "terrain"},
]

# ── KYERO ─────────────────────────────────────────────────────────────────
SITES_KYERO = [
    {"name": "kyero_fincas_tarragona", "url": "https://www.kyero.com/fr/province-de-tarragone-maisons-de-campagne-%C3%A0-vendre-0l43g4", "type": "finca"},
]

# ── FOTOCASA ──────────────────────────────────────────────────────────────
_SA = (
    "xjwzokiye6t9jGy5tkI6h19Pqh_2Nqpr1I22_gC60oO2mtSzko5Bs1hYo5ldzko5Bh-5jOyrk5BwhhjBk-zEpxqO"
    "xj1Cvj6lF33ihC2mtSngkjBk6tqY3suoDzw1ChzpOgo4wa9l-wOmiq_C7wijB1p3Kj-1gExht0C7wm8Juyh6Qqht0H"
    "2t64Iw9w8L7rqqDq11Km4mnHv50iO0v2xB_jwiE6vodn81iCk-zE307-Cxlg7Iq11Ki446Ej4q0CqxqOtt70G6vod"
    "6-9X50oOosrnV9_yxBkykpI70oOkvx9Lor4pDjisqB53hdq-s-Ch684BzyliC70oO_ijdxhhjBiq_jHr5ldxhhjB"
    "wj5X6vod4kigEwq_1G_tzEhk7oFr5ldo_99Cm6njL6300D9m-2du4mOvkuoF70oO9r28Nuh54Brw0E3s_iLrw0E"
    "uh54Brw0Ex8zCu4mO7om6L5tyqC4x85Lp9kxBmlvK4964Bi26nF1qtiHspxhCok2zC-5xX2h-cr6lO-5xXgjjdmthxB"
    "n8kOuo09C-z4iHx8zC_i_iBh5lyGmgw4Ex8zCiprzD2z8iBr50qYv0hoD_i_iBrw0E52_gCoxwpBw4mOv0hoD_16gC"
    "4rm1LzhhjB3vuu-Bx8zCjr6sO_i_iBzm6pC_i_iB4rm1Lmgw4E43moDrw0EzmutO9wm5jBqsinJ2izCnvhjGn8kO"
    "zhhjB_tzE0xr-Dx8zCrw0EvxtKp9lzDv6s6Jhp14B2z1jIkkvxiCoxwpBmgw4Ep8kO_tzE52_gCiprzD_i_iB"
    "jr6sOvk7iBhpuS-i-nDmv5gL4glv-B1v20Ig1r3Ux8zC-sri0Bp15iBr28gCs6lO2zvsOx8zCw-q0uBs3o-Dr28gC"
    "9ru-D_lnhC2r8czvzC3h-c2z8iBw0v4B8pj8JimhqC5rjgEu55zDzwx4Buk7iBto09Ck-zE2tv9Cuk7iBo8kOuk7iB"
    "o8kOuk7iBo8kO13mrMhliiL5ulqawphuY58xyoBmmx-D930rE58yEto09CluuuOsim_T7773N_o14BlzozD_40gLto09C"
    "sgrsYnygsEmmx-DjsjvRom5uO2_7mF75viNoj59C6r3hCo_opD6s8_JzjuqC6ipxS-hqlHgmnqB6hhxM9sutEh1l-C"
    "6mzpDqr0tE2u2hE9ijdhuqqBzj-xMvtv-C38slGk5xoyC8q76L9lpizB66tvd5wusM7vl4IwhhjB9ll7V9ijd84ioF"
    "gl3qPv7w1Fl_4xKs-2kLxj1Cq5i_C3yg5Bk-zEkn2xRml7hQk-zEwhhjBi7roD2mtSzko5B42rpB"
)
SITES_FOTOCASA = [
    {"name": "fotocasa_casas_rusticas", "url": f"https://www.fotocasa.es/es/comprar/casas-rurales/espana/todas-las-zonas/l?searchArea={_SA}",    "type": "casa_rustica"},
    {"name": "fotocasa_terrenos",        "url": f"https://www.fotocasa.es/es/comprar/terrenos/espana/todas-las-zonas/l/2?searchArea={_SA}", "type": "terrain"},
]

# ── IDEALISTA ─────────────────────────────────────────────────────────────
_SHAPE = "%28%28snruFciw%40gsoAor%40%7B%7D%7C%40spd%40miLytyDrpq%40ePfcyBxwiEiwOhrV%29%29"
SITES_IDEALISTA = [
    {"name": "idealista_chalets_tourist", "url": f"https://www.idealista.com/areas/venta-viviendas/con-chalets-independientes,casas-de-pueblo/?shape={_SHAPE}", "type": "chalet", "tourist_filter": True},
    {"name": "idealista_casas_pueblo",    "url": f"https://www.idealista.com/areas/venta-viviendas/con-casas-de-pueblo/?shape={_SHAPE}",                         "type": "casa_pueblo", "tourist_filter": False},
    {"name": "idealista_fincas_terrain",  "url": f"https://www.idealista.com/areas/venta-terrenos/con-metros-cuadrados-mas-de_5000,terrenos-no-urbanizables/?shape={_SHAPE}", "type": "finca_terrain", "tourist_filter": False},
]
TOURIST_KEYWORDS = ["licencia", "turístic", "turistic", "airbnb", "booking", "alquiler turistico", "vacacional"]

# ══════════════════════════════════════════════════════════════════════════
# MOBILIA GROUP A — True /ficha/ pattern (static HTML, &pag=N pagination)
# Confirmed working: FinquesRoca, FinquesFarnos, EbreTaxacions, Esteller, Rieres
# ══════════════════════════════════════════════════════════════════════════
SITES_MOBILIA_A = [
    {"name": "FinquesRoca",   "url": "https://www.finquesroca.com/index.php?limtipos=3699,899,10999,4099&buscador=1"},
    {"name": "FinquesFarnos", "url": "https://www.finquesfarnos.com/index.php?limtipos=3699,4599,4999,399,499,4099&buscador=1"},
    {"name": "EbreTaxacions", "url": "https://www.ebretaxacions.com/index.php?limtipos=3699,4599,899&buscador=1"},
    {"name": "Esteller",      "url": "https://www.estellerconsulting.com/index.php?limtipos=7599,3699,6299,6199,399,499,4099&av=1"},
    {"name": "Rieres",        "url": "https://www.rieres.com/index.php?limtipos=4599,7599,3699,399,499,4999&buscador=1"},
]

# ══════════════════════════════════════════════════════════════════════════
# MOBILIA DETALLE — /detalle/ URL pattern (JCInmo CMS, ?p=N pagination)
# ══════════════════════════════════════════════════════════════════════════
SITES_MOBILIA_DETALLE = [
    {"name": "JCInmo_R",  "url": "https://www.jcimmobiliaria.cat/buscador/en_venta/finca_rustica/"},
    {"name": "JCInmo_C",  "url": "https://www.jcimmobiliaria.cat/buscador/en_venta/chalet/"},
    {"name": "JCInmo_CR", "url": "https://www.jcimmobiliaria.cat/buscador/en_venta/chalet_rustico/"},
    {"name": "JCInmo_M",  "url": "https://www.jcimmobiliaria.cat/buscador/en_venta/masia/"},
]

# ══════════════════════════════════════════════════════════════════════════
# EBRORIVER — /detalles-es/property/{ID}/ pattern (&pag=N pagination)
# ══════════════════════════════════════════════════════════════════════════
SITES_EBRORIVER = [
    {"name": "EbroRiver_fincas",  "url": "https://www.ebroriver.com/es/properties.html?nbreal_category_id=2&type=8"},
    {"name": "EbroRiver_chalets", "url": "https://www.ebroriver.com/es/properties.html?nbreal_category_id=9&type=8"},
    {"name": "EbroRiver_casas",   "url": "https://www.ebroriver.com/es/properties.html?nbreal_category_id=1&type=8"},
]

# ══════════════════════════════════════════════════════════════════════════
# EBREPISOS — Drupal CMS, /propietat/ref/{ref} (&page=N, 0-indexed)
# ══════════════════════════════════════════════════════════════════════════
SITES_EBREPISOS = [
    {"name": "EbrePisos_fincas",  "url": "https://ebrepisos.com/es/aaa?field_type_tid=161"},
    {"name": "EbrePisos_masies",  "url": "https://ebrepisos.com/es/aaa?field_type_tid=53"},
    {"name": "EbrePisos_chalets", "url": "https://ebrepisos.com/es/aaa?field_type_tid=54"},
    {"name": "EbrePisos_cases",   "url": "https://ebrepisos.com/es/aaa?field_type_tid=55"},
]

# ══════════════════════════════════════════════════════════════════════════
# DELTAEBRO — Custom CMS, /es/rustica/venta/{city}/{slug}/{ID} (?page=N)
# ══════════════════════════════════════════════════════════════════════════
SITES_DELTAEBRO = [
    {"name": "DeltaEbro_rustica", "url": "https://inmobiliaria-deltadelebro.com/es/rustica/venta"},
]

# ══════════════════════════════════════════════════════════════════════════
# ACTIVEHOUSE — JSON-LD embedded, detail via ref ID anchor (#NNNNNNNN)
# ══════════════════════════════════════════════════════════════════════════
SITES_ACTIVEHOUSE = [
    {"name": "ActiveHouse_fincas",  "url": "https://www.activehouseinmo.es/buscador/finca_rustica/?IdTipoOperacion=0"},
    {"name": "ActiveHouse_chalets", "url": "https://www.activehouseinmo.es/buscador/chalet_rustico/?IdTipoOperacion=0"},
]

# ══════════════════════════════════════════════════════════════════════════
# INMOWEB SEO — data-url with -esNNNNNN.html (InmoWeb CMS, &pag=N)
# ══════════════════════════════════════════════════════════════════════════
SITES_INMOWEB_SEO = [
    {"name": "Stanza",      "url": "https://www.stanza.es/results/?id_tipo_operacion=1&type%5B%5D=3&type%5B%5D=16&type%5B%5D=9"},
    {"name": "EstebanInmo", "url": "https://www.estebanimmobiliaria.com/results/?id_tipo_operacion=1&type=3%2C9"},
    {"name": "FinquesEbre", "url": "https://www.finquesebre.com/results/?id_tipo_operacion=1&type=3%2C16%2C9"},
]

# ══════════════════════════════════════════════════════════════════════════
# JS-RENDERED — Playwright without proxy (small agencies, no anti-bot)
# Target: /ficha/ links or ficha-style data after JS renders
# ══════════════════════════════════════════════════════════════════════════
SITES_JS_NOPRX = [
    {"name": "HomeIn_chalets",   "url": "https://www.homein.cat/es/venta-chalets-chalets_independientes"},
    {"name": "Abonport_fincas",  "url": "https://www.abonport.es/inmuebles/venta/finca-rustica/tarragona/"},
    {"name": "Elimari",          "url": "https://www.grupoelimari.com/inmobiliaria-sant-carles-de-la-rapita-inm.html"},
    {"name": "ViaAugusta_land",  "url": "https://www.finquesviaaugusta.com/find/?kind=land&selling=true"},
    {"name": "ViaAugusta_house", "url": "https://www.finquesviaaugusta.com/find/?kind=housing&selling=true"},
    {"name": "ImmoMax_fincas",   "url": "https://www.immomax.es/es/venta-parcela-fincas_rusticas"},
    {"name": "ImmoMax_chalets",  "url": "https://www.immomax.es/es/venta-chalets-chalets_independientes"},
    {"name": "LaPlana_fincas",   "url": "https://www.laplanaimmobiliaria.com/inmuebles?key_tipo=finca_rustica"},
    {"name": "LaPlana_cases",    "url": "https://www.laplanaimmobiliaria.com/inmuebles?key_tipo=finca_rustica_casa"},
    {"name": "LaCentral_fincas", "url": "https://www.lacentralimmobiliaria.com/es-es/pisos-casas-venta-alquiler/fincas?srt=2"},
    {"name": "LaCentral_casas",  "url": "https://www.lacentralimmobiliaria.com/es-es/pisos-casas-venta-alquiler/viviendas-casas?srt=2"},
    {"name": "RusticMar",        "url": "https://www.rusticmar.info/inmuebles?type=191"},
    {"name": "PrimeInmo",        "url": "http://www.primeinmo.com/es/venta-chalets~parcela-chalets_independientes~masias~fincas_rusticas"},
    {"name": "DeltaEbro_ruralV", "url": "https://inmobiliaria-deltadelebro.com/es/rural-houses/venta"},
]

# Dead sites — included for documentation, skipped in scraper
SITES_DEAD = [
    "FinquesMar",   # 404
    "Prodeltamar",  # 404
]

# ── SCRAPER SETTINGS ──────────────────────────────────────────────────────
MAX_CONSECUTIVE_ERRORS = 15
MAX_PAGES_PER_SITE = 20
REQUEST_DELAY_MIN = 2.5
REQUEST_DELAY_MAX = 6.0
REQUEST_TIMEOUT   = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
