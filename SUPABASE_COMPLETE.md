# 🚀 Supabase Integration — COMPLETE

## ✅ Quoi a été fait

### 1. Projet Supabase créé
- **Nom** : simple-spain-immo
- **ID** : `wiumullfvbcdogironrl`
- **URL** : https://wiumullfvbcdogironrl.supabase.co
- **Région** : Dublin (eu-west-1)
- **Plan** : Gratuit

### 2. Schema SQL exécuté ✅
Toutes les tables créées :
- ✅ `listings` — propriétés (id, url, prix, surfaces, description, images, timestamp, FTS index)
- ✅ `client_profiles` — profils clients (budget, villes, types, mots-clés)
- ✅ `client_matches` — appariements client-listing
- ✅ `translations` — traductions + localisation anonyme
- ✅ `dedup_events` — audit déduplication

### 3. Code Python v3.0 — 10 BLOCS ✅
- ✅ BLOC 1 : `modules/supabase_client.py` (lazy singleton, JSON fallback)
- ✅ BLOC 2 : Unicode cleanup (`clean_text()`)
- ✅ BLOC 3 : Filtre touristique renommé
- ✅ BLOC 4 : LLM translations (`modules/llm_client.py`)
- ✅ BLOC 5 : Full-text search + Supabase FTS
- ✅ BLOC 6 : Client matching system (`modules/client_matching.py`)
- ✅ BLOC 7 : Proxy + cache (`pre_filter_urls`, `fetch_html_cached`)
- ✅ BLOC 8 : Card UI — 15 variables, galerie photos, traductions
- ✅ BLOC 9 : Admin page + JSONL logs
- ✅ BLOC 10 : `.env.example` complété

### 4. Clés API configurées
```
SUPABASE_URL = https://wiumullfvbcdogironrl.supabase.co ✅
SUPABASE_ANON_KEY = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... ✅
```

---

## ⚠️ TODO — Une seule étape manuelle

### Récupérer et configurer SUPABASE_SERVICE_KEY

**Option 1 : Script interactif (recommandé)**
```bash
cd /Users/monix/immo_intel
python3 setup_supabase.py
```

Le script va :
1. T'ouvrir le dashboard Supabase automatiquement
2. Te demander de coller la clé
3. Sauvegarder dans `.env`
4. Tester la connexion

**Option 2 : Manuel**
1. Ouvre https://supabase.com/dashboard/project/wiumullfvbcdogironrl/settings/api
2. Sous "Project API keys", copie le **"service_role secret"** (la clé longue commençant par `eyJ...`)
3. Édite `/Users/monix/immo_intel/.env` et remplace `RETRIEVER_DU_DASHBOARD_SUPABASE` par ta clé

---

## ✨ Après l'étape TODO

### Démarrer l'app avec Supabase

```bash
cd /Users/monix/immo_intel
./start.sh
# Choix 1 → Streamlit UI
```

La plateforme va :
- ✅ Lire les annonces depuis Supabase (si connecté)
- ✅ Double-write JSON local (fallback)
- ✅ Full-text search via GIN index (Recherche page)
- ✅ Client matching (page Clients)
- ✅ Traductions Claude (boutons FR/EN/DE)
- ✅ Admin dashboard avec stats Supabase

### Tester la connexion manuelle

```bash
cd /Users/monix/immo_intel
python3 -c "
from modules.supabase_client import _use_supabase, get_client
if _use_supabase():
    client = get_client()
    resp = client.table('listings').select('id').limit(1).execute()
    print('✅ Supabase connecté')
else:
    print('⚠️  Mode JSON local (SUPABASE_SERVICE_KEY manquant)')
"
```

---

## 📊 Statut final

| Composant | Statut |
|-----------|--------|
| Projet Supabase | ✅ Créé |
| Schema SQL | ✅ Exécuté |
| Code Python v3.0 | ✅ Implémenté (10 blocs) |
| Clés anon/URL | ✅ Configurées |
| Clé service | ⏳ À entrer via script |
| App Streamlit | ✅ Prête |
| Git commit | ✅ v3.0 production-ready |

---

## 🔒 Sécurité

- ❌ `.env` ne doit JAMAIS être commité
- ❌ `SUPABASE_SERVICE_KEY` est une clé sensible → keep-secret
- ✅ JSON local fonctionne sans Supabase (failover)
- ✅ ANTHROPIC_API_KEY optionnelle (traductions désactivées sinon)

---

## 📝 Fichiers créés/modifiés

### Créés
- `modules/supabase_client.py` — Client Supabase
- `modules/llm_client.py` — Claude Haiku API
- `modules/client_parser.py` — Parsing profils
- `modules/client_matching.py` — Matching listings
- `schema.sql` — Schema SQL
- `setup_supabase.py` — Setup interactif
- `SUPABASE_SETUP.md` — Guide d'installation
- `.env` — Variables configurées

### Modifiés
- `app.py` — Pages Clients + Admin + FTS + Traductions
- `modules/db.py` — Supabase + JSON fallback
- `modules/cleanup.py` — Unicode normalization
- `scrapers/base.py` — `pre_filter_urls` + cache HTTP
- `scrapers/idealista.py` — Tourist filter rename
- `scrapers/thinkspain.py` — Apply cache + filter
- `scrapers/kyero.py` — Apply cache + filter
- `pipeline.py` — JSONL structured logs
- `.env.example` — Clés API
- `requirements.txt` — `supabase>=2.4.0`, `anthropic>=0.25.0`

---

## 🎯 Prochaines étapes

1. **Immédiat** : Exécute `python3 setup_supabase.py` (5 min)
2. **Optionnel** : Ajoute `ANTHROPIC_API_KEY` pour traductions Claude
3. **Lancer** : `./start.sh` → Choix 1 pour Streamlit UI

**Fin de la configuration Supabase !**
