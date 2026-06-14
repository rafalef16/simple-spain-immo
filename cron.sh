#!/bin/bash
# ============================================================
# Simple Spain — Daily scraping cron
#
# SETUP (run once):
#   chmod +x cron.sh
#   crontab -e
#
# CRON LINE (every day at 06:00):
#   0 6 * * * /Users/monix/immo_intel/cron.sh >> /Users/monix/immo_intel/logs/cron.log 2>&1
#
# CRON LINE (every day at 06:00 + 18:00):
#   0 6,18 * * * /Users/monix/immo_intel/cron.sh >> /Users/monix/immo_intel/logs/cron.log 2>&1
# ============================================================

set -e
cd "$(dirname "$0")"

PYTHON="/Users/monix/miniforge3/bin/python3"
LOGFILE="logs/cron_$(date +%Y%m%d).log"

echo "========================================" | tee -a "$LOGFILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') — Starting pipeline" | tee -a "$LOGFILE"

# Step 1: Scrape no-proxy sites first (fast, safe)
echo "--- [1/3] Mobilia + ThinkSpain + Kyero" | tee -a "$LOGFILE"
$PYTHON pipeline.py --sites thinkspain kyero mobilia 2>&1 | tee -a "$LOGFILE"

# Step 2: Proxy-based scrapers (Fotocasa + Idealista)
echo "--- [2/3] Fotocasa + Idealista (proxy)" | tee -a "$LOGFILE"
$PYTHON pipeline.py --sites fotocasa idealista 2>&1 | tee -a "$LOGFILE"

# Step 3: Merge all to master.json
echo "--- [3/3] Merge to master.json" | tee -a "$LOGFILE"
$PYTHON pipeline.py --merge-only 2>&1 | tee -a "$LOGFILE"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Done" | tee -a "$LOGFILE"
echo "========================================" | tee -a "$LOGFILE"
