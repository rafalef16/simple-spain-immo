"""
LLM client — Claude Haiku for translations and profile parsing.
Returns empty strings if ANTHROPIC_API_KEY is absent.
"""
import os
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

_client = None
_tried = False


def _get_client():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=key)
    except Exception:
        _client = None
    return _client


def translate_and_anonymize(listing_id: str, text: str, target_lang: str) -> dict:
    """
    Translate listing text to target_lang (fr|en|de) and anonymize location.
    Returns dict with keys: title_tr, desc_tr, location_anon.
    Returns empty strings on failure or missing API key.
    """
    client = _get_client()
    if not client or not text:
        return {"title_tr": "", "desc_tr": "", "location_anon": ""}

    lang_names = {"fr": "French", "en": "English", "de": "German"}
    lang_name = lang_names.get(target_lang, "English")

    prompt = f"""You are a real estate translation assistant.
Translate the following Spanish property listing description to {lang_name}.
Also provide an anonymized location (remove specific street/number, keep only town/region).

Text to translate:
{text[:3000]}

Respond ONLY as valid JSON with this exact structure:
{{
  "desc_tr": "<translated description>",
  "location_anon": "<anonymized location, {lang_name}>"
}}"""

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        raw = message.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        return {
            "title_tr": "",
            "desc_tr": result.get("desc_tr", ""),
            "location_anon": result.get("location_anon", ""),
        }
    except Exception:
        return {"title_tr": "", "desc_tr": "", "location_anon": ""}


def parse_client_profile(raw_text: str) -> dict:
    """
    Parse natural language client requirements into structured criteria.
    Returns structured dict or empty criteria on failure.
    """
    client = _get_client()
    if not client or not raw_text:
        return {}

    prompt = f"""You are a real estate CRM assistant.
Parse the following client requirements (written in French, English, or Spanish) into structured criteria.

Client text:
{raw_text[:2000]}

Respond ONLY as valid JSON:
{{
  "budget_min": <int or null>,
  "budget_max": <int or null>,
  "terrain_min": <int m² or null>,
  "terrain_max": <int m² or null>,
  "construction_min": <int m² or null>,
  "construction_max": <int m² or null>,
  "villes": [<list of town names or empty>],
  "types": [<list from: finca, casa, touristic, autre>],
  "keywords_must": [<required keywords in description>],
  "keywords_must_not": [<excluded keywords>]
}}"""

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        raw = message.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {}
