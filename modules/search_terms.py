"""
Synonymes et patterns regex pour la recherche granulaire.
Chaque groupe: label (UI), terms (affichage), patterns (regex match).
"""

SEARCH_SYNONYMS = {
    "water_feature": {
        "label": "💧 Piscine / Bassin",
        "terms": ["piscina", "balsa", "alberca", "pool", "bassa"],
        "patterns": [
            r"pisc(?:ina)?",
            r"\bbalsa\b",
            r"alberca",
            r"\bpool\b",
            r"\bbassa\b",
        ],
    },
    "sea_view": {
        "label": "🌊 Vue mer",
        "terms": ["vista al mar", "vistas al mar", "vista sobre el mar", "vista marina", "frente al mar"],
        "patterns": [
            r"vistas?\s+(?:al|sobre|del)\s+(?:el\s+)?mar",
            r"vista\s+marina",
            r"frente\s+al\s+mar",
            r"vista\s+(?:al\s+)?mar",
        ],
    },
    "mountain_view": {
        "label": "⛰️ Vue montagne",
        "terms": ["vista montaña", "vistas montaña", "vista al monte", "sierra"],
        "patterns": [
            r"vistas?\s+(?:a\s+la?\s+)?monta[ñn]",
            r"vista\s+al\s+monte",
            r"entorno\s+monta[ñn]oso",
            r"\bsierra\b",
        ],
    },
    "fence": {
        "label": "🚧 Vallado",
        "terms": ["vallado", "vallada", "cercado", "vallados", "valladas", "cerrado"],
        "patterns": [
            r"vall(?:ad|ada)s?",
            r"cerc(?:ad|ada)s?",
            r"\bcerrado\b",
        ],
    },
    "finca_construida": {
        "label": "🏠 Finca construida",
        "terms": ["finca construida", "casa rural", "con construcción", "vivienda rural", "masía"],
        "patterns": [
            r"finca\s+construida",
            r"casa\s+rural",
            r"con\s+construcci[oó]n",
            r"vivienda\s+rural",
            r"mas[ií]a",
            r"\d+\s*m[²2]?\s*(?:de\s+)?(?:construid|edificad)",
        ],
    },
    "finca_rustica": {
        "label": "🌿 Finca rústica (sin construir)",
        "terms": ["finca rústica", "terreno rústico", "sin construcción", "sin edificar"],
        "patterns": [
            r"finca\s+r[uú]stica",
            r"terreno\s+r[uú]stico",
            r"sin\s+construcci[oó]n",
            r"sin\s+edificar",
            r"finca\s+sin\s+construir",
            r"suelo\s+r[uú]stico",
        ],
    },
    "olive_trees": {
        "label": "🫒 Oliviers",
        "terms": ["olivar", "olivares", "olivo", "olivos", "olivero"],
        "patterns": [
            r"olivar(?:es)?",
            r"olivo(?:s)?",
            r"olivero(?:s)?",
        ],
    },
    "almond_trees": {
        "label": "🌰 Amandiers",
        "terms": ["almendro", "almendros", "ametller", "almendral"],
        "patterns": [
            r"almendro(?:s)?",
            r"almendral",
            r"ametller",
        ],
    },
    "carob_trees": {
        "label": "🌾 Caroubiers",
        "terms": ["algarrobo", "algarrobos", "garrofer", "garrofes"],
        "patterns": [
            r"algarrob(?:o|os)",
            r"garrofer",
            r"garrofes",
        ],
    },
    "tourism_license": {
        "label": "🏖️ Licence touristique",
        "terms": ["licencia turística", "licencia turistica", "airbnb", "alquiler vacacional"],
        "patterns": [
            r"licencia\s+tur[ií]stic[ao]",
            r"\bairbnb\b",
            r"alquiler\s+vacacional",
            r"habitaci[oó]n\s+tur[ií]stic",
        ],
    },
    "river_access": {
        "label": "🏞️ Accès rivière / acequia",
        "terms": ["río", "rio", "acequia", "riera", "ribera"],
        "patterns": [
            r"\br[ií]o\b",
            r"acequia",
            r"riera",
            r"ribera",
        ],
    },
    "garage": {
        "label": "🚗 Garage / hangar",
        "terms": ["garaje", "garage", "nave", "hangar", "cochera"],
        "patterns": [
            r"garaje",
            r"garage",
            r"\bnave\b",
            r"hangar",
            r"cochera",
        ],
    },
    "casa": {
        "label": "🏡 Casa / caseta de campo",
        "terms": ["casa", "casa rural", "caseta", "caseta de campo", "cabaña", "vivienda", "masía"],
        "patterns": [
            r"\bcasa\b",
            r"casa\s+rural",
            r"caseta(?:\s+de\s+campo)?",
            r"caba[ñn]a",
            r"vivienda",
            r"mas[ií]a",
        ],
    },
    "almacen": {
        "label": "📦 Almacén / annexe",
        "terms": ["almacén", "almacen", "trastero", "cobertizo", "establo", "corral"],
        "patterns": [
            r"almac[eé]n",
            r"trastero",
            r"cobertiz[oa]",
            r"establo",
            r"corral",
        ],
    },
    "surface_built": {
        "label": "📐 Surface bâtie (NN m²)",
        "terms": ["m² construidos", "edificados", "vivienda de X m²", "construida"],
        "patterns": [
            r"\d+\s*m[²2]",                       # toute surface chiffrée en m²
            r"construid[oa]s?",
            r"edificad[oa]s?",
            r"superficie\s+(?:construida|edificada|[uú]til)",
        ],
    },
}

# ── Patterns agua / luz (utilisés directement dans app.py) ──────────────────

AGUA_CON_PATTERNS = [
    r"con\s+agua",
    r"agua\s+corriente",
    r"agua\s+potable",
    r"suministro\s+(?:de\s+)?agua",
    r"toma\s+(?:de\s+)?agua",
    r"\bpozo\b",
    r"acequia",
    r"agua\s+(?:de\s+)?red",
]

AGUA_SIN_PATTERNS = [
    r"sin\s+agua",
    r"sin\s+suministro\s+(?:de\s+)?agua",
    r"no\s+(?:tiene|dispone)\s+(?:de\s+)?agua",
    r"no\s+hay\s+agua",
]

AGUA_ANY = r"agua"

LUZ_CON_PATTERNS = [
    r"con\s+luz",
    r"luz\s+el[eé]ctrica",
    r"\belectricidad\b",
    r"suministro\s+(?:de\s+)?(?:luz|electricidad)",
    r"red\s+el[eé]ctrica",
    r"toma\s+(?:de\s+)?luz",
    r"corriente\s+el[eé]ctrica",
    r"acometida\s+el[eé]ctrica",
]

LUZ_SIN_PATTERNS = [
    r"sin\s+luz",
    r"sin\s+electricidad",
    r"sin\s+suministro\s+(?:de\s+)?(?:luz|electricidad)",
    r"no\s+(?:tiene|dispone)\s+(?:de\s+)?(?:luz|electricidad)",
    r"no\s+hay\s+luz",
]

LUZ_ANY = r"luz|electricidad"
