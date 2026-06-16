"""
Client profile parser — converts raw text into structured criteria.
Uses LLM when available, falls back to keyword heuristics.
"""
import re
from modules.llm_client import parse_client_profile


def _parse_budget_heuristic(text: str) -> tuple[int | None, int | None]:
    text = text.replace(".", "").replace(",", "").replace(" ", "")
    nums = [int(m) for m in re.findall(r'\d{4,7}', text)]
    nums = [n for n in nums if 10_000 <= n <= 5_000_000]
    if len(nums) >= 2:
        return min(nums), max(nums)
    if len(nums) == 1:
        return None, nums[0]
    return None, None


def _parse_surface_heuristic(text: str, keywords: list[str]) -> int | None:
    for kw in keywords:
        m = re.search(rf'{kw}[^\d]{{0,20}}(\d{{2,5}})', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def parse(name: str, raw_text: str) -> dict:
    """
    Return a client profile dict ready to store.
    Tries LLM first, then heuristics.
    """
    profile: dict = {
        "name": name,
        "raw_text": raw_text,
        "budget_min": None,
        "budget_max": None,
        "terrain_min": None,
        "terrain_max": None,
        "construction_min": None,
        "construction_max": None,
        "villes": [],
        "types": [],
        "keywords_must": [],
        "keywords_must_not": [],
    }

    llm_result = parse_client_profile(raw_text)
    if llm_result:
        for key in ("budget_min", "budget_max", "terrain_min", "terrain_max",
                    "construction_min", "construction_max", "villes", "types",
                    "keywords_must", "keywords_must_not"):
            val = llm_result.get(key)
            if val is not None:
                profile[key] = val
        return profile

    # Heuristic fallback
    b_min, b_max = _parse_budget_heuristic(raw_text)
    profile["budget_min"] = b_min
    profile["budget_max"] = b_max
    profile["terrain_min"] = _parse_surface_heuristic(raw_text, ["terrain", "terreno", "parcelle"])
    profile["construction_min"] = _parse_surface_heuristic(raw_text, ["construction", "bâti", "maison"])

    text_lower = raw_text.lower()
    if any(w in text_lower for w in ["finca", "rural", "rustic", "campo"]):
        profile["types"].append("finca")
    if any(w in text_lower for w in ["maison", "chalet", "villa", "casa"]):
        profile["types"].append("casa")
    if any(w in text_lower for w in ["tourist", "airbnb", "vacaciones", "licencia"]):
        profile["types"].append("touristic")

    return profile
