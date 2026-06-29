"""
Moteur de filtres — recherche granulaire (espagnol).

Tolérances : INSENSIBLE AUX ACCENTS (présence/absence indifférente) + tolérance
d'1 à 2 lettres manquantes/erronées (fuzzy via le module `regex`).
- normalisation = minuscule + suppression des accents, SANS changer la longueur
  → les offsets restent valides pour le surlignage sur le texte d'origine.
- budget d'erreurs par longueur de terme : ≤4 car = exact, 5-8 = 1 erreur, ≥9 = 2.
- les jetons ultra-ambigus une fois désaccentués (ex. « mas » vs « más ») sont
  matchés en mode accent-sensible pour éviter un sur-déclenchement massif.

API publique : SEARCH_SYNONYMS, text_matches(text, gk), text_spans(text, gk),
is_solar_excluded(text).
"""
import unicodedata
import regex as _re

_FLAGS = _re.IGNORECASE
_ACCENT_SENSITIVE = {"mas"}  # désaccentué « más » (=plus) → trop fréquent : garder l'accent


def _lower(s: str) -> str:
    return (s or "").lower()


def _strip(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Minuscule + sans accents (longueur préservée → offsets valides)."""
    return _strip(_lower(s))


def _alt(xs):
    return "|".join(sorted(set(xs), key=len, reverse=True))


def _compile_phrases(phrases):
    """Compile une liste de phrases. Stratégie EXACT-D'ABORD (rapide) puis fuzzy en
    repli (lent, seulement quand l'exact échoue → typos rares) :
    - exact_ai : alternance EXACTE accent-insensible (tous les termes).
    - exact_as : alternance exacte accent-SENSIBLE (jetons ambigus type « mas »).
    - fuzzy    : repli tolérant 1 erreur (5-11 car) / 2 erreurs (≥12 car).
    Renvoie un dict {exact_ai, exact_as, fuzzy:[…]}."""
    exact_ai, exact_as, fz = [], [], {1: [], 2: []}
    for p in phrases:
        npa = _lower(p)
        npi = _strip(npa)
        if not npi.strip():
            continue
        if npi in _ACCENT_SENSITIVE:
            exact_as.append(_re.escape(npa).replace(r"\ ", r"\s+"))
            continue
        body = _re.escape(npi).replace(r"\ ", r"\s+")
        exact_ai.append(body)
        # Tolérance « 1-2 lettres » : sur les MOTS SEULS uniquement (une faute de
        # frappe touche un mot, pas une phrase entière) — les phrases multi-mots
        # restent en exact accent-insensible. budget 1 (5-9 car) / 2 (≥10 car).
        L = len(npi)
        if " " not in npi and L >= 5:
            fz[1].append(body)   # budget 1 : compromis tolérance/perf sur des milliers d'annonces
    c = {"exact_ai": None, "exact_as": None, "fuzzy": []}
    if exact_ai:
        c["exact_ai"] = _re.compile(r"\b(?:%s)\b" % _alt(exact_ai), _FLAGS)
    if exact_as:
        c["exact_as"] = _re.compile(r"\b(?:%s)\b" % _alt(exact_as), _FLAGS)
    for budget, alts in fz.items():
        if alts:
            c["fuzzy"].append(_re.compile(r"(?:%s){e<=%d}" % (_alt(alts), budget), _FLAGS))
    return c


def _match_compiled(c, nt, nta) -> bool:
    if c["exact_ai"] and c["exact_ai"].search(nt):
        return True
    if c["exact_as"] and c["exact_as"].search(nta):
        return True
    for rx in c["fuzzy"]:           # repli fuzzy seulement si l'exact a échoué
        for m in rx.finditer(nt):
            # le fuzzy ne doit JAMAIS franchir un espace : une faute touche un MOT
            # seul (ex. « campr », « kamper »), pas deux mots collés (« ca per »
            # surligné à tort dans « rústica perfecta »). On rejette tout match
            # contenant un blanc → tolérance lettre manquante/erronée, sans espace.
            if not any(ch.isspace() for ch in m.group()):
                return True
    return False


def _spans_compiled(c, nt, nta):
    spans = []
    if c["exact_ai"]:
        spans += [(m.start(), m.end()) for m in c["exact_ai"].finditer(nt)]
    if c["exact_as"]:
        spans += [(m.start(), m.end()) for m in c["exact_as"].finditer(nta)]
    for rx in c["fuzzy"]:
        spans += [(m.start(), m.end()) for m in rx.finditer(nt)
                  if m.end() > m.start() and not any(ch.isspace() for ch in m.group())]
    return spans


# ── Définition des groupes : (clé, label, [phrases]) ────────────────────────────
_GROUPS = [
    ("water_feature", "💧 Piscine / Bassin", [
        "piscina", "piscina privada", "piscina propia", "piscina comunitaria",
        "piscina elevada", "piscina desmontable", "piscina de obra", "balsa",
        "balsa de agua", "balsa de riego", "alberca", "alberca de agua", "pool",
        "bassa", "bassa d'aigua", "zona de baño",
    ]),
    ("sea_view", "🌊 Vue mer", [
        "vistas al mar", "vista al mar", "vista sobre el mar", "vistas sobre el mar",
        "vistas mar", "vistas al mediterráneo", "vistas al mediterraneo",
        "panorámicas al mar", "panoramicas al mar", "frente al mar",
        "primera línea de mar", "primera linea de mar", "cerca del mar",
        "orientación mar", "orientacion mar", "mirando al mar", "con el mar de fondo",
    ]),
    ("mountain_view", "⛰️ Vue montagne / nature", [
        "vistas a la montaña", "vista montaña", "vistas montaña", "vistas al monte",
        "vista al monte", "vistas a la sierra", "sierra", "entorno natural",
        "paraje natural", "rodeado de naturaleza", "rodeada de naturaleza",
        "plena naturaleza", "paisaje natural", "vistas despejadas",
        "vistas panorámicas", "vistas panoramicas", "vistas al campo",
        "vistas al valle", "valle", "entorno rural",
    ]),
    ("fence", "🚧 Vallado / clôturé", [
        "vallado", "vallada", "totalmente vallado", "completamente vallado",
        "finca vallada", "parcela vallada", "cercado", "cercada", "cerrado",
        "cerrada", "cerramiento", "perimetral", "vallado perimetral",
        "muro de piedra", "muro perimetral", "puerta de acceso", "acceso cerrado",
        "parcela cerrada", "terreno cerrado",
    ]),
    # ── Groupe FUSIONNÉ : finca construida + garage + hangar + caseta + almacén… ──
    ("building", "🏠 Construction / bâtiment (casa·caseta·garage·hangar·almacén…)", [
        "finca con casa", "finca con vivienda", "finca construida", "con construcción",
        "con construccion", "construcción existente", "construccion existente",
        "casa rural", "casa de campo", "vivienda rural", "vivienda", "masía", "masia",
        "maset", "mas", "chalet", "casita", "caseta", "caseta de campo", "refugio",
        "edificación", "edificacion", "inmueble", "construcción legal",
        "construccion legal", "construcción registrada", "vivienda registrada",
        "escriturada", "con escritura", "catastro vivienda", "garaje", "garage",
        "cochera", "nave", "nave agrícola", "nave agricola", "nave industrial",
        "hangar", "almacén", "almacen", "cubierto", "trastero", "cobertizo", "cobert",
        "caseta de aperos", "cuarto de aperos", "aperos", "almacén agrícola",
        "almacen agricola", "establo", "cuadras", "corral", "gallinero", "anexo",
        "anejo", "dependencia", "dependencias", "porche", "taller", "bodega",
        "leñera", "casa", "cabaña", "ruina", "en ruinas", "para reformar",
        "a reformar", "necesita reforma", "reforma integral", "a rehabilitar",
        "para rehabilitar", "proyecto de reforma", "antigua masía", "antigua masia",
        "construcción antigua", "construccion antigua",
    ]),
    ("surface_built", "📐 Surface bâtie", [
        "m² construidos", "m2 construidos", "metros construidos",
        "superficie construida", "construidos", "edificados", "superficie edificada",
        "vivienda de", "casa de", "construcción de", "construccion de", "almacén de",
        "almacen de", "caseta de", "metros cuadrados construidos",
    ]),
    ("finca_rustica", "🌿 Finca rústica (sans construction)", [
        "finca rústica", "finca rustica", "terreno rústico", "terreno rustico",
        "parcela rústica", "parcela rustica", "suelo rústico", "suelo rustico",
        "terreno agrícola", "terreno agricola", "finca agrícola", "finca agricola",
        "sin construcción", "sin construccion", "sin edificar", "no edificable",
        "terreno sin edificar", "parcela sin edificar", "tierra de cultivo",
    ]),
    # ── SPÉCIAL : « finca » présent ET possibilité de construire ──
    ("finca_buildable", "🏗️ Finca + possibilité de construire", [
        "finca rústica con posibilidad de construir",
        "finca rustica con posibilidad de construir",
        "terreno rústico con posibilidad de construir",
        "terreno rustico con posibilidad de construir",
        "posibilidad de construir", "posibilidad de edificar",
        "permiso para construir", "permiso para una construccion",
        "permiso de construccion", "se puede construir", "se podría construir",
        "se podria construir", "apto para construir", "licencia para construir",
        "proyecto aprobado", "proyecto de vivienda aprobado",
    ]),
    ("olive_trees", "🫒 Oliviers", [
        "olivar", "olivares", "olivo", "olivos", "oliveras", "oliveres", "olivera",
        "olivero", "oliveros", "finca de olivos", "campo de olivos",
        "cultivo de olivos", "olivos en producción", "olivos en produccion",
        "aceite propio", "producción de aceite", "produccion de aceite",
        "arbequina", "empeltre", "sevillenca",
    ]),
    ("almond_trees", "🌰 Amandiers", [
        "almendro", "almendros", "almendral", "campo de almendros",
        "finca de almendros", "cultivo de almendros", "almendros en producción",
        "almendros en produccion", "ametller", "ametllers", "ametlleral",
    ]),
    ("carob_trees", "🌾 Caroubiers", [
        "algarrobo", "algarrobos", "algarrobera", "algarroberas", "garrofer",
        "garrofers", "garrofera", "garrofes", "campo de algarrobos",
        "finca de algarrobos",
    ]),
    ("tourism_license", "🏖️ Licence touristique / locatif", [
        "licencia turística", "licencia turistica", "licencia vacacional",
        "licencia de alquiler turístico", "licencia de alquiler turistico",
        "vivienda turística", "vivienda turistica", "HUT", "HUTTE", "HUTB", "HUTG",
        "HUTT", "VT", "VUT", "alquiler vacacional", "alquiler turístico",
        "alquiler turistico", "airbnb", "booking", "apto para alquiler turístico",
        "turismo rural", "casa rural con licencia", "explotación turística",
        "explotacion turistica",
    ]),
    ("river_access", "🏞️ Rivière / eau naturelle", [
        "río", "rio", "junto al río", "junto al rio", "acceso al río",
        "acceso al rio", "riera", "ribera", "arroyo", "torrente", "manantial",
        "fuente", "balsa de riego",
    ]),
    ("isolation", "🏔️ Isolement réel", [
        "sin vecinos", "sin vecinos cerca", "sin vecinos próximos",
        "sin vecinos proximos", "sin casas cerca", "aislado", "aislada",
        "finca aislada", "totalmente aislada", "totalmente aislado", "privacidad",
        "mucha privacidad", "intimidad", "entorno privado", "lejos de vecinos",
    ]),
    ("neighbors_close", "🏘️ Voisins proches", [
        "vecinos cercanos", "vecinos cerca", "vecinos próximos", "vecinos proximos",
        "casas cercanas", "viviendas cercanas", "con vecinos", "cerca de otras casas",
    ]),
    ("water_available", "💧 Eau disponible", [
        "agua potable", "agua corriente", "agua de red", "red de agua",
        "agua municipal", "contador de agua", "agua dada de alta", "pozo propio",
        "pozo legal", "cisterna", "agua de riego", "derecho de riego",
        "comunidad de regantes",
    ]),
    ("water_none", "🚱 Sans eau", [
        "sin agua", "no tiene agua", "no dispone de agua", "sin suministro de agua",
        "agua no conectada", "agua cerca",
    ]),
    ("water_connectable", "🔌 Possibilité de connecter l'eau", [
        "posibilidad de conectar agua", "conexion posible al agua",
        "conexion posible al pozo",
        "posible de conectarse a la comunidad de regantes",
        "posibilidad de conexión de agua", "posibilidad de conexion de agua",
        "posibilidad de conectar a la red de agua",
        "posibilidad de conexión a la red de agua",
        "posibilidad de conexion a la red de agua", "se puede conectar al agua",
        "se puede conectar a la red de agua", "conexión posible al agua",
        "posibilidad de conectar al pozo", "posibilidad de conexión al pozo",
        "posibilidad de conexion al pozo",
        "posibilidad de conectar a la comunidad de regantes",
        "posibilidad de conexión a la comunidad de regantes",
        "posibilidad de conexion a la comunidad de regantes",
        "se puede conectar a la comunidad de regantes", "agua cercana", "pozo cercano",
    ]),
    # ── SPÉCIAL : électricité réelle, EXCLUT « posibilidad de … solar » et « luz solar » ──
    ("electricity_available", "⚡ Électricité disponible", [
        "tiene luz", "con luz", "electricidad", "luz de red", "red eléctrica",
        "red electrica", "contador de luz", "contador eléctrico", "contador electrico",
        "luz dada de alta", "conectado a la red eléctrica",
        "conectada a la red eléctrica", "conectado a la luz", "grupo electrógeno",
        "grupo electrogeno", "placas solares", "paneles solares", "instalación solar",
        "instalacion solar", "sistema solar",
        "(exclut : posibilidad de placas solares, luz solar)",
    ]),
    ("electricity_none", "🔌 Sans électricité", [
        "sin luz", "sin electricidad", "no tiene luz", "no dispone de luz",
        "sin suministro eléctrico", "sin suministro electrico", "luz no conectada",
        "posibilidad de conectar luz", "poste de luz cerca",
    ]),
    ("autocaravana", "🚐 Autocaravana / Camping", [
        "autocaravana", "autocaravanas", "caravana", "caravanas", "camper", "campers",
        "furgón camper", "furgon camper", "camperizada", "camperizado", "mobil home",
        "mobile home", "apta para autocaravana", "ideal para autocaravana",
        "ideal para autocaravanas", "ideal para caravana", "ideal para caravanas",
        "ideal para camper", "perfecta para autocaravana", "perfecta para camper",
        "espacio para autocaravana", "espacio para caravana", "zona para autocaravana",
        "zona para caravanas", "aparcamiento de autocaravanas",
        "parking para autocaravanas", "se puede instalar una caravana",
        "se puede poner una caravana", "posibilidad de instalar una caravana",
        "posibilidad de poner una caravana", "se puede instalar una autocaravana",
        "posibilidad de instalar una autocaravana", "parcela para autocaravana",
        "parcela para caravana", "camping", "glamping", "camping comunitario",
    ]),
    ("good_access", "🛣️ Bon accès", [
        "buen acceso", "buen acceso por camino", "buen acceso por carretera",
        "fácil acceso", "facil acceso", "acceso cómodo", "acceso comodo",
        "acceso fácil", "acceso facil", "camino en buen estado", "camino bueno",
        "camino practicable", "acceso sin dificultad", "acceso asfaltado",
        "camino asfaltado", "carretera asfaltada", "todo asfaltado",
        "acceso por carretera asfaltada", "acceso totalmente asfaltado",
        "asfalto hasta la finca", "carretera hasta la finca", "buen acceso asfaltado",
        "excelente acceso", "muy buen acceso", "acceso inmejorable",
    ]),
    ("near_town", "🏙️ Proche village / ville", [
        "cerca del pueblo", "cerca de la población", "cerca de la poblacion",
        "cerca del casco urbano", "próximo al pueblo", "proximo al pueblo",
        "próximo a la población", "proximo a la poblacion", "muy bien comunicado",
        "bien comunicado", "cerca de todos los servicios",
        "próximo a todos los servicios", "proximo a todos los servicios",
        "todos los servicios", "todos los suministros", "cerca de comercios",
        "cerca de supermercados", "cerca de restaurantes", "cerca de colegios",
        "cerca del centro", "cerca del núcleo urbano", "cerca del nucleo urbano",
        "minutos del pueblo", "minutos de la población", "minutos de la poblacion",
        "minutos del casco urbano",
    ]),
    ("terrain_plat", "⬜ Terrain plat", [
        "terreno plano", "parcela plana", "finca plana",
        "totalmente plano", "totalmente plana",
        "prácticamente plano", "practicamente plano",
        "llano", "llana", "terreno llano", "finca llana", "parcela llana",
        "sin desnivel", "poco desnivel",
    ]),
    ("terrain_bancales", "🏔️ Terrain en niveaux / bancales", [
        "bancales", "terrazas", "terreno abancalado", "finca abancalada",
        "parcela abancalada", "en diferentes niveles", "en varios niveles",
        "varios bancales", "distintos bancales", "terreno con desnivel",
        "con desnivel", "desnivelado", "desnivelada",
    ]),
    ("pret_a_vivre", "🏠 Prêt à vivre", [
        "listo para entrar a vivir", "lista para entrar a vivir",
        "para entrar a vivir", "entrar a vivir",
        "lista para vivir", "listo para vivir",
        "habitable", "vivienda habitable",
        "perfecto estado", "perfecto estado de conservación",
        "perfecto estado de conservacion",
        "no necesita reforma", "sin necesidad de reforma",
        "cédula de habitabilidad", "cedula de habitabilidad",
        "cédula vigente", "cedula vigente",
        "cédula en vigor", "cedula en vigor",
        "licencia de segunda ocupación", "licencia de segunda ocupacion",
        "licencia de segunda ocupación vigente",
        "licencia de segunda ocupacion vigente",
        "segunda ocupación", "segunda ocupacion",
        "licencia de primera ocupación", "licencia de primera ocupacion",
        "primera ocupación", "primera ocupacion",
        "licencia de ocupación", "licencia de ocupacion",
        "licencia de uso y ocupación", "licencia de uso y ocupacion",
        "LPO",
    ]),
]

# ── Groupes spéciaux (logique non triviale) ─────────────────────────────────────
_SPECIAL = {"finca_buildable", "electricity_available"}

# finca_buildable : « finca » présent ET au moins une phrase « possibilité de construire »
_FINCA_RX = _re.compile(r"\bfinca\b", _FLAGS)
_BUILD_POSS = _compile_phrases([p for k, _, ph in _GROUPS if k == "finca_buildable" for p in ph])

# electricity_available : signaux non-solaires directs OU installation solaire RÉELLE
# (pas « posibilidad de … » ni « luz solar »).
_ELEC_CORE = _compile_phrases([
    "tiene luz", "con luz", "electricidad", "luz de red", "red eléctrica",
    "red electrica", "contador de luz", "contador eléctrico", "contador electrico",
    "luz dada de alta", "conectado a la red eléctrica", "conectada a la red eléctrica",
    "conectado a la luz", "grupo electrógeno", "grupo electrogeno",
])
_ELEC_SOLAR_RX = _re.compile(
    r"(?:placas? solares?|paneles? solares?|instalacion(?:es)? solar(?:es)?|"
    r"sistema solar){e<=1}", _FLAGS)


def _elec_match(nt: str, nta: str) -> bool:
    if _match_compiled(_ELEC_CORE, nt, nta):
        return True
    for m in _ELEC_SOLAR_RX.finditer(nt):
        if "posib" not in nt[max(0, m.start() - 25):m.start()]:
            return True
    return False


def _elec_spans(nt: str, nta: str):
    spans = _spans_compiled(_ELEC_CORE, nt, nta)
    for m in _ELEC_SOLAR_RX.finditer(nt):
        if "posib" not in nt[max(0, m.start() - 25):m.start()]:
            spans.append((m.start(), m.end()))
    return spans


def _fb_match(nt: str, nta: str) -> bool:
    return bool(_FINCA_RX.search(nt)) and _match_compiled(_BUILD_POSS, nt, nta)


def _fb_spans(nt: str, nta: str):
    spans = [(m.start(), m.end()) for m in _FINCA_RX.finditer(nt)]
    return spans + _spans_compiled(_BUILD_POSS, nt, nta)


_SPECIAL_MATCH = {"finca_buildable": _fb_match, "electricity_available": _elec_match}
_SPECIAL_SPANS = {"finca_buildable": _fb_spans, "electricity_available": _elec_spans}

# ── Construction des structures publiques ───────────────────────────────────────
SEARCH_SYNONYMS = {}
_COMPILED = {}
for _k, _label, _phrases in _GROUPS:
    # "patterns" = phrases (rétro-compat avec l'ancien code _search_freetext).
    SEARCH_SYNONYMS[_k] = {"label": _label, "terms": _phrases, "patterns": list(_phrases)}
    if _k not in _SPECIAL:
        _COMPILED[_k] = _compile_phrases(_phrases)


def text_matches(text: str, gk: str) -> bool:
    """True si la description (accent-insensible, fuzzy) déclenche le filtre gk."""
    nt, nta = norm(text), _lower(text)
    if gk in _SPECIAL_MATCH:
        return _SPECIAL_MATCH[gk](nt, nta)
    c = _COMPILED.get(gk)
    return _match_compiled(c, nt, nta) if c else False


def text_spans(text: str, gk: str):
    """Spans (start, end) des mots déclencheurs du filtre gk — offsets valides sur
    le TEXTE D'ORIGINE (la normalisation préserve la longueur)."""
    nt, nta = norm(text), _lower(text)
    if gk in _SPECIAL_SPANS:
        return _SPECIAL_SPANS[gk](nt, nta)
    c = _COMPILED.get(gk)
    return _spans_compiled(c, nt, nta) if c else []


# ── Exclusion « solar / urbain » (terrain constructible), énergie PRÉSERVÉE ──────
_SOLAR_TERRAIN_RX = _re.compile(
    r"\bsolar(?:es)?\s+(?:de\s+\d|ubicad[oa]s?|urban[oa]s?|edificable|residencial|"
    r"industrial|urbanizable|finalista|en\s+venta|en\s+esquina|vallad[oa]s?)"
    r"|(?:parcela|terreno|venta\s+del?|vendo|se\s+vende[n]?|magnifico|gran)\s+solar\b",
    _FLAGS)
_SOLAR_URBAN = _compile_phrases([
    "suelo urbano", "terreno urbano", "parcela urbana", "finca urbana",
    "suelo urbanizable", "terreno urbanizable", "parcela urbanizable",
    "urbano consolidado", "parcela edificable", "terreno edificable",
    "solar edificable", "obra nueva", "proyecto de obra nueva",
])


def is_solar_excluded(text: str) -> bool:
    """True si l'annonce relève du TERRAIN constructible / urbain (à exclure).
    Ne déclenche jamais sur « placas solares », « energía solar », etc."""
    nt = norm(text)
    if _SOLAR_TERRAIN_RX.search(nt):
        return True
    return _match_compiled(_SOLAR_URBAN, nt, nt)


# Rétro-compatibilité (ancien code/app non routé) : conservé inchangé.
SOLAR_EXCLUDE_PATTERN = _SOLAR_TERRAIN_RX.pattern

# ── Patterns agua / luz (anciens, utilisés par la page Recherche héritée) ────────
AGUA_CON_PATTERNS = [
    r"con\s+agua", r"agua\s+corriente", r"agua\s+potable",
    r"suministro\s+(?:de\s+)?agua", r"toma\s+(?:de\s+)?agua", r"\bpozo\b",
    r"acequia", r"agua\s+(?:de\s+)?red",
]
AGUA_SIN_PATTERNS = [
    r"sin\s+agua", r"sin\s+suministro\s+(?:de\s+)?agua",
    r"no\s+(?:tiene|dispone)\s+(?:de\s+)?agua", r"no\s+hay\s+agua",
]
AGUA_ANY = r"agua"

LUZ_CON_PATTERNS = [
    r"con\s+luz", r"luz\s+el[eé]ctrica", r"\belectricidad\b",
    r"suministro\s+(?:de\s+)?(?:luz|electricidad)", r"red\s+el[eé]ctrica",
    r"toma\s+(?:de\s+)?luz", r"corriente\s+el[eé]ctrica", r"acometida\s+el[eé]ctrica",
]
LUZ_SIN_PATTERNS = [
    r"sin\s+luz", r"sin\s+electricidad",
    r"sin\s+suministro\s+(?:de\s+)?(?:luz|electricidad)",
    r"no\s+(?:tiene|dispone)\s+(?:de\s+)?(?:luz|electricidad)", r"no\s+hay\s+luz",
]
LUZ_ANY = r"luz|electricidad"
