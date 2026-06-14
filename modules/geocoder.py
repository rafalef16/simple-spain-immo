"""
Static GPS coordinates for ~65 municipalities in Terres de l'Ebre,
Delta de l'Ebre, Priorat, Montsià, Baix Ebre and surrounding area.
No network calls — fully offline.
"""
import unicodedata
from difflib import SequenceMatcher

COORDS_CATALOG: dict[str, tuple[float, float]] = {
    # Baix Ebre
    "Tortosa":                    (40.8121, 0.5212),
    "Roquetes":                   (40.8300, 0.4969),
    "Xerta":                      (40.8500, 0.5236),
    "Tivenys":                    (40.8725, 0.5386),
    "Benifallet":                 (40.9033, 0.5628),
    "Rasquera":                   (40.9497, 0.6411),
    "Perelló":                    (40.8933, 0.7022),
    "L'Aldea":                    (40.7167, 0.5333),
    "Aldover":                    (40.8550, 0.5108),
    "Paüls":                      (40.8936, 0.5031),
    "Alfara de Carles":           (40.8639, 0.4422),
    # Delta de l'Ebre
    "Amposta":                    (40.7063, 0.5786),
    "Deltebre":                   (40.7220, 0.7092),
    "Sant Jaume d'Enveja":        (40.7333, 0.7878),
    "Camarles":                   (40.7614, 0.7050),
    "L'Ampolla":                  (40.8036, 0.6956),
    "L'Ametlla de Mar":           (40.8728, 0.7806),
    # Montsià
    "Sant Carles de la Ràpita":   (40.6207, 0.5952),
    "Alcanar":                    (40.5393, 0.4778),
    "Ulldecona":                  (40.5980, 0.4480),
    "La Sénia":                   (40.6403, 0.2858),
    "Mas de Barberans":           (40.6553, 0.3508),
    "Freginals":                  (40.6003, 0.4600),
    "Santa Bàrbara":              (40.6811, 0.4681),
    "Godall":                     (40.6233, 0.4267),
    "Masdenverge":                (40.6856, 0.5425),
    "La Galera":                  (40.7528, 0.4428),
    "Galera":                     (40.7528, 0.4428),
    # Terra Alta
    "Gandesa":                    (41.0528, 0.4542),
    "Bot":                        (40.9883, 0.3914),
    "Horta de Sant Joan":         (40.9242, 0.3272),
    "Arnes":                      (40.8958, 0.2725),
    "Prat de Comte":              (40.9150, 0.3072),
    "La Fatarella":               (41.1017, 0.5214),
    "Corbera d'Ebre":             (41.0386, 0.5197),
    "Pinell de Brai":             (40.9731, 0.5278),
    "El Pinell":                  (40.9731, 0.5278),
    "Massaluca":                  (41.1336, 0.4694),
    "Vilalba dels Arcs":          (41.0847, 0.3917),
    "Batea":                      (41.1153, 0.2883),
    "Caseres":                    (41.0000, 0.3197),
    "Nonasp":                     (41.1814, 0.0728),
    # Ribera d'Ebre
    "Miravet":                    (41.0050, 0.5889),
    "Benissanet":                 (41.0692, 0.6203),
    "Ginestar":                   (41.0178, 0.6714),
    "Tivissa":                    (41.0428, 0.7236),
    "Vinebre":                    (41.1383, 0.5492),
    "Riba-roja d'Ebre":           (41.1478, 0.5364),
    "Ascó":                       (41.1972, 0.5664),
    "Garcia":                     (41.1267, 0.6303),
    "Flix":                       (41.2339, 0.5414),
    "Móra d'Ebre":                (41.0875, 0.6369),
    "Móra la Nova":               (41.1000, 0.6514),
    "Mola":                       (41.0278, 0.7044),
    # Baix Camp / Costa Daurada
    "L'Hospitalet de l'Infant":   (40.9994, 0.9208),
    "Miami Platja":               (40.9769, 0.9633),
    "Vandellòs":                  (41.0083, 0.8892),
    "Pratdip":                    (41.0025, 0.9094),
    "Cambrils":                   (41.0656, 1.0594),
    "Salou":                      (41.0761, 1.1436),
    "Tarragona":                  (41.1189, 1.2445),
    # Alt Camp / Conca de Barberà
    "Montblanc":                  (41.3756, 1.1625),
    # Alt Empordà
    "Roses":                      (42.2673, 3.1753),
    "Portbou":                    (42.4275, 3.1647),
    # Aliases courts fréquents dans les URLs scrappées
    "La Rapita":                  (40.6207, 0.5952),
    "Rapita":                     (40.6207, 0.5952),
    "Sant Carles":                (40.6207, 0.5952),
    "La Cava":                    (40.7220, 0.7092),
    "Riumar":                     (40.7422, 0.8483),
    "Poble Nou del Delta":        (40.6989, 0.7853),
    "Poble Nou":                  (40.6989, 0.7853),
    "Els Muntells":               (40.7069, 0.6583),
    "L'Encanyissada":             (40.6833, 0.7167),
    "Aldea":                      (40.7167, 0.5333),
    "Ametlla":                    (40.8728, 0.7806),
    "Ampolla":                    (40.8036, 0.6956),
}

# Normalised lookup table (no accents, lowercase)
def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()

_NORM_CATALOG: dict[str, tuple[float, float]] = {
    _norm(k): v for k, v in COORDS_CATALOG.items()
}


def resolve_coords(city_raw: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) for a city name, or None if unknown.
    No network call — static lookup only.
    """
    if not city_raw:
        return None

    # 1. Exact match
    if city_raw in COORDS_CATALOG:
        return COORDS_CATALOG[city_raw]

    # 2. Normalised exact match
    key = _norm(city_raw.strip())
    if key in _NORM_CATALOG:
        return _NORM_CATALOG[key]

    # 3. Fuzzy match (similarity >= 0.80)
    best_score = 0.0
    best_coords = None
    for norm_key, coords in _NORM_CATALOG.items():
        score = SequenceMatcher(None, key, norm_key).ratio()
        if score > best_score:
            best_score = score
            best_coords = coords

    if best_score >= 0.80:
        return best_coords

    return None
