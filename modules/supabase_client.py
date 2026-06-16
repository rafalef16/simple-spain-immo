"""
Supabase client — lazy singleton.
Falls back silently to None when SUPABASE_URL is absent from .env.
"""
import os
from dotenv import load_dotenv

load_dotenv()

_client = None
_tried = False


def get_client():
    """Return Supabase client or None if not configured."""
    global _client, _tried
    if _tried:
        return _client
    _tried = True

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
    except Exception:
        _client = None
    return _client


def _use_supabase() -> bool:
    return get_client() is not None
