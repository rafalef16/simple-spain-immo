#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  Simple Spain — Script de démarrage unique
#  Usage : ./start.sh
# ─────────────────────────────────────────────────────────────────
set -e
PYTHON=/Users/monix/miniforge3/bin/python3
STREAMLIT=/Users/monix/miniforge3/bin/streamlit
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "═══════════════════════════════════════════════════════════"
echo "  SIMPLE SPAIN — Intelligence Immobilière Catalane"
echo "═══════════════════════════════════════════════════════════"

# Vérifier .env
if [ ! -f .env ]; then
  echo "📋 Création du fichier .env depuis .env.example..."
  cp .env.example .env
fi

# Vérifier dépendances
echo "📦 Vérification des dépendances..."
$PYTHON -c "import streamlit, playwright" 2>/dev/null || {
  echo "⚙️  Installation des dépendances..."
  $PYTHON -m pip install -r requirements.txt -q
  $PYTHON -m playwright install chromium
  STREAMLIT=/Users/monix/miniforge3/bin/streamlit
}

echo ""
echo "Que voulez-vous faire ?"
echo "  1) Lancer l'interface Streamlit (UI)"
echo "  2) Lancer le scraper complet (toutes sources, EVOMI actif partout)"
echo "  3) Lancer le scraper sources locales (Mobilia + ThinkSpain + Kyero + Regional, EVOMI actif)"
echo "  4) Lancer le scraper portails (Fotocasa + Idealista, EVOMI actif)"
echo "  5) Fusionner les données JSON → master.json"
echo "  6) TEST — dry-run toutes sources (EVOMI actif, limite annonces/site)"
echo "  7) DIAG — 1 annonce par site local (mobilia+regional), dry-run"
echo "  8) Quitter"
echo ""
read -p "Choix [1-8] : " choice

case $choice in
  1)
    echo "🚀 Lancement de l'interface..."
    $STREAMLIT run app.py --server.port 8501
    ;;
  2)
    echo "🕷️  Scraper complet (scrape_v2 — EVOMI + 2captcha)..."
    $PYTHON scrape_v2.py --site all --limit 10
    $PYTHON -c "from modules.db import merge_all_to_master; merge_all_to_master()"
    ;;
  3)
    echo "🕷️  Scraper sources locales (Mobilia)..."
    $PYTHON scrape_v2.py --site mobilia --limit 10
    $PYTHON -c "from modules.db import merge_all_to_master; merge_all_to_master()"
    ;;
  4)
    echo "🕷️  Scraper portails (Fotocasa + Idealista, EVOMI + 2captcha)..."
    $PYTHON scrape_v2.py --site fotocasa --limit 10
    $PYTHON scrape_v2.py --site idealista --limit 10
    $PYTHON -c "from modules.db import merge_all_to_master; merge_all_to_master()"
    ;;
  5)
    echo "🔀 Fusion des données → master.json..."
    $PYTHON -c "from modules.db import merge_all_to_master; print(len(merge_all_to_master()), 'annonces')"
    ;;
  6)
    echo "🧪 TEST — 2 URLs par source (scrape_v2, toutes sources)..."
    $PYTHON scrape_v2.py --site all --limit 2
    $PYTHON -c "from modules.db import merge_all_to_master; merge_all_to_master()"
    ;;
  7)
    echo "🔬 DIAG — 1 annonce Mobilia..."
    $PYTHON scrape_v2.py --site mobilia --limit 1
    ;;
  *)
    echo "Au revoir."
    ;;
esac
