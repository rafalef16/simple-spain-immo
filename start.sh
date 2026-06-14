#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  Simple Spain — Script de démarrage unique
#  Usage : ./start.sh
# ─────────────────────────────────────────────────────────────────
set -e
PYTHON=/Users/monix/miniforge3/bin/python3
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
}

echo ""
echo "Que voulez-vous faire ?"
echo "  1) Lancer l'interface Streamlit (UI)"
echo "  2) Lancer le scraper complet (toutes sources)"
echo "  3) Lancer le scraper sans proxy (Mobilia + ThinkSpain + Kyero)"
echo "  4) Lancer le scraper proxy uniquement (Fotocasa + Idealista)"
echo "  5) Fusionner les données JSON → master.json"
echo "  6) Quitter"
echo ""
read -p "Choix [1-6] : " choice

case $choice in
  1)
    echo "🚀 Lancement de l'interface..."
    streamlit run app.py --server.port 8501
    ;;
  2)
    echo "🕷️  Scraper complet..."
    $PYTHON pipeline.py --sites all
    ;;
  3)
    echo "🕷️  Scraper sans proxy..."
    $PYTHON pipeline.py --sites mobilia thinkspain kyero regional
    ;;
  4)
    echo "🕷️  Scraper avec proxy EVOMI..."
    $PYTHON pipeline.py --sites fotocasa idealista
    ;;
  5)
    echo "🔀 Fusion des données..."
    $PYTHON pipeline.py --merge-only
    ;;
  *)
    echo "Au revoir."
    ;;
esac
