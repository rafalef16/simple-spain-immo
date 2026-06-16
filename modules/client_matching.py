"""
Client-listing matching engine.
Scores each listing against client criteria and returns sorted matches.
"""
from __future__ import annotations


def _detect_type_local(l: dict) -> str:
    t = (l.get("type") or "").lower()
    title = (l.get("title") or "").lower()
    combined = t + " " + title
    if any(w in combined for w in ["finca", "rustic", "terreno", "terrain", "solar", "rural"]):
        return "finca"
    if any(w in combined for w in ["chalet", "villa", "casa", "maison", "masia"]):
        return "casa"
    if any(w in combined for w in ["tourist", "touristic", "airbnb", "booking", "vacacional"]):
        return "touristic"
    return "autre"


def _normalize_ville(v: str) -> str:
    return v.lower().strip()


def match_listing(listing: dict, profile: dict) -> tuple[bool, float]:
    """
    Return (matches: bool, score: float 0..1).
    Hard filters: budget, terrain, construction, ville, type.
    Soft score: keyword matches in description.
    """
    score = 0.0
    penalties = 0

    prix = listing.get("prix_eur") or 0
    terrain = listing.get("terrain_m2") or 0
    construction = listing.get("construction_m2") or 0
    ville = _normalize_ville(listing.get("ville_canonical") or listing.get("ville") or "")
    desc = ((listing.get("title") or "") + " " + (listing.get("description_clean") or "")).lower()

    # Hard filters — disqualify immediately
    if profile.get("budget_min") and prix > 0 and prix < profile["budget_min"]:
        return False, 0.0
    if profile.get("budget_max") and prix > profile["budget_max"]:
        return False, 0.0
    if profile.get("terrain_min") and terrain > 0 and terrain < profile["terrain_min"]:
        return False, 0.0
    if profile.get("terrain_max") and terrain > profile["terrain_max"]:
        return False, 0.0
    if profile.get("construction_min") and construction > 0 and construction < profile["construction_min"]:
        return False, 0.0
    if profile.get("construction_max") and construction > profile["construction_max"]:
        return False, 0.0

    villes = [_normalize_ville(v) for v in (profile.get("villes") or [])]
    if villes and ville and not any(v in ville or ville in v for v in villes):
        return False, 0.0

    must_not = [kw.lower() for kw in (profile.get("keywords_must_not") or [])]
    if any(kw in desc for kw in must_not):
        return False, 0.0

    # Soft score
    if prix > 0:
        score += 0.2

    must = [kw.lower() for kw in (profile.get("keywords_must") or [])]
    if must:
        matched = sum(1 for kw in must if kw in desc)
        score += 0.4 * (matched / len(must))
    else:
        score += 0.4

    types = [t.lower() for t in (profile.get("types") or [])]
    if not types or _detect_type_local(listing) in types:
        score += 0.2

    if listing.get("cover_image_url"):
        score += 0.1
    if terrain > 0:
        score += 0.1

    return True, round(score, 3)


def rank_listings(listings: list[dict], profile: dict) -> list[dict]:
    """Return listings that match profile, sorted by score descending."""
    results = []
    for l in listings:
        matches, score = match_listing(l, profile)
        if matches:
            results.append({**l, "_match_score": score})
    return sorted(results, key=lambda x: x["_match_score"], reverse=True)
