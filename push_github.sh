#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  Créer le repo GitHub et pousser le code
#  Lancez ce script UNE SEULE FOIS depuis un terminal
# ─────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"

echo "══════════════════════════════════════════"
echo "  Simple Spain → GitHub"
echo "══════════════════════════════════════════"

# Vérifier auth GitHub
if ! gh auth status &>/dev/null; then
  echo "🔐 Connexion GitHub requise..."
  gh auth login
fi

# Créer le repo public
echo "📦 Création du repo simple-spain-immo..."
gh repo create simple-spain-immo \
  --public \
  --description "Plateforme d'intelligence immobilière catalane — scraping Fotocasa, Idealista, ThinkSpain, Kyero + 36 agences locales" \
  --source . \
  --remote origin \
  --push

echo ""
echo "✅ Repo créé et code poussé !"
echo "🔗 https://github.com/$(gh api user -q .login)/simple-spain-immo"
