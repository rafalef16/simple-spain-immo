# Simple Spain — Intelligence Immobilière Catalane

Plateforme de scraping + interface de recherche pour les propriétés rurales catalanes (Terres de l'Ebre, Delta de l'Ebre, Priorat, Montsià).

---

## Où est créé le système ?

```
/Users/monix/immo_intel/
├── config.py          # Toutes les URLs et paramètres
├── pipeline.py        # Orchestrateur CLI
├── app.py             # Interface Streamlit
├── start.sh           # Script de démarrage (menu interactif)
├── SimpleSpain.command # Raccourci double-clic pour Bureau Mac
├── Makefile           # Raccourcis make
├── cron.sh            # Cron journalier automatique
├── scrapers/
│   ├── mobilia.py     # 7 familles CMS locales (22 sites)
│   ├── regional.py    # 14 agences JS-rendered (Playwright)
│   ├── thinkspain.py  # ThinkSpain (radius 75km Tortosa)
│   ├── kyero.py       # Kyero Tarragona
│   ├── fotocasa.py    # Fotocasa (Playwright + EVOMI)
│   └── idealista.py   # Idealista (Playwright + EVOMI + filtre licence)
├── modules/
│   ├── db.py          # Stockage JSON, déduplication, merge master
│   ├── cleanup.py     # Nettoyage HTML, prix, surfaces, filtre solaire
│   └── cities.py      # Normalisation 80+ noms de villes catalanes
└── data/              # Données scrapées (gitignore)
```

---

## Sources couvertes (8 flux officiels)

| Source | Type | Proxy |
|--------|------|-------|
| Fotocasa — Casas rústicas | `searchArea` géozone | EVOMI |
| Fotocasa — Terrenos | `searchArea` géozone | EVOMI |
| Idealista — Chalets + licences touristiques | filtre actif | EVOMI |
| Idealista — Casas pueblo | géozone shape | EVOMI |
| Idealista — Fincas + terrains ≥5000m² | géozone shape | EVOMI |
| ThinkSpain — Fincas country houses | radius 75km Tortosa | Non |
| ThinkSpain — Undeveloped lands | radius 75km Tortosa | Non |
| Kyero — Maisons de campagne Tarragona | province | Non |

Plus **36 agences locales** (Mobilia 7 familles CMS + 14 JS-rendered).

---

## Installation

```bash
cd /Users/monix/immo_intel

# 1. Copier et remplir les clés proxy
cp .env.example .env
# Éditez .env avec vos clés EVOMI

# 2. Installer les dépendances
make install
```

---

## Lancer l'interface Streamlit

### Option A — Script interactif (recommandé)
```bash
./start.sh
# → Choisir 1 pour l'UI
```

### Option B — Raccourci Bureau Mac
```bash
cp SimpleSpain.command ~/Desktop/
chmod +x ~/Desktop/SimpleSpain.command
# Double-clic sur le fichier
```

### Option C — Commande directe
```bash
make app
# ou
streamlit run app.py --server.port 8501
```

L'interface s'ouvre sur **http://localhost:8501**

---

## Lancer le scraper

```bash
# Tout scraper (toutes sources)
make scrape

# Sans proxy (Mobilia + ThinkSpain + Kyero + Regional)
make scrape-no-proxy

# Avec proxy EVOMI uniquement (Fotocasa + Idealista)
make scrape-fotocasa
make scrape-idealista

# Test sans écriture disque
make dry-run

# Compter les annonces par source
make data-count
```

---

## Configurer EVOMI

Votre clé EVOMI est au format :
```
http://core-residential.evomi.com:1000:USER:PASS
```

Dans `.env` :
```env
EVOMI_USER=samueldomi6
EVOMI_PASS=DSfzAOkqIjfgPqQhcD5h_country-ES
```

Le suffixe `_country-ES` force le ciblage Espagne.

---

## Filtres automatiques

| Filtre | Comportement |
|--------|-------------|
| Panneaux solaires | Annonces avec "placas solares", "paneles solares"... → **supprimées** |
| Licence touristique | Idealista chalets → **garder uniquement** celles avec "licencia", "turístico", "airbnb", "booking", "alquiler turistico", "vacacional" |
| Déduplication SHA256 | `sha256(url + description[:25 mots])` → pas de doublon |

---

## Déploiement cloud

### Fly.io (recommandé — gratuit)
```bash
# Installer flyctl
curl -L https://fly.io/install.sh | sh

# Déployer
fly launch --name simple-spain --region mad
fly secrets set EVOMI_USER=samueldomi6 EVOMI_PASS=DSfzAOkqIjfgPqQhcD5h_country-ES
fly deploy
```

### Render.com
1. Connecter le repo GitHub
2. Build command : `pip install -r requirements.txt`
3. Start command : `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
4. Variables d'environnement : `EVOMI_USER`, `EVOMI_PASS`

### Docker
```bash
docker build -t simple-spain .
docker run -p 8501:8501 \
  -e EVOMI_USER=samueldomi6 \
  -e EVOMI_PASS=DSfzAOkqIjfgPqQhcD5h_country-ES \
  simple-spain
```

---

## Cron automatique (scrape journalier)

```bash
# Ajouter au crontab
crontab -e
# Ajouter cette ligne (scrape tous les jours à 7h)
0 7 * * * /Users/monix/immo_intel/cron.sh >> /Users/monix/immo_intel/logs/cron.log 2>&1
```

---

## Pipeline de données

```
URLs config.py
    ↓
Scrapers (requests / Playwright + EVOMI)
    ↓
Nettoyage HTML (modules/cleanup.py)
    ↓
Filtres (solaire ✗, licence touristique ✓)
    ↓
Déduplication SHA256
    ↓
data/{site}.json
    ↓
merge → data/master.json
    ↓
Streamlit UI (app.py)
```
