"""
Simple Spain — Real Estate Intelligence Platform
Streamlit UI : Carte · Recherche · Stats · À propos
"""
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from modules.db import load_master, scrape_stats
from modules.geocoder import resolve_coords

# ── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Simple Spain | Immobilier Catalan",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🏡",
)

st.markdown("""
<style>
/* Cards */
.ss-card { border:1px solid #ddd; border-radius:10px; padding:16px; margin-bottom:14px; background:#fff; }
/* Badges */
.badge { display:inline-block; padding:2px 9px; border-radius:12px; font-size:0.75em; font-weight:600; margin-right:4px; }
.badge-green  { background:#e8f5e9; color:#2e7d32; }
.badge-blue   { background:#e3f2fd; color:#1565c0; }
.badge-orange { background:#fff3e0; color:#e65100; }
.badge-grey   { background:#f5f5f5; color:#555; }
.badge-red    { background:#fce4ec; color:#c62828; }
.badge-new    { background:#e0f7fa; color:#006064; }
/* Price */
.price-big { font-size:1.4em; font-weight:700; color:#2e7d32; }
/* Metrics row */
.metric-label { font-size:0.72em; color:#888; text-transform:uppercase; letter-spacing:.04em; }
.metric-val   { font-size:1.05em; font-weight:600; color:#222; }
</style>
""", unsafe_allow_html=True)


# ── DATA ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load():
    return load_master()


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _price_m2(l: dict) -> float | None:
    p = l.get("prix_eur") or 0
    t = l.get("terrain_m2") or 0
    if p > 0 and t > 0:
        return round(p / t, 1)
    return None


def _days_ago(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def _badge_html(text: str, cls: str) -> str:
    return f'<span class="badge badge-{cls}">{text}</span>'


def _fmt_price(p) -> str:
    if not p:
        return "—"
    return f"{int(p):,} €".replace(",", " ")


def _fmt_m2(v) -> str:
    if not v:
        return "—"
    return f"{int(v):,} m²".replace(",", " ")


def _detect_type(l: dict) -> str:
    t = (l.get("type") or "").lower()
    title = (l.get("title") or "").lower()
    combined = t + " " + title
    if any(w in combined for w in ["finca", "rustic", "terreno", "terrain", "solar", "rural"]):
        return "finca"
    if any(w in combined for w in ["chalet", "villa", "casa", "maison", "masia"]):
        return "casa"
    if any(w in combined for w in ["tourist", "touristic", "airbnb", "booking", "vacacional"]):
        return "touristic"
    return "autre"


def _is_tourist(l: dict) -> bool:
    keywords = ["licencia", "turístic", "turistic", "airbnb", "booking",
                "alquiler turistico", "vacacional"]
    text = ((l.get("title") or "") + " " + (l.get("description_clean") or "")).lower()
    return any(k in text for k in keywords)


def _marker_color(prop_type: str) -> str:
    return {"finca": "green", "casa": "blue", "touristic": "orange"}.get(prop_type, "gray")


def _icon_color(prop_type: str) -> str:
    return {"finca": "#2e7d32", "casa": "#1565c0", "touristic": "#e65100"}.get(prop_type, "#757575")


# ── SIDEBAR FILTERS ───────────────────────────────────────────────────────────
def _sidebar_filters(all_data: list[dict]) -> list[dict]:
    with st.sidebar:
        st.image("https://flagcdn.com/es.svg", width=36)
        st.title("Simple Spain")
        st.caption("Intelligence Immobilière Catalane")
        st.divider()

        page = st.radio(
            "Page",
            ["🗺️ Carte", "🔍 Recherche", "📊 Stats", "ℹ️ À propos"],
            label_visibility="collapsed",
        )
        st.divider()
        st.subheader("Filtres")

        # Budget
        col1, col2 = st.columns(2)
        bmin = col1.number_input("Budget min €", value=0, step=10_000, format="%d")
        bmax = col2.number_input("Budget max €", value=2_000_000, step=10_000, format="%d")

        # Surfaces
        tmin = st.number_input("Terrain min m²", value=0, step=500, format="%d")
        cmin = st.number_input("Construction min m²", value=0, step=10, format="%d")
        pm2_max = st.number_input("Prix/m² max €/m²", value=0, step=1, format="%d",
                                   help="0 = pas de limite")

        # Villes
        villes_raw = sorted({
            l.get("ville_canonical") or l.get("ville") or ""
            for l in all_data
            if l.get("ville_canonical") or l.get("ville")
        })
        villes_raw = [v for v in villes_raw if v]
        villes_sel = st.multiselect("Villes", villes_raw)

        # Sources
        sources = sorted({l.get("site_family") or l.get("site") or "" for l in all_data if l.get("site")})
        sources_sel = st.multiselect("Sources", sources)

        # Type
        type_sel = st.multiselect("Type", ["finca", "casa", "touristic", "autre"])

        # Toggles
        only_tourist = st.checkbox("Licence touristique uniquement")
        only_image   = st.checkbox("Exclure sans image")
        only_surface = st.checkbox("Exclure sans surface terrain")

        # Texte libre
        q = st.text_input("🔍 Texte libre", placeholder="finca piscine vue mer...")

        st.divider()
        sort_by = st.selectbox("Trier par", ["Prix ↑", "Prix ↓", "Terrain ↓", "Récent ↓", "Prix/m² ↑"])

        limit = st.slider("Résultats max", 20, 500, 100)

    # Apply filters
    data = all_data

    if bmin > 0:
        data = [l for l in data if (l.get("prix_eur") or 0) >= bmin]
    if bmax < 2_000_000:
        data = [l for l in data if 0 < (l.get("prix_eur") or 0) <= bmax]
    if tmin > 0:
        data = [l for l in data if (l.get("terrain_m2") or 0) >= tmin]
    if cmin > 0:
        data = [l for l in data if (l.get("construction_m2") or 0) >= cmin]
    if pm2_max > 0:
        data = [l for l in data if (_price_m2(l) or 999_999) <= pm2_max]
    if villes_sel:
        data = [l for l in data
                if (l.get("ville_canonical") or l.get("ville") or "") in villes_sel]
    if sources_sel:
        data = [l for l in data
                if (l.get("site_family") or l.get("site") or "") in sources_sel]
    if type_sel:
        data = [l for l in data if _detect_type(l) in type_sel]
    if only_tourist:
        data = [l for l in data if _is_tourist(l)]
    if only_image:
        data = [l for l in data if l.get("cover_image_url")]
    if only_surface:
        data = [l for l in data if (l.get("terrain_m2") or 0) > 0]
    if q:
        ql = q.lower()
        data = [
            l for l in data
            if ql in (l.get("title") or "").lower()
            or ql in (l.get("description_clean") or "").lower()
            or ql in (l.get("ville_canonical") or l.get("ville") or "").lower()
        ]

    # Sort
    def _sv(l):
        return l.get("prix_eur") or 0

    def _st(l):
        return l.get("terrain_m2") or 0

    if sort_by == "Prix ↑":
        data = sorted(data, key=lambda l: _sv(l) or 9_999_999)
    elif sort_by == "Prix ↓":
        data = sorted(data, key=_sv, reverse=True)
    elif sort_by == "Terrain ↓":
        data = sorted(data, key=_st, reverse=True)
    elif sort_by == "Récent ↓":
        data = sorted(data, key=lambda l: l.get("scrap_timestamp") or "", reverse=True)
    elif sort_by == "Prix/m² ↑":
        data = sorted(data, key=lambda l: _price_m2(l) or 999_999)

    return data[:limit], page


# ── PAGE CARTE ────────────────────────────────────────────────────────────────
def page_carte(data: list[dict]):
    st.header("🗺️ Carte des propriétés")

    # Résoudre coordonnées
    geo_listings = []
    for l in data:
        city = l.get("ville_canonical") or l.get("ville") or ""
        coords = resolve_coords(city)
        if coords:
            geo_listings.append((l, coords))

    st.caption(
        f"**{len(geo_listings)}** biens géolocalisés sur **{len(data)}** filtrés "
        f"({'%.0f' % (100 * len(geo_listings) / max(len(data), 1))}%)"
    )

    # Build Folium map
    m = folium.Map(
        location=[40.85, 0.55],
        zoom_start=10,
        tiles="CartoDB Positron",
        prefer_canvas=True,
    )
    cluster = MarkerCluster(
        options={"maxClusterRadius": 50, "disableClusteringAtZoom": 14}
    ).add_to(m)

    for l, (lat, lon) in geo_listings:
        ptype = _detect_type(l)
        color = _marker_color(ptype)
        price_str = _fmt_price(l.get("prix_eur"))
        terrain_str = _fmt_m2(l.get("terrain_m2"))
        const_str = _fmt_m2(l.get("construction_m2"))
        city = l.get("ville_canonical") or l.get("ville") or "—"
        title = (l.get("title") or "Annonce")[:80]
        site = (l.get("site") or "—").upper()
        url = l.get("url") or "#"
        pm2 = _price_m2(l)
        pm2_str = f"{pm2} €/m²" if pm2 else "—"

        popup_html = f"""
        <div style="min-width:220px;font-family:sans-serif;font-size:13px">
          <b style="font-size:14px">{title}</b><br>
          <span style="color:#2e7d32;font-size:1.2em;font-weight:700">{price_str}</span>
          <span style="color:#888;font-size:11px;margin-left:8px">{pm2_str}</span>
          <hr style="margin:6px 0">
          🏞️ Terrain : {terrain_str}<br>
          🏠 Bâti : {const_str}<br>
          📍 {city}<br>
          🏷️ {site}<br>
          <a href="{url}" target="_blank"
             style="display:inline-block;margin-top:8px;padding:4px 10px;
                    background:#1565c0;color:#fff;border-radius:4px;
                    text-decoration:none;font-size:12px">
            Voir l'annonce →
          </a>
        </div>
        """
        tooltip = f"{price_str} — {city}"

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=tooltip,
            icon=folium.Icon(color=color, icon="home", prefix="fa"),
        ).add_to(cluster)

    st_folium(m, width="100%", height=580, returned_objects=[])

    st.divider()

    # GRILLE SOUS LA CARTE
    st.subheader(f"📋 Grille détaillée — {len(data)} annonces")
    _grille(data)


# ── GRILLE DE DÉTAIL ──────────────────────────────────────────────────────────
def _grille(data: list[dict]):
    if not data:
        st.info("Aucune annonce ne correspond aux filtres.")
        return

    cols = st.columns(2)
    for idx, l in enumerate(data):
        with cols[idx % 2]:
            _card(l)


def _card(l: dict):
    ptype     = _detect_type(l)
    is_tour   = _is_tourist(l)
    days      = _days_ago(l.get("scrap_timestamp"))
    price_m2  = _price_m2(l)
    city      = l.get("ville_canonical") or l.get("ville") or "—"
    coords    = resolve_coords(city)
    site      = (l.get("site") or "—")
    family    = (l.get("site_family") or "—")
    ref       = (l.get("ref") or "—")
    uid       = (l.get("id") or "")[:8] or "—"
    desc      = l.get("description_clean") or ""
    url       = l.get("url") or "#"
    title     = l.get("title") or "Sans titre"
    ts        = (l.get("scrap_timestamp") or "")[:10]
    has_solar = "solar" in desc.lower()

    # Badge row
    type_cls = {"finca": "green", "casa": "blue", "touristic": "orange"}.get(ptype, "grey")
    badges = _badge_html(ptype.upper(), type_cls)
    badges += _badge_html(site.upper(), "blue")
    if is_tour:
        badges += _badge_html("🏖️ TOURIST", "orange")
    if has_solar:
        badges += _badge_html("🌞 SOLAR", "red")
    if days is not None and days < 2:
        badges += _badge_html("🆕 NOUVEAU", "new")

    with st.container(border=True):
        st.markdown(badges, unsafe_allow_html=True)
        st.markdown(f"### {title}")

        # Prix + meta
        col_p, col_r, col_d = st.columns([2, 1, 1])
        col_p.markdown(
            f'<span class="price-big">{_fmt_price(l.get("prix_eur"))}</span>',
            unsafe_allow_html=True
        )
        col_r.markdown(
            f'<div class="metric-label">Réf</div>'
            f'<div class="metric-val">{ref}</div>',
            unsafe_allow_html=True
        )
        col_d.markdown(
            f'<div class="metric-label">Scrapé</div>'
            f'<div class="metric-val">{ts}</div>',
            unsafe_allow_html=True
        )

        st.divider()

        # Métriques 3 colonnes
        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown('<div class="metric-label">Terrain</div>'
                        f'<div class="metric-val">{_fmt_m2(l.get("terrain_m2"))}</div>',
                        unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Bâti</div>'
                        f'<div class="metric-val">{_fmt_m2(l.get("construction_m2"))}</div>',
                        unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Prix/m² terrain</div>'
                        f'<div class="metric-val">{f"{price_m2} €/m²" if price_m2 else "—"}</div>',
                        unsafe_allow_html=True)

        with c2:
            st.markdown(f'<div class="metric-label">Ville</div>'
                        f'<div class="metric-val">{city}</div>',
                        unsafe_allow_html=True)
            coord_str = f"{coords[0]:.4f}, {coords[1]:.4f}" if coords else "—"
            st.markdown(f'<div class="metric-label">GPS</div>'
                        f'<div class="metric-val" style="font-size:0.85em">{coord_str}</div>',
                        unsafe_allow_html=True)

        with c3:
            st.markdown(f'<div class="metric-label">Source</div>'
                        f'<div class="metric-val">{site}</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="metric-label">Famille CMS</div>'
                        f'<div class="metric-val">{family}</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="metric-label">ID</div>'
                        f'<div class="metric-val" style="font-family:monospace">{uid}</div>',
                        unsafe_allow_html=True)

        # Image
        if l.get("cover_image_url"):
            try:
                st.image(l["cover_image_url"], use_column_width=True)
            except Exception:
                st.caption("📷 Image indisponible")
        else:
            st.caption("📷 Pas d'image")

        # Description
        if desc:
            short = desc[:2000]
            with st.expander("📝 Description"):
                st.write(short)
                if len(desc) > 2000:
                    if st.button("Lire tout", key=f"full_{uid}_{hash(url)}"):
                        st.write(desc)

        # Lien
        st.markdown(
            f'<a href="{url}" target="_blank" '
            f'style="display:inline-block;padding:6px 16px;background:#1565c0;'
            f'color:white;border-radius:6px;text-decoration:none;font-size:13px">'
            f'🔗 Voir l\'annonce</a>',
            unsafe_allow_html=True,
        )
        st.markdown("")  # spacing


# ── PAGE RECHERCHE ────────────────────────────────────────────────────────────
def page_recherche(data: list[dict]):
    st.header("🔍 Recherche")
    st.info(f"**{len(data)} annonces** correspondent aux filtres sidebar.")
    _grille(data)


# ── PAGE STATS ────────────────────────────────────────────────────────────────
def page_stats(all_data: list[dict]):
    st.header("📊 Statistiques")

    total   = len(all_data)
    with_img  = sum(1 for l in all_data if l.get("cover_image_url"))
    with_px   = sum(1 for l in all_data if l.get("prix_eur"))
    with_ter  = sum(1 for l in all_data if l.get("terrain_m2"))
    with_tour = sum(1 for l in all_data if _is_tourist(l))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total annonces", total)
    c2.metric("Avec image", f"{with_img} ({100*with_img//max(total,1)}%)")
    c3.metric("Avec prix",  f"{with_px}  ({100*with_px//max(total,1)}%)")
    c4.metric("Avec terrain",f"{with_ter} ({100*with_ter//max(total,1)}%)")
    c5.metric("Touristiques",f"{with_tour}")

    st.divider()

    # Par source
    st.subheader("Annonces par source")
    src_counts: dict[str, int] = {}
    for l in all_data:
        s = l.get("site_family") or l.get("site") or "inconnu"
        src_counts[s] = src_counts.get(s, 0) + 1
    df_src = pd.DataFrame(
        sorted(src_counts.items(), key=lambda x: x[1], reverse=True),
        columns=["Source", "Annonces"]
    )
    st.bar_chart(df_src.set_index("Source"))
    st.dataframe(df_src, use_container_width=True, hide_index=True)

    st.divider()

    # Histogramme prix
    st.subheader("Distribution des prix")
    prices = [l["prix_eur"] for l in all_data if l.get("prix_eur")]
    if prices:
        df_px = pd.DataFrame(prices, columns=["Prix €"])
        bins  = [0, 50_000, 100_000, 150_000, 200_000, 300_000,
                 500_000, 750_000, 1_000_000, 2_000_000]
        labels = ["<50k","50-100k","100-150k","150-200k","200-300k",
                  "300-500k","500-750k","750k-1M",">1M"]
        df_px["Tranche"] = pd.cut(df_px["Prix €"], bins=bins, labels=labels, right=False)
        hist = df_px["Tranche"].value_counts().reindex(labels).fillna(0)
        st.bar_chart(hist)

    st.divider()

    # Top villes
    st.subheader("Top villes")
    city_data: dict[str, dict] = {}
    for l in all_data:
        city = l.get("ville_canonical") or l.get("ville") or "—"
        if city == "—":
            continue
        if city not in city_data:
            city_data[city] = {"count": 0, "prices": []}
        city_data[city]["count"] += 1
        if l.get("prix_eur"):
            city_data[city]["prices"].append(l["prix_eur"])

    rows = []
    for city, d in city_data.items():
        median = sorted(d["prices"])[len(d["prices"]) // 2] if d["prices"] else None
        rows.append({
            "Ville": city,
            "Annonces": d["count"],
            "Prix médian": f"{median:,} €".replace(",", " ") if median else "—",
        })
    df_cities = pd.DataFrame(rows).sort_values("Annonces", ascending=False).head(20)
    st.dataframe(df_cities, use_container_width=True, hide_index=True)

    st.divider()
    if st.button("🔄 Recharger les données"):
        st.cache_data.clear()
        st.rerun()


# ── PAGE À PROPOS ─────────────────────────────────────────────────────────────
def page_about():
    st.header("ℹ️ Simple Spain")
    st.markdown("""
**Plateforme d'intelligence immobilière** pour les propriétés rurales catalanes.

### Sources
| Source | Type | Proxy |
|--------|------|-------|
| Fotocasa — Casas rústicas + Terrenos | Géozone Terres de l'Ebre | EVOMI |
| Idealista — Chalets (**licence touristique**) | Géozone shape | EVOMI |
| Idealista — Casas pueblo + Fincas/Terrains | Géozone shape | EVOMI |
| ThinkSpain — Fincas + Undeveloped lands | Rayon 75km Tortosa | Non |
| Kyero — Maisons de campagne Tarragona | Province | Non |
| **36 agences locales** (7 familles CMS + 14 JS) | Terres de l'Ebre | Non |

### Pipeline
```
Scrape → Dédup SHA256 → Nettoyage HTML → Filtre solaire → Merge Master → Carte/Grille
```

### Commandes
```bash
make scrape           # Tout scraper
make scrape-no-proxy  # Sans proxy (Mobilia + ThinkSpain + Kyero)
make scrape-fotocasa  # Fotocasa (EVOMI requis)
make scrape-idealista # Idealista (EVOMI requis)
make app              # Lancer l'UI
```

### Filtres automatiques
- 🌞 **Solar** : annonces contenant "placas solares", "paneles solares" → exclues du scraper
- 🏖️ **Licence touristique** : Idealista uniquement → gardées si "licencia", "airbnb", "booking"...
- ♻️ **Déduplication** : SHA256(url + 25 premiers mots description)
    """)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_data = _load()
    filtered, page = _sidebar_filters(all_data)

    if "Carte" in page:
        page_carte(filtered)
    elif "Recherche" in page:
        page_recherche(filtered)
    elif "Stats" in page:
        page_stats(all_data)
    else:
        page_about()


if __name__ == "__main__":
    main()
