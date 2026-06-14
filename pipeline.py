#!/usr/bin/env python3
"""
Main ETL pipeline.
Usage:
  python pipeline.py                  # Run all scrapers
  python pipeline.py --sites thinkspain kyero
  python pipeline.py --sites mobilia
  python pipeline.py --dry-run
  python pipeline.py --merge-only
"""
import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "pipeline.log"),
    ],
)
log = logging.getLogger("pipeline")

SCRAPER_MAP = {
    "thinkspain": "scrapers.thinkspain",
    "kyero":      "scrapers.kyero",
    "fotocasa":   "scrapers.fotocasa",
    "idealista":  "scrapers.idealista",
    "mobilia":    "scrapers.mobilia",   # 7 static CMS families (35 sub-sites)
    "regional":   "scrapers.regional",  # 14 JS-rendered small agencies
}


def run_scraper(name: str, dry_run: bool, limit: int = 0) -> int:
    import importlib
    mod = importlib.import_module(SCRAPER_MAP[name])
    log.info("=" * 50)
    log.info("Starting scraper: %s", name.upper())
    t0 = time.time()
    try:
        import inspect
        sig = inspect.signature(mod.run)
        kwargs = {"dry_run": dry_run}
        if "limit" in sig.parameters and limit:
            kwargs["limit"] = limit
        results = mod.run(**kwargs)
        elapsed = time.time() - t0
        log.info("Done %s: %d listings in %.1fs", name, len(results), elapsed)
        return len(results)
    except Exception as e:
        log.error("Scraper %s FAILED: %s", name, e, exc_info=True)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Real Estate Intelligence Pipeline")
    parser.add_argument(
        "--sites", nargs="+",
        choices=list(SCRAPER_MAP.keys()) + ["all"],
        default=["all"],
        help="Which scrapers to run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write to disk")
    parser.add_argument("--merge-only", action="store_true", help="Only merge JSON files to master")
    parser.add_argument("--limit", type=int, default=0, help="Cap detail URLs per site config entry (0 = no limit)")
    args = parser.parse_args()

    if args.merge_only:
        from modules.db import merge_all_to_master
        master = merge_all_to_master()
        log.info("Merged %d total listings into master.json", len(master))
        return

    sites = list(SCRAPER_MAP.keys()) if "all" in args.sites else args.sites
    total = 0

    for site in sites:
        total += run_scraper(site, args.dry_run, args.limit)

    if not args.dry_run:
        from modules.db import merge_all_to_master
        master = merge_all_to_master()
        log.info("=" * 50)
        log.info("Pipeline complete — %d new listings | %d total in master", total, len(master))
    else:
        log.info("DRY RUN complete — %d listings found", total)


if __name__ == "__main__":
    main()
