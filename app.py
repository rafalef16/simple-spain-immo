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
            l.get("ville") or l.get("ville_canonical") or ""
            for l in all_data
            if l.get("ville") or l.get("ville_canonical")
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
                if (l.get("ville") or l.get("ville_canonical") or "") in villes_sel]
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
            or ql in (l.get("ville") or l.get("ville_canonical") or "").lower()
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
        city = l.get("ville") or l.get("ville_canonical") or ""
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
        city = l.get("ville") or l.get("ville_canonical") or "—"
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
def _grille(data: list[dict], active_groups: dict | None = None):
    if not data:
        st.info("Aucune annonce ne correspond aux filtres.")
        return

    # 1 carte par ligne horizontale
    for l in data:
        _card(l, active_groups)


def _card(l: dict, active_groups: dict | None = None, select_client: str | None = None,
          ctx: str = ""):
    ptype     = _detect_type(l)
    is_tour   = _is_tourist(l)
    days      = _days_ago(l.get("scrap_timestamp"))
    price_m2  = _price_m2(l)
    city      = l.get("ville") or l.get("ville_canonical") or "—"
    coords    = resolve_coords(city)
    site      = (l.get("site") or "—")
    family    = (l.get("site_family") or "—")
    ref       = (l.get("ref") or "—")
    uid       = (l.get("id") or "")[:8] or "—"
    desc      = l.get("description_clean") or ""
    url       = l.get("url") or "#"
    title     = l.get("title") or "Sans titre"
    terrain   = l.get("terrain_m2")
    constr    = l.get("construction_m2")
    beds      = l.get("bedrooms")
    baths     = l.get("bathrooms")
    img       = l.get("cover_image_url")

    # Badges minimaux (type + signaux utiles ; le site va dans les FILTRES, pas la carte)
    type_cls = {"finca": "green", "casa": "blue", "touristic": "orange"}.get(ptype, "grey")
    badges = _badge_html(ptype.upper(), type_cls)
    if is_tour:
        badges += _badge_html("🏖️ TOURIST", "orange")
    if days is not None and days < 2:
        badges += _badge_html("🆕 NOUVEAU", "new")

    with st.container(border=True):
        # En-tête : titre + prix
        head_l, head_r = st.columns([3, 1])
        head_l.markdown(badges, unsafe_allow_html=True)
        head_l.markdown(f"### {title}")
        head_r.markdown(
            f'<div class="price-big" style="text-align:right">{_fmt_price(l.get("prix_eur"))}</div>',
            unsafe_allow_html=True,
        )

        # Ligne méta : uniquement les champs réellement présents (zéro bruit)
        bits = []
        if terrain: bits.append(f"📐 {_fmt_m2(terrain)} terrain")
        if constr:  bits.append(f"🏠 {_fmt_m2(constr)} bâti")
        if beds:    bits.append(f"🛏️ {beds}")
        if baths:   bits.append(f"🚿 {baths}")
        if city and city != "—": bits.append(f"📍 {city}")
        if bits:
            st.caption(" · ".join(bits))

        # Image PETITE à gauche + description complète (toujours visible) à droite
        img_col, desc_col = st.columns([1, 3])
        with img_col:
            if img:
                try:
                    st.image(img, width=150)
                except Exception:
                    st.caption("📷")
            else:
                st.caption("📷 —")
        with desc_col:
            if desc:
                st.write(desc)
            else:
                st.caption("_Pas de description disponible_")

        # ── Traduction (repliée pour ne pas encombrer) ────────────────────────
        tr_key = f"tr_{ctx}_{uid}_{hash(url)}"
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

        # ── Désactivation par annonce : kicker un faux positif d'un filtre actif ──
        if active_groups:
            st.caption("⚠️ Faux positif ? Retirer cette annonce d'un filtre :")
            kick_cols = st.columns(len(active_groups))
            for ki, (gk, gd) in enumerate(active_groups.items()):
                with kick_cols[ki]:
                    if st.button(f"❌ {gd['label']}", key=f"kick_{ctx}_{gk}_{uid}_{hash(url)}"):
                        _toggle_exclusion(gk, url)
                        st.rerun()

        # ── Présélection par client (fiche client) ───────────────────────────
        if select_client:
            selected = url in _client_selection(select_client)
            if selected:
                if st.button("✅ Dans la sélection — retirer", key=f"csel_{ctx}_{uid}_{hash(url)}",
                             type="secondary"):
                    _toggle_client_selection(select_client, url)
                    st.rerun()
            else:
                if st.button("➕ Ajouter à la sélection", key=f"csel_{ctx}_{uid}_{hash(url)}",
                             type="primary"):
                    _toggle_client_selection(select_client, url)
                    st.rerun()

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
        or ql in (l.get("ville") or l.get("ville_canonical") or "").lower()
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


def _contains_pattern(text: str, regex_pattern: str) -> bool:
    return bool(re.search(regex_pattern, text.lower()))


# ── Exclusions manuelles par filtre (faux positifs kické depuis l'annonce) ────
_EXCL_FILE = Path(__file__).parent / "data" / "filter_exclusions.json"


def _load_exclusions() -> dict:
    if not _EXCL_FILE.exists():
        return {}
    try:
        return json.loads(_EXCL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _toggle_exclusion(group_key: str, url: str):
    """Ajoute/retire une annonce de la liste d'exclusion d'un filtre."""
    excl = _load_exclusions()
    lst = excl.setdefault(group_key, [])
    if url in lst:
        lst.remove(url)
    else:
        lst.append(url)
    tmp = _EXCL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(excl, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_EXCL_FILE)


def _search_with_synonyms(data: list[dict], selected_groups: dict) -> list[dict]:
    excl = _load_exclusions()
    filtered = data.copy()
    for gk, group_data in selected_groups.items():
        combined = "|".join(group_data["patterns"])
        kicked = set(excl.get(gk, []))
        filtered = [
            item for item in filtered
            if _contains_pattern(item.get("description_clean", ""), combined)
            and item.get("url") not in kicked   # faux positifs retirés à la main
        ]
    return filtered


def _search_freetext(data: list[dict], query: str) -> list[dict]:
    from modules.search_terms import SEARCH_SYNONYMS
    if "|" in query:
        logic, terms = "OR", [t.strip() for t in query.split("|")]
    else:
        logic, terms = "AND", re.split(r"[\s\+]+", query.strip())

    expanded: list[str] = []
    for term in terms:
        tc = term.lower().strip()
        if not tc:
            continue
        found = False
        for gd in SEARCH_SYNONYMS.values():
            if tc in [t.lower() for t in gd["terms"]]:
                expanded.extend(gd["patterns"])
                found = True
                break
        if not found:
            expanded.append(re.escape(tc))

    if not expanded:
        return data

    filtered = data.copy()
    if logic == "AND":
        for pat in expanded:
            filtered = [l for l in filtered if _contains_pattern(l.get("description_clean", ""), pat)]
    else:
        combined = "|".join(expanded)
        filtered = [l for l in filtered if _contains_pattern(l.get("description_clean", ""), combined)]
    return filtered


def _filter_agua(data: list[dict], mode: str) -> list[dict]:
    from modules.search_terms import AGUA_CON_PATTERNS, AGUA_SIN_PATTERNS, AGUA_ANY
    if mode == "Con agua":
        pat = "|".join(AGUA_CON_PATTERNS)
        return [l for l in data if _contains_pattern(l.get("description_clean", ""), pat)]
    if mode == "Sin agua":
        pat = "|".join(AGUA_SIN_PATTERNS)
        return [l for l in data if _contains_pattern(l.get("description_clean", ""), pat)]
    if mode == "Non mentionné":
        return [l for l in data if not _contains_pattern(l.get("description_clean", ""), AGUA_ANY)]
    return data


def _filter_luz(data: list[dict], mode: str) -> list[dict]:
    from modules.search_terms import LUZ_CON_PATTERNS, LUZ_SIN_PATTERNS, LUZ_ANY
    if mode == "Con luz":
        pat = "|".join(LUZ_CON_PATTERNS)
        return [l for l in data if _contains_pattern(l.get("description_clean", ""), pat)]
    if mode == "Sin luz":
        pat = "|".join(LUZ_SIN_PATTERNS)
        return [l for l in data if _contains_pattern(l.get("description_clean", ""), pat)]
    if mode == "Non mentionné":
        return [l for l in data if not _contains_pattern(l.get("description_clean", ""), LUZ_ANY)]
    return data


def page_recherche(data: list[dict]):
    from modules.search_terms import SEARCH_SYNONYMS

    st.header("🔍 Recherche granulaire")

    # ── SLIDER PRIX ───────────────────────────────────────────────────────────
    prices = [l["prix_eur"] for l in data if l.get("prix_eur")]
    if prices:
        p_min, p_max = int(min(prices)), int(max(prices))
        if p_min < p_max:
            price_range = st.slider(
                "💶 Budget (€)",
                min_value=p_min, max_value=p_max,
                value=(p_min, p_max),
                step=5_000, format="%d €",
            )
            data = [l for l in data if price_range[0] <= (l.get("prix_eur") or 0) <= price_range[1]]

    st.caption(f"**{len(data)}** biens dans la sélection courante")
    st.divider()

    # ── FILTRE SOURCE (Kyero · Fotocasa · Idealista · ThinkSpain · Mobilia …) ──
    src_labels = {"kyero": "🟣 Kyero", "fotocasa": "🔵 Fotocasa", "idealista": "🟢 Idealista",
                  "thinkspain": "🟠 ThinkSpain", "mobilia": "🟡 Mobilia (38 agences)",
                  "finquesmar": "🔴 FinquesMar"}
    present = sorted({(l.get("site") or "").lower() for l in data if l.get("site")})
    src_options = [src_labels.get(s, s.title()) for s in present]
    _lbl2site = {src_labels.get(s, s.title()): s for s in present}
    src_sel = st.multiselect("📡 Sources", src_options, key="src_filter")
    if src_sel:
        wanted = {_lbl2site[lbl] for lbl in src_sel}
        data = [l for l in data if (l.get("site") or "").lower() in wanted]

    # ── FILTRE SURFACES (discrimination casita ≤400 m² / terrain >400 m²) ──────
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        surf_kind = st.selectbox("📐 Type de surface", ["Toutes", "Avec casita (bâti)",
                                 "Terrain nu (sans bâti)"], key="surf_kind")
    with col_s2:
        ter_min = st.number_input("Terrain min (m²)", min_value=0, value=0, step=500, key="ter_min")
    with col_s3:
        bat_min = st.number_input("Bâti min (m²)", min_value=0, value=0, step=10, key="bat_min")
    if surf_kind == "Avec casita (bâti)":
        data = [l for l in data if (l.get("construction_m2") or 0) > 0]
    elif surf_kind == "Terrain nu (sans bâti)":
        data = [l for l in data if not (l.get("construction_m2") or 0)]
    if ter_min:
        data = [l for l in data if (l.get("terrain_m2") or 0) >= ter_min]
    if bat_min:
        data = [l for l in data if (l.get("construction_m2") or 0) >= bat_min]

    st.divider()

    # ── FILTRES EAU / ÉLECTRICITÉ ─────────────────────────────────────────────
    col_eau, col_luz = st.columns(2)
    with col_eau:
        eau_mode = st.selectbox("💧 Eau", ["Toutes", "Con agua", "Sin agua", "Non mentionné"], key="eau_mode")
    with col_luz:
        luz_mode = st.selectbox("⚡ Électricité", ["Toutes", "Con luz", "Sin luz", "Non mentionné"], key="luz_mode")

    data = _filter_agua(data, eau_mode)
    data = _filter_luz(data, luz_mode)

    st.divider()

    # ── TABS ──────────────────────────────────────────────────────────────────
    # Streamlit exécute le contenu des DEUX onglets à chaque rerun. On calcule donc
    # chaque filtre dans sa propre variable, puis on COMBINE à la fin — sans qu'un
    # onglet vide n'écrase le résultat de l'autre (bug « 18 résultats mais tout
    # reste affiché »).
    tab1, tab2 = st.tabs(["🏷️ Tags (facile)", "⌨️ Texte libre (avancé)"])
    res_tags = None
    res_free = None

    with tab1:
        st.subheader("Clique sur les catégories recherchées (AND)")
        selected_groups: dict = {}
        cols = st.columns(3)
        for i, (gk, gd) in enumerate(SEARCH_SYNONYMS.items()):
            with cols[i % 3]:
                if st.checkbox(gd["label"], key=f"chip_{gk}"):
                    selected_groups[gk] = gd

        st.divider()
        if selected_groups:
            st.write("**Filtres actifs :**")
            for gd in selected_groups.values():
                st.caption(f"**{gd['label']}** → {' | '.join(gd['terms'][:4])}")
            res_tags = _search_with_synonyms(data, selected_groups)
            # ── Liste d'exclusion dynamique : faux positifs retirés à la main ──
            excl = _load_exclusions()
            active_excl = {gk: excl.get(gk, []) for gk in selected_groups if excl.get(gk)}
            if active_excl:
                with st.expander(f"🚫 Exclusions manuelles ({sum(len(v) for v in active_excl.values())})"):
                    for gk, urls in active_excl.items():
                        st.caption(f"**{selected_groups[gk]['label']}** — {len(urls)} annonce(s) retirée(s)")
                        for u in urls:
                            cu, cb = st.columns([5, 1])
                            cu.write(f"`{u[:70]}`")
                            if cb.button("↩️", key=f"restore_{gk}_{hash(u)}", help="Réintégrer"):
                                _toggle_exclusion(gk, u)
                                st.rerun()
            st.write(f"**{len(res_tags)} résultats**")

    with tab2:
        st.subheader("Texte libre")
        st.caption("Syntaxe : `mot1 + mot2` (AND) · `mot1 | mot2` (OR)")
        query = st.text_area(
            "Requête",
            placeholder="piscina + vista + vallado\n\nou: piscina | balsa (l'une ou l'autre)",
            height=80, label_visibility="collapsed",
        )
        if query.strip():
            res_free = _search_freetext(data, query)
            st.write(f"**{len(res_free)} résultats**")

    # Combinaison : intersection si les deux actifs, sinon celui qui est actif.
    if res_tags is not None and res_free is not None:
        free_urls = {l.get("url") for l in res_free}
        results = [l for l in res_tags if l.get("url") in free_urls]
    elif res_tags is not None:
        results = res_tags
    elif res_free is not None:
        results = res_free
    else:
        results = data

    # ── RÉSULTATS ─────────────────────────────────────────────────────────────
    if results:
        st.divider()
        st.subheader(f"📋 Résultats ({len(results)})")
        # Les filtres chips actifs permettent de kicker un faux positif par annonce
        _grille(results, active_groups=selected_groups if selected_groups else None)
    else:
        st.info("Aucun résultat — essayez d'autres critères.")


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


def _client_selection(name: str) -> list[str]:
    """URLs présélectionnées pour un client (persistées dans clients.json)."""
    for c in _load_clients():
        if c["name"] == name:
            return c.get("selected_urls") or []
    return []


def _toggle_client_selection(name: str, url: str):
    """Ajoute/retire une annonce de la sélection d'un client."""
    clients = _load_clients()
    for c in clients:
        if c["name"] == name:
            sel = c.setdefault("selected_urls", [])
            if url in sel:
                sel.remove(url)
            else:
                sel.append(url)
            break
    _save_clients(clients)


def _property_map(listings: list[dict], height: int = 430):
    """Mini-carte folium des biens fournis (réutilise le rendu de la page Carte)."""
    geo = []
    for l in listings:
        city = l.get("ville") or l.get("ville_canonical") or ""
        coords = resolve_coords(city)
        if coords:
            geo.append((l, coords))
    if not geo:
        st.caption("📍 Aucun bien géolocalisable dans la sélection.")
        return
    m = folium.Map(location=[40.85, 0.55], zoom_start=10,
                   tiles="CartoDB Positron", prefer_canvas=True)
    for l, (lat, lon) in geo:
        price_str = _fmt_price(l.get("prix_eur"))
        city = l.get("ville") or l.get("ville_canonical") or "—"
        popup = (f'<b>{(l.get("title") or "Annonce")[:70]}</b><br>'
                 f'<span style="color:#2e7d32;font-weight:700">{price_str}</span><br>'
                 f'🏞️ {_fmt_m2(l.get("terrain_m2"))} · 🏠 {_fmt_m2(l.get("construction_m2"))}<br>'
                 f'📍 {city}<br><a href="{l.get("url","#")}" target="_blank">Voir →</a>')
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup, max_width=260),
            tooltip=f"{price_str} — {city}",
            icon=folium.Icon(color=_marker_color(_detect_type(l)), icon="home", prefix="fa"),
        ).add_to(m)
    st_folium(m, width="100%", height=height, returned_objects=[])


def _profile_summary(profile: dict):
    """Critères du client, format compact (dropdown)."""
    st.markdown(f"**Budget :** {_fmt_price(profile.get('budget_min'))} — {_fmt_price(profile.get('budget_max'))}")
    st.markdown(f"**Terrain :** {_fmt_m2(profile.get('terrain_min'))} — {_fmt_m2(profile.get('terrain_max'))}")
    st.markdown(f"**Bâti :** {_fmt_m2(profile.get('construction_min'))} — {_fmt_m2(profile.get('construction_max'))}")
    st.markdown(f"**Types :** {', '.join(profile.get('types') or []) or '—'}")
    st.markdown(f"**Villes :** {', '.join(profile.get('villes') or []) or '—'}")
    st.markdown(f"**Mots-clés requis :** {', '.join(profile.get('keywords_must') or []) or '—'}")
    st.markdown(f"**Mots-clés exclus :** {', '.join(profile.get('keywords_must_not') or []) or '—'}")


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

    # ── Cartes clients THIN (1 ligne compacte par client) ─────────────────────
    by_url = {l.get("url"): l for l in all_data}
    st.caption("Sélectionnez un client pour ouvrir sa fiche.")
    cli_cols = st.columns(min(4, len(clients)))
    for i, c in enumerate(clients):
        with cli_cols[i % len(cli_cols)]:
            n_sel = len(c.get("selected_urls") or [])
            st.metric(c["name"], f"⭐ {n_sel}", help="Biens présélectionnés")

    client_names = [c["name"] for c in clients]
    sel_name = st.selectbox("📂 Client actif", client_names)
    profile = next((c for c in clients if c["name"] == sel_name), None)
    if not profile:
        return

    # Fiche compacte : critères en dropdown + suppression
    head_l, head_r = st.columns([4, 1])
    with head_l:
        with st.expander(f"📋 Critères de « {profile['name']} »"):
            _profile_summary(profile)
    with head_r:
        if st.button("🗑️ Supprimer", type="secondary", key=f"del_{sel_name}"):
            clients = [c for c in clients if c["name"] != sel_name]
            _save_clients(clients)
            st.rerun()

    sel_urls = _client_selection(sel_name)
    sel_listings = [by_url[u] for u in sel_urls if u in by_url]

    tab_sel, tab_match = st.tabs(
        [f"⭐ Sélection client ({len(sel_listings)})", "🎯 Matching automatique"])

    # ── Onglet SÉLECTION : carte + cartes biens (format identique à « Carte ») ─
    with tab_sel:
        if sel_listings:
            st.subheader("🗺️ Carte de la sélection")
            _property_map(sel_listings)
            st.divider()
            st.subheader("📋 Biens sélectionnés")
            for l in sel_listings:
                _card(l, select_client=sel_name, ctx="sel")
        else:
            st.info("Aucun bien sélectionné. Ajoutez-en depuis l'onglet « Matching ».")

    # ── Onglet MATCHING : résultats en cartes complètes + bouton présélection ─
    with tab_match:
        if st.button("🔍 Lancer le matching", key=f"match_{sel_name}"):
            st.session_state[f"_matches_{sel_name}"] = True
        if st.session_state.get(f"_matches_{sel_name}"):
            from modules.client_matching import rank_listings
            with st.spinner("Matching en cours…"):
                matches = rank_listings(all_data, profile)
            if matches:
                st.success(f"**{len(matches)} correspondances** trouvées.")
                for m in matches[:30]:
                    m.pop("_match_score", None)
                    _card(m, select_client=sel_name, ctx="match")
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
        city = l.get("ville") or l.get("ville_canonical") or "—"
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
