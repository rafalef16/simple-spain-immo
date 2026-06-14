import re
import hashlib


_NOISE_PATTERNS = [
    (r'<script[^>]*>.*?</script>', ' '),
    (r'<style[^>]*>.*?</style>', ' '),
    (r'<svg[^>]*>.*?</svg>', ' '),
    (r'<iframe[^>]*>.*?</iframe>', ' '),
    (r'<!--.*?-->', ' '),
    (r'<[^>]+>', ' '),
    (r'&nbsp;', ' '),
    (r'&amp;', '&'),
    (r'&lt;', '<'),
    (r'&gt;', '>'),
    (r'&quot;', '"'),
    (r'&#39;', "'"),
    (r'&rsquo;', "'"),
    (r'&ldquo;|&rdquo;', '"'),
    (r'&mdash;', '—'),
    (r'&hellip;', '...'),
    (r'\s{2,}', ' '),
]

_COMPILED = [(re.compile(p, re.DOTALL | re.IGNORECASE), r) for p, r in _NOISE_PATTERNS]


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = raw_html
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text.strip()


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace(' ', ' ').replace('\t', ' ')
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def extract_og_image(html: str) -> str | None:
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
    return m.group(1) if m else None


def extract_json_ld_image(html: str) -> str | None:
    import json
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                img = item.get('image')
                if isinstance(img, str) and img.startswith('http'):
                    return img
                if isinstance(img, list) and img:
                    return img[0]
        except Exception:
            pass
    return None


def cover_image(html: str, site: str = "") -> str | None:
    url = extract_og_image(html) or extract_json_ld_image(html)
    if url:
        return url

    site_patterns = {
        "fotocasa": r'https://[^"\']+static\.fotocasa[^"\']+',
        "idealista": r'https://[^"\']+idealista[^"\']+\.(jpg|jpeg|png|webp)',
        "thinkspain": r'https://[^"\']+thinkspain[^"\']+\.(jpg|jpeg|png|webp)',
        "kyero": r'https://[^"\']+kyero[^"\']+\.(jpg|jpeg|png|webp)',
    }
    if site in site_patterns:
        m = re.search(site_patterns[site], html, re.IGNORECASE)
        if m:
            return m.group(0)

    m = re.search(r'<img[^>]+src=["\']([^"\']+\.(jpg|jpeg|png|webp))["\']', html, re.IGNORECASE)
    return m.group(1) if m else None


def dedup_hash(url: str, description: str) -> str:
    words = description.lower().strip().split()[:25]
    key = url + " " + " ".join(words)
    return hashlib.sha256(key.encode()).hexdigest()


def parse_price(raw: str) -> tuple[int | None, str]:
    if not raw:
        return None, ""
    clean = raw.replace('\xa0', '').replace(' ', '').replace('.', '').replace(',', '').replace('€', '').strip()
    digits = re.sub(r'[^\d]', '', clean)
    if digits:
        return int(digits), raw.strip()
    return None, raw.strip()


def parse_surface(raw: str) -> int | None:
    if not raw:
        return None
    m = re.search(r'(\d[\d\s\.]*)\s*m', raw.replace(',', '.'))
    if m:
        val = re.sub(r'[^\d]', '', m.group(1))
        return int(val) if val else None
    return None


def is_solar_listing(description: str) -> bool:
    desc_lower = description.lower()
    solar_indicators = ["placas solares", "paneles solares", "energia solar", "placa solar", "panel solar"]
    return any(ind in desc_lower for ind in solar_indicators)
