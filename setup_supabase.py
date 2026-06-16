#!/usr/bin/env python3
"""
Setup Supabase service key interactively.
Guides user to fetch the service_role secret from Supabase dashboard.
"""
import os
import re
import webbrowser
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DASHBOARD_URL = "https://supabase.com/dashboard/project/wiumullfvbcdogironrl/settings/api"

def setup_service_key():
    env_file = Path(__file__).parent / ".env"

    print("\n" + "="*70)
    print("  🔐 SUPABASE SERVICE KEY SETUP")
    print("="*70)
    print(f"""
✅ Projet créé : simple-spain-immo
   URL: https://wiumullfvbcdogironrl.supabase.co
   Region: Dublin (eu-west-1)

📋 Étapes :

   1. Je vais ouvrir le dashboard Supabase...
   2. Va à Settings → API
   3. Cherche "service_role secret" (clé longue commençant par "eyJ...")
   4. Copie-la
   5. Reviens ici et colle-la

Ouverture du dashboard dans 3 secondes...
""")

    time.sleep(2)
    try:
        webbrowser.open(DASHBOARD_URL)
        print("✅ Navigateur ouvert → Supabase Dashboard")
    except Exception as e:
        print(f"⚠️  Impossible d'ouvrir le navigateur : {e}")
        print(f"   Ouvre manuellement : {DASHBOARD_URL}")

    print("")
    service_key = input("🔑 Colle SUPABASE_SERVICE_KEY ici : ").strip()

    if not service_key:
        print("❌ Aucune clé fournie. Abandon.")
        return False

    if not service_key.startswith("eyJ"):
        print("⚠️  Attention : la clé doit commencer par 'eyJ'. Vous avez copié la bonne clé ?")
        confirm = input("Continuer quand même ? (y/n) : ").lower()
        if confirm != "y":
            return False

    # Update .env
    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()

    if "SUPABASE_SERVICE_KEY=" in content:
        content = re.sub(
            r'SUPABASE_SERVICE_KEY=.*',
            f'SUPABASE_SERVICE_KEY={service_key}',
            content
        )
    else:
        content += f"\nSUPABASE_SERVICE_KEY={service_key}\n"

    with open(env_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n✅ SUPABASE_SERVICE_KEY sauvegardé dans .env")
    print(f"   Clé : {service_key[:30]}...")

    # Test connection
    print("\n🔍 Test de connexion Supabase...")
    try:
        from modules.supabase_client import get_client, _use_supabase
        # Force reload
        import importlib
        import modules.supabase_client
        importlib.reload(modules.supabase_client)
        from modules.supabase_client import get_client, _use_supabase

        if _use_supabase():
            client = get_client()
            if client:
                client.table("listings").select("id").limit(1).execute()
                print("✅ Connexion Supabase OK!")
                print("   Tables : listings, client_profiles, client_matches, translations, dedup_events")
                return True
        else:
            print("⚠️  SUPABASE_URL non défini")
            return False
    except Exception as e:
        print(f"⚠️  Erreur test : {e}")
        print("   La clé est peut-être invalide. Essaie à nouveau.")
        return False


if __name__ == "__main__":
    success = setup_service_key()
    exit(0 if success else 1)
