"""
Simple Spain — Real Estate Intelligence Platform
Streamlit UI : Carte · Recherche · Clients · Admin · À propos
"""
import re
import json
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
@st.cache_data(ttl=60)
def _load():
    from modules.db import merge_all_to_master
    return merge_all_to_master()


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
def _sidebar_filters(all_data: list[dict]) -> tuple[list[dict], str]:
    with st.sidebar:
        st.image("https://flagcdn.com/es.svg", width=36)
        st.title("Simple Spain")
        st.caption("Intelligence Immobilière Catalane")
        st.divider()

        page = st.radio(
            "Page",
            ["🗺️ Carte", "🔍 Recherche", "👥 Clients", "📊 Stats", "🛠️ Admin", "ℹ️ À propos"],
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
    photos    = l.get("photos") or []
    dedup_h   = (l.get("id") or "")  # SHA256 dedup hash (full)

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
    if photos:
        badges += _badge_html(f"📷 {len(photos)}", "grey")

    with st.container(border=True):
        st.markdown(badges, unsafe_allow_html=True)
        st.markdown(f"### {title}")

        # Prix + meta
        col_p, col_r, col_d = st.columns([2, 1, 1])
        col_p.markdown(
            f'<span class="price-big">{_fmt_price(l.get("prix_eur"))}</span>'
            f'<span style="font-size:0.85em;color:#888;margin-left:8px">'
            f'{l.get("prix_display") or ""}</span>',
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

        # Métriques 3 colonnes — 15 variables obligatoires
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
            st.markdown(f'<div class="metric-label">Type</div>'
                        f'<div class="metric-val">{ptype}</div>',
                        unsafe_allow_html=True)

        with c3:
            st.markdown(f'<div class="metric-label">Source</div>'
                        f'<div class="metric-val">{site}</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="metric-label">Famille</div>'
                        f'<div class="metric-val">{family}</div>',
                        unsafe_allow_html=True)
            st.markdown(f'<div class="metric-label">ID (SHA256)</div>'
                        f'<div class="metric-val" style="font-family:monospace;font-size:0.8em">'
                        f'{uid}…</div>',
                        unsafe_allow_html=True)

        # Image principale
        if l.get("cover_image_url"):
            try:
                st.image(l["cover_image_url"], use_column_width=True)
            except Exception:
                st.caption("📷 Image indisponible")
        else:
            st.caption("📷 Pas d'image")

        # Galerie photos
        if len(photos) > 1:
            with st.expander(f"📸 Galerie ({len(photos)} photos)"):
                gcols = st.columns(3)
                for pi, photo_url in enumerate(photos[:12]):
                    with gcols[pi % 3]:
                        try:
                            st.image(photo_url, use_column_width=True)
                        except Exception:
                            pass

        # Description
        if desc:
            short = desc[:2000]
            with st.expander("📝 Description"):
                st.write(short)
                if len(desc) > 2000:
                    if st.button("Lire tout", key=f"full_{uid}_{hash(url)}"):
                        st.write(desc)

        # ── Traductions Claude ────────────────────────────────────────────────
        tr_key = f"tr_{uid}_{hash(url)}"
        with st.expander("🌍 Traduction"):
            tr_col1, tr_col2, tr_col3 = st.columns(3)
            lang_chosen = None
            if tr_col1.button("🇫🇷 FR", key=f"{tr_key}_fr"):
                lang_chosen = "fr"
            if tr_col2.button("🇬🇧 EN", key=f"{tr_key}_en"):
                lang_chosen = "en"
            if tr_col3.button("🇩🇪 DE", key=f"{tr_key}_de"):
                lang_chosen = "de"

            cache_key = f"{tr_key}_{lang_chosen}"
            if lang_chosen:
                if cache_key not in st.session_state:
                    with st.spinner("Traduction en cours…"):
                        from modules.llm_client import translate_and_anonymize
                        result = translate_and_anonymize(
                            listing_id=l.get("id", ""),
                            text=desc[:1500],
                            target_lang=lang_chosen,
                        )
                        st.session_state[cache_key] = result
                result = st.session_state.get(cache_key, {})
                if result.get("desc_tr"):
                    st.markdown(f"**Localisation anonymisée :** {result.get('location_anon', '—')}")
                    st.write(result["desc_tr"])
                else:
                    st.warning("Clé ANTHROPIC_API_KEY absente ou erreur API.")

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
def _text_filter(data: list[dict], query: str) -> list[dict]:
    if not query:
        return data
    ql = query.lower().strip()
    return [
        l for l in data
        if ql in (l.get("title") or "").lower()
        or ql in (l.get("description_clean") or "").lower()
        or ql in (l.get("ville_canonical") or l.get("ville") or "").lower()
        or ql in (l.get("ref") or "").lower()
    ]


def _supabase_fts(query: str, limit: int = 50) -> list[dict]:
    """Full-text search via Supabase GIN index when available."""
    try:
        from modules.supabase_client import get_client
        client = get_client()
        if not client:
            return []
        resp = (
            client.table("listings")
            .select("*")
            .text_search("description_clean", query, config="spanish")
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


def page_recherche(data: list[dict]):
    st.header("🔍 Recherche")

    q = st.text_input(
        "Recherche plein-texte",
        placeholder="ex: finca piscine, licencia turistica, vue mer…",
        help="Recherche dans le titre, la description et la ville",
    )

    use_supa = False
    try:
        from modules.supabase_client import _use_supabase
        use_supa = _use_supabase()
    except Exception:
        pass

    if q and use_supa:
        results = _supabase_fts(q)
        if results:
            st.caption(f"🗄️ Supabase FTS — **{len(results)}** résultats")
            _grille(results)
            return

    results = _text_filter(data, q)
    st.info(f"**{len(results)} annonces** — {('filtrées par: \"' + q + '\"') if q else 'tous les filtres sidebar'}")
    _grille(results)


# ── PAGE CLIENTS ──────────────────────────────────────────────────────────────
_CLIENTS_FILE = Path(__file__).parent / "data" / "clients.json"


def _load_clients() -> list[dict]:
    if not _CLIENTS_FILE.exists():
        return []
    try:
        return json.loads(_CLIENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_clients(clients: list[dict]):
    tmp = _CLIENTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(clients, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_CLIENTS_FILE)


def page_clients(all_data: list[dict]):
    st.header("👥 Fiches Clients")

    clients = _load_clients()

    # ── Ajouter un client ────────────────────────────────────────────────────
    with st.expander("➕ Nouveau client", expanded=not clients):
        name = st.text_input("Nom du client")
        raw_text = st.text_area(
            "Critères (texte libre)",
            placeholder="Budget 150k-300k€, finca avec terrain 5000m² min, piscine, vue montagne, Tortosa ou Gandesa",
            height=120,
        )
        if st.button("Enregistrer le profil", disabled=not name or not raw_text):
            from modules.client_parser import parse
            profile = parse(name.strip(), raw_text.strip())
            clients.append(profile)
            _save_clients(clients)
            st.success(f"Profil « {name} » enregistré.")
            st.rerun()

    if not clients:
        st.info("Aucun client enregistré. Créez un profil ci-dessus.")
        return

    # ── Liste clients ─────────────────────────────────────────────────────────
    client_names = [c["name"] for c in clients]
    sel_name = st.selectbox("Client actif", client_names)
    profile = next((c for c in clients if c["name"] == sel_name), None)
    if not profile:
        return

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader(f"Profil : {profile['name']}")
        st.markdown(f"**Budget :** {_fmt_price(profile.get('budget_min'))} — {_fmt_price(profile.get('budget_max'))}")
        st.markdown(f"**Terrain :** {_fmt_m2(profile.get('terrain_min'))} — {_fmt_m2(profile.get('terrain_max'))}")
        st.markdown(f"**Bâti :** {_fmt_m2(profile.get('construction_min'))} — {_fmt_m2(profile.get('construction_max'))}")
        st.markdown(f"**Types :** {', '.join(profile.get('types') or []) or '—'}")
        st.markdown(f"**Villes :** {', '.join(profile.get('villes') or []) or '—'}")
        st.markdown(f"**Mots-clés requis :** {', '.join(profile.get('keywords_must') or []) or '—'}")
        st.markdown(f"**Mots-clés exclus :** {', '.join(profile.get('keywords_must_not') or []) or '—'}")
        st.divider()
        if st.button("🗑️ Supprimer ce client", type="secondary"):
            clients = [c for c in clients if c["name"] != sel_name]
            _save_clients(clients)
            st.rerun()

    with col_r:
        st.subheader("Annonces correspondantes")
        if st.button("🔍 Lancer le matching"):
            from modules.client_matching import rank_listings
            with st.spinner("Matching en cours…"):
                matches = rank_listings(all_data, profile)
            if matches:
                st.success(f"**{len(matches)} correspondances** trouvées.")
                for m in matches[:20]:
                    score = m.pop("_match_score", 0)
                    with st.container(border=True):
                        sc1, sc2 = st.columns([3, 1])
                        sc1.markdown(f"**{m.get('title', 'Sans titre')}**")
                        sc2.markdown(f"Score : **{score:.0%}**")
                        st.caption(
                            f"{_fmt_price(m.get('prix_eur'))} | "
                            f"{_fmt_m2(m.get('terrain_m2'))} terrain | "
                            f"{m.get('ville_canonical') or m.get('ville') or '—'}"
                        )
                        st.markdown(
                            f'<a href="{m.get("url","#")}" target="_blank">🔗 Voir</a>',
                            unsafe_allow_html=True,
                        )
            else:
                st.warning("Aucune correspondance.")


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


# ── PAGE ADMIN ────────────────────────────────────────────────────────────────
def page_admin(all_data: list[dict]):
    st.header("🛠️ Administration")

    stats = scrape_stats()

    # Résumé global
    col1, col2, col3 = st.columns(3)
    col1.metric("Total listings (master)", stats.get("total", 0))
    col2.metric("Sources actives", len(stats.get("by_site", {})))
    last = stats.get("last_run")
    col3.metric("Dernier scrape", last[:10] if last else "—")

    st.divider()

    # Par source
    st.subheader("Annonces par source (fichiers JSON)")
    by_site = stats.get("by_site", {})
    if by_site:
        df = pd.DataFrame(
            sorted(by_site.items(), key=lambda x: x[1], reverse=True),
            columns=["Fichier source", "Annonces"]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # Qualité des données
    st.subheader("Qualité des données")
    total = len(all_data)
    if total > 0:
        fields = [
            ("prix_eur", "Prix"),
            ("terrain_m2", "Terrain m²"),
            ("construction_m2", "Construction m²"),
            ("cover_image_url", "Image couverture"),
            ("description_clean", "Description"),
            ("ville_canonical", "Ville"),
            ("ref", "Référence"),
        ]
        quality_rows = []
        for field, label in fields:
            count = sum(1 for l in all_data if l.get(field))
            pct = round(100 * count / total, 1)
            quality_rows.append({"Champ": label, "Rempli": count, "%": pct})
        df_q = pd.DataFrame(quality_rows)
        st.dataframe(df_q, use_container_width=True, hide_index=True)

    st.divider()

    # Logs
    st.subheader("Logs pipeline")
    log_path = Path(__file__).parent / "logs" / "pipeline.jsonl"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        recent = lines[-50:][::-1]
        log_rows = []
        for line in recent:
            try:
                entry = json.loads(line)
                log_rows.append({
                    "Heure": entry.get("ts", "")[:19],
                    "Niveau": entry.get("level", ""),
                    "Message": entry.get("msg", "")[:120],
                })
            except Exception:
                pass
        if log_rows:
            df_logs = pd.DataFrame(log_rows)
            st.dataframe(df_logs, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucun log JSONL disponible (lancez un scrape d'abord).")

    st.divider()

    # Actions
    st.subheader("Actions")
    col_a, col_b = st.columns(2)
    if col_a.button("🔄 Recharger master.json"):
        st.cache_data.clear()
        st.rerun()
    if col_b.button("🗄️ Test connexion Supabase"):
        try:
            from modules.supabase_client import get_client, _use_supabase
            if _use_supabase():
                client = get_client()
                client.table("listings").select("id").limit(1).execute()
                st.success("✅ Supabase connecté")
            else:
                st.warning("⚠️ SUPABASE_URL non configuré — mode JSON local actif")
        except Exception as e:
            st.error(f"❌ Erreur Supabase : {e}")


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
| ThinkSpain — Fincas + Undeveloped lands | Rayon 75km Tortosa | EVOMI |
| Kyero — Maisons de campagne Tarragona | Province | EVOMI |
| **36 agences locales** (7 familles CMS + 14 JS) | Terres de l'Ebre | Non |

### Pipeline
```
Scrape → Dédup SHA256 → Nettoyage HTML → Filtre solaire → Merge Master → Carte/Grille
```

### Commandes
```bash
./start.sh   # Menu interactif
```

### Filtres automatiques
- 🌞 **Solar** : annonces contenant "placas solares", "paneles solares" → exclues
- 🏖️ **Licence touristique** : Idealista uniquement → gardées si "licencia", "airbnb", "booking"...
- ♻️ **Déduplication** : SHA256(url + 25 premiers mots description)
- 🗑️ **Bruit URL** : login, contact, blog, etc. filtrés avant fetch HTTP
    """)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    all_data = _load()
    filtered, page = _sidebar_filters(all_data)

    if "Carte" in page:
        page_carte(filtered)
    elif "Recherche" in page:
        page_recherche(filtered)
    elif "Clients" in page:
        page_clients(all_data)
    elif "Stats" in page:
        page_stats(all_data)
    elif "Admin" in page:
        page_admin(all_data)
    else:
        page_about()


if __name__ == "__main__":
    main()
