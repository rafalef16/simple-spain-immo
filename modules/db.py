import json
import os
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


def merge_all_to_master() -> list[dict]:
    """Merge all per-site JSON files into master.json with dedup."""
    master: dict[str, dict] = {}
    master_path = DATA_DIR / "master.json"

    if master_path.exists():
        try:
            for item in json.loads(master_path.read_text(encoding="utf-8")):
                master[item.get("id", item.get("url", ""))] = item
        except Exception:
            pass

    for p in DATA_DIR.glob("*.json"):
        if p.name in ("master.json", "clients.json"):
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in items:
            key = item.get("id") or item.get("url", "")
            if key not in master:
                master[key] = item

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
    for p in DATA_DIR.glob("*.json"):
        if p.name in ("master.json", "clients.json"):
            continue
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
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
