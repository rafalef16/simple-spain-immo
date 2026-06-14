PYTHON := /Users/monix/miniforge3/bin/python3
APP    := app.py

.PHONY: help scrape scrape-mobilia scrape-thinkspain scrape-kyero \
        scrape-fotocasa scrape-idealista merge app install dry-run

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*##"}{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

install: ## Install Python dependencies
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m playwright install chromium

scrape: ## Run ALL scrapers (Mobilia + ThinkSpain + Kyero + Fotocasa + Idealista)
	$(PYTHON) pipeline.py --sites all

scrape-mobilia: ## Run Mobilia scraper only (38 sites, no proxy needed)
	$(PYTHON) pipeline.py --sites mobilia

scrape-thinkspain: ## Run ThinkSpain scraper only
	$(PYTHON) pipeline.py --sites thinkspain

scrape-kyero: ## Run Kyero scraper only
	$(PYTHON) pipeline.py --sites kyero

scrape-fotocasa: ## Run Fotocasa scraper (requires EVOMI proxy)
	$(PYTHON) pipeline.py --sites fotocasa

scrape-idealista: ## Run Idealista scraper (requires EVOMI proxy)
	$(PYTHON) pipeline.py --sites idealista

scrape-regional: ## Run 14 JS-rendered local agencies (Playwright, no proxy)
	$(PYTHON) pipeline.py --sites regional

scrape-no-proxy: ## Run all scrapers that don't need a proxy
	$(PYTHON) pipeline.py --sites thinkspain kyero mobilia regional

dry-run: ## Test all scrapers without writing files
	$(PYTHON) pipeline.py --dry-run

merge: ## Merge all JSON files into master.json
	$(PYTHON) pipeline.py --merge-only

app: ## Launch Streamlit UI
	streamlit run $(APP) --server.port 8501

app-dev: ## Launch UI in dev mode (auto-reload)
	streamlit run $(APP) --server.runOnSave true --server.port 8501

stats: ## Show scrape stats
	$(PYTHON) -c "from modules.db import scrape_stats; import json; print(json.dumps(scrape_stats(), indent=2))"

clean-logs: ## Remove old log files
	rm -f logs/*.log

data-count: ## Count listings per source
	$(PYTHON) -c "
import json, glob
for f in sorted(glob.glob('data/*.json')):
    if 'master' in f: continue
    try:
        items = json.load(open(f))
        print(f'{f:50s} {len(items):5d}')
    except: pass
"
