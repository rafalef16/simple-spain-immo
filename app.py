"""
Simple Spain — Real Estate Intelligence Platform
Streamlit UI: search, filter, client profiles, admin.
"""
import streamlit as st
import pandas as pd
import hashlib
import re
from pathlib import Path
from datetime import datetime

from modules.db import load_master, scrape_stats
from modules.cleanup import parse_surface, parse_price

st.set_page_config(
    page_title="Simple Spain | Immobilier Catalan",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.listing-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.price-badge { background: #2e7d32; color: white; padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: 1.1em; }
.site-badge { background: #1565c0; color: white; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; }
.new-badge { background: #e65100; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_data():
    return load_master()


def _price_val(listing: dict) -> int:
    return listing.get("prix_eur") or 0


def _terrain_val(listing: dict) -> int:
    return listing.get("terrain_m2") or 0


def _jitter_coord(url: str, coord: float, spread: float = 0.005) -> float:
    h = int(hashlib.md5(url.encode()).hexdigest()[:8], 16)
    return coord + (h % 1000 - 500) / 1000 * spread


def display_card(listing: dict):
    col_img, col_info = st.columns([1, 2])

    with col_img:
        if listing.get("cover_image_url"):
            st.image(listing["cover_image_url"], use_column_width=True)
        else:
            st.markdown("📷 *Pas d'image*")

    with col_info:
        st.markdown(
            f"<span class='site-badge'>{listing.get('site','?').upper()}</span> "
            f"&nbsp; <span class='price-badge'>{listing.get('prix_display') or '—'}</span>",
            unsafe_allow_html=True
        )
        st.subheader(listing.get("title") or listing.get("url", "")[:60])

        col1, col2, col3 = st.columns(3)
        col1.metric("📍 Ville", listing.get("ville_canonical") or listing.get("ville") or "—")
        col2.metric("🏞️ Terrain", f"{listing.get('terrain_m2'):,} m²" if listing.get("terrain_m2") else "—")
        col3.metric("🏠 Bâti", f"{listing.get('construction_m2'):,} m²" if listing.get("construction_m2") else "—")

        desc = listing.get("description_clean") or ""
        if desc:
            with st.expander("📝 Description", expanded=False):
                st.write(desc[:2000])

        st.caption(
            f"🔗 [Voir l'annonce]({listing.get('url', '#')}) &nbsp;|&nbsp; "
            f"Réf: {listing.get('ref') or '—'} &nbsp;|&nbsp; "
            f"Scrapé: {(listing.get('scrap_timestamp') or '')[:10]}"
        )


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://flagcdn.com/es.svg", width=40)
    st.title("Simple Spain")
    st.caption("Intelligence Immobilière Catalane")
    st.divider()

    page = st.radio("Navigation", ["🔍 Recherche", "📊 Stats", "ℹ️ À propos"], label_visibility="collapsed")

    st.divider()
    st.subheader("Filtres")

    budget_min = st.number_input("Budget min (€)", value=0, step=10000)
    budget_max = st.number_input("Budget max (€)", value=2000000, step=10000)
    terrain_min = st.number_input("Terrain min (m²)", value=0, step=500)

    all_data = load_data()
    villes = sorted({l.get("ville_canonical") or l.get("ville") or "" for l in all_data if l.get("ville_canonical") or l.get("ville")})
    villes_sel = st.multiselect("Villes", villes)

    sites_available = sorted({l.get("site_family") or l.get("site") or "" for l in all_data if l.get("site")})
    sites_sel = st.multiselect("Sources", sites_available)

    search_query = st.text_input("🔍 Recherche texte libre", placeholder="finca piscine vue mer...")

    st.divider()
    sort_by = st.selectbox("Trier par", ["Prix ↑", "Prix ↓", "Terrain ↓", "Récent ↓"])

    limit = st.slider("Max résultats", 10, 200, 50)


# ── MAIN CONTENT ──────────────────────────────────────────────────────────────
if "Recherche" in page:
    st.header("🔍 Annonces Immobilières")

    # Filter data
    data = all_data
    if budget_min > 0:
        data = [l for l in data if _price_val(l) >= budget_min]
    if budget_max < 2000000:
        data = [l for l in data if 0 < _price_val(l) <= budget_max]
    if terrain_min > 0:
        data = [l for l in data if _terrain_val(l) >= terrain_min]
    if villes_sel:
        data = [l for l in data if (l.get("ville_canonical") or l.get("ville") or "") in villes_sel]
    if sites_sel:
        data = [l for l in data if (l.get("site_family") or l.get("site") or "") in sites_sel]
    if search_query:
        q = search_query.lower()
        data = [
            l for l in data
            if q in (l.get("description_clean") or "").lower()
            or q in (l.get("title") or "").lower()
            or q in (l.get("ville_canonical") or "").lower()
        ]

    # Sort
    if sort_by == "Prix ↑":
        data = sorted(data, key=lambda x: _price_val(x) or 9999999)
    elif sort_by == "Prix ↓":
        data = sorted(data, key=lambda x: _price_val(x), reverse=True)
    elif sort_by == "Terrain ↓":
        data = sorted(data, key=lambda x: _terrain_val(x), reverse=True)
    elif sort_by == "Récent ↓":
        data = sorted(data, key=lambda x: x.get("scrap_timestamp") or "", reverse=True)

    total = len(data)
    displayed = data[:limit]

    st.info(f"**{total} annonces** correspondent à vos critères — affichage des {len(displayed)} premières")

    if not displayed:
        st.warning("Aucune annonce ne correspond. Élargissez vos filtres.")
    else:
        for listing in displayed:
            with st.container():
                display_card(listing)
                st.divider()

elif "Stats" in page:
    st.header("📊 Statistiques")
    stats = scrape_stats()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total annonces", stats["total"])
    col2.metric("Sources actives", len(stats["by_site"]))
    col3.metric("Dernier scrape", (stats.get("last_run") or "—")[:10])

    if stats["by_site"]:
        df = pd.DataFrame([
            {"Source": k, "Annonces": v}
            for k, v in sorted(stats["by_site"].items(), key=lambda x: x[1], reverse=True)
        ])
        st.bar_chart(df.set_index("Source"))
        st.dataframe(df, use_container_width=True)

    st.subheader("Actions")
    if st.button("🔄 Recharger les données"):
        st.cache_data.clear()
        st.rerun()

elif "propos" in page:
    st.header("ℹ️ Simple Spain")
    st.markdown("""
**Plateforme d'intelligence immobilière** pour les propriétés catalanes rurales.

**Sources couvertes:**
- ThinkSpain (fincas + terrains, rayon 75km Tortosa)
- Kyero (Tarragona maisons de campagne)
- Fotocasa (casas rústicas + terrenos)
- Idealista (chalets avec licence touristique + casas pueblo + fincas/terrenos)
- 38 agences locales Mobilia (Terres de l'Ebre, Delta de l'Ebre, Priorat...)

**Pipeline:**
```
Scrape → Dédup SHA256 → Nettoyage HTML → Filtre solaire → Merge Master
```

**Commandes:**
```bash
make scrape          # Tout scraper
make scrape-mobilia  # Mobilia uniquement (38 sites)
make merge           # Fusionner les fichiers JSON
make app             # Lancer l'interface
```
    """)
