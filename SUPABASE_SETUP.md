# ✅ Supabase Setup — Simple Spain

## Statut
- **Projet créé** ✅ : `simple-spain-immo` 
- **ID** : `wiumullfvbcdogironrl`
- **Région** : Dublin (eu-west-1)
- **Schema** : Exécuté ✅ (listings, client_profiles, client_matches, translations, dedup_events)
- **Clés API** : Partiellement configurées

## Configuration finale — 2 étapes

### 1️⃣ Récupérer SUPABASE_SERVICE_KEY

Aller sur le dashboard :
1. **https://supabase.com/dashboard** 
2. Sélectionne le projet **"simple-spain-immo"**
3. Va à **Settings → API**
4. Sous "Project API keys", **copie le "service_role secret"** (la clé longue commençant par `eyJ...`)

### 2️⃣ Entrer la clé dans .env

Exécute ce script :
```bash
cd /Users/monix/immo_intel
/Users/monix/miniforge3/bin/python3 setup_supabase.py
```

Le script va :
- Te demander de coller la clé
- Sauvegarder dans `.env`
- Tester la connexion

## Clés configurées

```
SUPABASE_URL = https://wiumullfvbcdogironrl.supabase.co ✅
SUPABASE_ANON_KEY = eyJhbGc... ✅ 
SUPABASE_SERVICE_KEY = À FAIRE (2 étapes ci-dessus)
```

## Vérifier la connexion

Une fois la clé service_role entrée :
```bash
cd /Users/monix/immo_intel
/Users/monix/miniforge3/bin/python3 -c "
from modules.supabase_client import get_client, _use_supabase
if _use_supabase():
    client = get_client()
    resp = client.table('listings').select('id').limit(1).execute()
    print('✅ Supabase OK - tables créées')
else:
    print('⚠️  Mode JSON local')
"
```

## Lancer l'app avec Supabase

```bash
./start.sh   # Choix 1 → Streamlit UI
# Page Admin affichera les stats Supabase
```

---

**Notes** :
- La plateforme fonctionne sans Supabase (mode JSON local)
- Avec Supabase + JSON : double-write pour redondance
- La clé service_role est sensible → **ne jamais commit en git**
