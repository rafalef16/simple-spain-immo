import json
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _use_supabase() -> bool:
    from modules.supabase_client import _use_supabase as _sb
    return _sb()


def _sb_upsert(listing: dict) -> bool:
    """Upsert one listing into Supabase listings table. Returns True on success."""
    try:
        from modules.supabase_client import get_client
        client = get_client()
        if not client:
            return False
        # Remove internal-only fields not in schema
        row = {k: v for k, v in listing.items() if k not in ("valide", "_match_score")}
        client.table("listings").upsert(row, on_conflict="url").execute()
        return True
    except Exception:
        return False


def _sb_load_all() -> list[dict]:
    """Load all non-deleted listings from Supabase."""
    try:
        from modules.supabase_client import get_client
        client = get_client()
        if not client:
            return []
        resp = (
            client.table("listings")
            .select("*")
            .is_("deleted_at", "null")
            .order("scrap_timestamp", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


# ── JSON local helpers ────────────────────────────────────────────────────────

def load(name: str) -> list[dict]:
    p = _path(name)
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _atomic_write(p: Path, data: list[dict]) -> None:
    """Atomic write: temp file → rename to avoid corrupt JSON on SIGINT."""
    tmp = p.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(p)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def save(name: str, data: list[dict]) -> None:
    _atomic_write(_path(name), data)


_CHECKPOINT_INTERVAL = 5
_checkpoint_counters: dict[str, int] = {}


def append_listing(name: str, listing: dict) -> bool:
    """Append a single listing; returns True if added, False if duplicate.
    Writes to Supabase when configured, always writes JSON as fallback/mirror.
    Every 5 new listings also rebuilds master.json as a checkpoint.
    """
    data = load(name)
    existing_ids = {item.get("id") for item in data}
    if listing.get("id") in existing_ids:
        return False
    existing_urls = {item.get("url") for item in data}
    if listing.get("url") in existing_urls:
        return False

    data.append(listing)
    _atomic_write(_path(name), data)

    # Supabase upsert (non-blocking; JSON is the source of truth if it fails)
    if _use_supabase():
        _sb_upsert(listing)

    # Checkpoint: rebuild master.json every N listings per source
    _checkpoint_counters[name] = _checkpoint_counters.get(name, 0) + 1
    if _checkpoint_counters[name] % _CHECKPOINT_INTERVAL == 0:
        try:
            merge_all_to_master()
        except Exception:
            pass
    return True


def load_processed_urls(name: str) -> set:
    return {item.get("url", "") for item in load(name)}


def _extract_ville(item: dict) -> Optional[str]:
    """Ville par regex sur titre/URL (le champ HTML varie selon chaque CMS)."""
    if item.get("ville") or item.get("localisation"):
        return item.get("ville") or item.get("localisation")
    title = item.get("title") or ""
    # "... en venta en Xerta, Tarragona" / "... en Roquetes" / "· Cambrils ..."
    m = re.search(r"\ben\s+(?:venta\s+(?:en\s+)?)?([A-ZÁÉÍÓÚ][\wáéíóúñ'’\-]+(?:\s+[A-ZÁÉÍÓÚ][\wáéíóúñ'’\-]+)?)", title)
    if m:
        return m.group(1).strip()
    # slug d'URL : /.../la-rapita/... ou -en-roquetes-es...
    url = item.get("url") or ""
    m = re.search(r"-en-([a-záéíóúñ\-]+?)-es\d", url) or re.search(r"/venta/([a-záéíóúñ\-]+)/", url)
    if m:
        return m.group(1).replace("-", " ").title()
    return None


# Mapping schéma scrape_v2 (data/v2) → schéma attendu par l'affichage Streamlit.
_DISPLAY_MAP = {
    "price_eur": "prix_eur",
    "image": "cover_image_url",
    "description": "description_clean",
    "scrap_ts": "scrap_timestamp",
}


def _normalize_for_display(item: dict) -> dict:
    """Harmonise un record v2 vers le schéma des cartes Streamlit (idempotent)."""
    out = dict(item)
    for src, dst in _DISPLAY_MAP.items():
        if out.get(dst) in (None, "") and out.get(src) not in (None, ""):
            out[dst] = out[src]
    # Surfaces : bâti (casita) → construction_m2 ; terrain → terrain_m2.
    if out.get("construction_m2") in (None, "") and out.get("built_m2") not in (None, ""):
        out["construction_m2"] = out["built_m2"]
    # Records hérités sans built/terrain explicites : surface_m2 → terrain par défaut.
    if (out.get("terrain_m2") in (None, "") and out.get("built_m2") in (None, "")
            and out.get("surface_m2") not in (None, "")):
        out["terrain_m2"] = out["surface_m2"]
    # ville
    if not out.get("ville"):
        v = _extract_ville(out)
        if v:
            out["ville"] = v
    # site_family / id / photos pour cohérence des cartes
    if not out.get("site_family"):
        out["site_family"] = out.get("agence") or out.get("site")
    if not out.get("id") and out.get("url"):
        out["id"] = hashlib.sha256(out["url"].encode()).hexdigest()
    if not out.get("photos") and out.get("cover_image_url"):
        out["photos"] = [out["cover_image_url"]]
    return out


def merge_all_to_master() -> list[dict]:
    """Merge all per-site JSON files into master.json with dedup."""
    master: dict[str, dict] = {}
    master_path = DATA_DIR / "master.json"

    if master_path.exists():
        try:
            for item in json.loads(master_path.read_text(encoding="utf-8")):
                master[item.get("url") or item.get("id", "")] = _normalize_for_display(item)
        except Exception:
            pass

    for p in (DATA_DIR / "v2").glob("*.json"):
        if p.name in ("master.json", "clients.json", "session_pool.json"):
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            key = item.get("url") or item.get("id", "")
            if key not in master:
                master[key] = _normalize_for_display(item)

    result = sorted(master.values(), key=lambda x: x.get("scrap_timestamp", ""), reverse=True)
    _atomic_write(master_path, result)
    return result


def load_master() -> list[dict]:
    """Load master.json, or fall back to Supabase if configured."""
    if _use_supabase():
        sb_data = _sb_load_all()
        if sb_data:
            return sb_data

    p = DATA_DIR / "master.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def scrape_stats() -> dict:
    stats = {"total": 0, "by_site": {}, "last_run": None}
    for p in (DATA_DIR / "v2").glob("*.json"):
        if p.name in ("master.json", "clients.json", "session_pool.json"):
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                continue
            site = p.stem
            stats["by_site"][site] = len(items)
            stats["total"] += len(items)
            if items:
                last = max(items, key=lambda x: x.get("scrap_timestamp", ""), default=None)
                if last:
                    ts = last.get("scrap_timestamp", "")
                    if not stats["last_run"] or ts > stats["last_run"]:
                        stats["last_run"] = ts
        except Exception:
            pass
    return stats
