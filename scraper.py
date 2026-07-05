# File: scraper.py
import requests
from html.parser import HTMLParser
import re

# ─── Detektor Cloudflare ───────────────────────────────────────────────────────
CLOUDFLARE_TITLES = [
    "attention required", "just a moment",
    "checking your browser", "enable javascript", "403 forbidden", "cloudflare"
]

def _is_cloudflare_block(judul: str, teks: str) -> bool:
    """Mendeteksi apakah Jina mengembalikan halaman Cloudflare, bukan artikel asli."""
    j = judul.lower()
    t = teks.lower()
    return (
        any(kw in j for kw in CLOUDFLARE_TITLES) or
        ("ray id" in t and "cloudflare" in t) or
        len(teks) < 300
    )

# ─── Ekstraktor HTML Sederhana (tanpa library tambahan) ───────────────────────
class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.teks = []
        self._skip = False
        self._skip_tags = {'script', 'style', 'nav', 'footer', 'head', 'noscript', 'aside', 'header'}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.teks.append(data.strip())

def _html_ke_teks(html: str) -> str:
    p = _HTMLTextExtractor()
    p.feed(html)
    return "\n".join(p.teks)


# ═══════════════════════════════════════════════════════════════════════════
# FIX #1c — Ekstraksi tanggal publikasi ASLI dari HTML (bukan hardcode string)
# ═══════════════════════════════════════════════════════════════════════════
_BULAN_ID = {
    "januari": "01", "februari": "02", "maret": "03", "april": "04",
    "mei": "05", "juni": "06", "juli": "07", "agustus": "08",
    "september": "09", "oktober": "10", "november": "11", "desember": "12",
}

def _normalisasi_tanggal_terbit(raw: str) -> str:
    """
    Coba normalisasi berbagai format tanggal mentah jadi YYYY-MM-DD.
    Return "" jika tidak berhasil dikenali/diparsing.
    """
    if not raw:
        return ""
    raw = raw.strip()

    # Format ISO 8601: 2026-06-23T10:00:00+07:00 atau 2026-06-23
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # Format Indonesia: "23 Juni 2026" / "23 juni 2026"
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', raw)
    if m:
        tgl, bulan_str, tahun = m.groups()
        bulan = _BULAN_ID.get(bulan_str.lower())
        if bulan:
            return f"{tahun}-{bulan}-{int(tgl):02d}"

    return ""


def _ekstrak_tanggal_terbit(html: str) -> str:
    """
    Coba ekstrak tanggal publikasi ASLI dari halaman HTML, urutan prioritas:
    1. Meta tag article:published_time / og:published_time
    2. JSON-LD "datePublished"
    3. Meta tag publish-date (beberapa CMS pakai ini)
    4. Tag <time datetime="...">

    Return string YYYY-MM-DD jika berhasil, "" jika tidak ditemukan/gagal parse.
    Dipakai sebagai FIX untuk bug lama yang hardcode field "tanggal" jadi string
    placeholder "Diekstrak otomatis oleh AI" — sekarang kalau ketemu, AI ekstraksi
    (ai_engine.py) benar-benar dapat tanggal terbit asli, bukan teks yang menyesatkan.
    """
    if not html:
        return ""

    pola_meta = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'<meta[^>]+property=["\']og:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']publish-date["\'][^>]+content=["\']([^"\']+)["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
    ]
    for pola in pola_meta:
        m = re.search(pola, html, re.IGNORECASE)
        if m:
            hasil = _normalisasi_tanggal_terbit(m.group(1))
            if hasil:
                return hasil

    m = re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        hasil = _normalisasi_tanggal_terbit(m.group(1))
        if hasil:
            return hasil

    return ""


# ─── 3 Metode Scraping ────────────────────────────────────────────────────────
def _metode_jina(url: str) -> dict | None:
    """Metode 1: Jina Reader API (bypass Cloudflare otomatis)."""
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "application/json", "X-Return-Format": "markdown"},
            timeout=45
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})
        # FIX #1c: Jina Reader kadang menyertakan field publishedTime di respons JSON-nya
        tanggal_mentah = data.get("publishedTime", "") or ""
        return {
            "judul": data.get("title", ""),
            "teks": data.get("content", ""),
            "tanggal_terbit": _normalisasi_tanggal_terbit(tanggal_mentah),
        }
    except Exception:
        return None

def _metode_direct(url: str) -> dict | None:
    """Metode 2: Request langsung dengan header browser asli."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
            "Referer": "https://www.google.com/",
        }
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            return None
        html_mentah = resp.text
        teks = _html_ke_teks(html_mentah)

        judul = ""
        match = re.search(r'<title[^>]*>(.*?)</title>', html_mentah, re.IGNORECASE | re.DOTALL)
        if match:
            judul = match.group(1).strip()

        # FIX #1c: ekstrak tanggal terbit asli dari HTML mentah SEBELUM dikonversi ke teks polos
        tanggal_terbit = _ekstrak_tanggal_terbit(html_mentah)

        return {"judul": judul, "teks": teks, "tanggal_terbit": tanggal_terbit}
    except Exception:
        return None

def _metode_google_cache(url: str) -> dict | None:
    """Metode 3: Google Cache sebagai fallback terakhir."""
    try:
        cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(cache_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        html_mentah = resp.text
        teks = _html_ke_teks(html_mentah)
        tanggal_terbit = _ekstrak_tanggal_terbit(html_mentah)  # FIX #1c
        return {"judul": "Dari Google Cache", "teks": teks, "tanggal_terbit": tanggal_terbit}
    except Exception:
        return None


def bersihkan_teks_artikel(teks: str) -> str:
    """
    Preprocessing teks hasil scraping sebelum dikirim ke AI.
    Menghapus noise umum dari halaman web.
    """
    teks = teks.replace('\r\n', '\n').replace('\r', '\n')

    baris = teks.split('\n')
    baris_bersih = [b for b in baris if len(b.strip()) >= 25]
    teks = '\n'.join(baris_bersih)

    teks = re.sub(r'[ \t]{2,}', ' ', teks)
    teks = re.sub(r'\n{3,}', '\n\n', teks)
    teks = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', teks)

    return teks.strip()


def hitung_kata(teks: str) -> int:
    """Hitung kata di dalam teks."""
    return len(teks.split())

# ─── Fungsi Utama ─────────────────────────────────────────────────────────────
def scrape_berita(url: str) -> dict:
    """
    Scraper berlapis 3:
    Jina Reader → Direct Request → Google Cache
    """
    clean_url = url.split('?')[0]

    metode_list = [
        ("Jina Reader API",   _metode_jina),
        ("Direct Request",    _metode_direct),
        ("Google Cache",      _metode_google_cache),
    ]

    for nama_metode, fungsi in metode_list:
        print(f"   -> [Mencoba] {nama_metode}...")

        hasil = fungsi(clean_url)

        if hasil is None:
            print(f"   -> [Gagal] {nama_metode}: Tidak ada respons.")
            continue

        judul          = hasil.get("judul", "")
        teks           = hasil.get("teks", "")
        tanggal_terbit = hasil.get("tanggal_terbit", "")   # FIX #1c

        if _is_cloudflare_block(judul, teks):
            print(f"   -> [Diblokir] {nama_metode}: Kena Cloudflare challenge.")
            continue

        teks_bersih = bersihkan_teks_artikel(teks)

        if hitung_kata(teks_bersih) < 80:
            print(f"   -> [Gagal] {nama_metode}: Teks terlalu sedikit kata ({hitung_kata(teks_bersih)} kata).")
            continue

        # Sukses!
        print(f"   -> [✅ Sukses] via {nama_metode}!")
        return {
            "status":               "sukses",
            "metode":               nama_metode,
            "url":                  clean_url,
            "judul":                judul or "Judul diekstrak AI",
            # FIX #1c: bukan lagi hardcode placeholder — pakai tanggal asli jika
            # berhasil ditemukan, kalau tidak biarkan kosong ("" = benar-benar
            # tidak diketahui, bukan string yang menyesatkan)
            "tanggal":              tanggal_terbit,
            "tanggal_pasti_scrape": bool(tanggal_terbit),
            "teks":                 teks_bersih,
        }

    return {
        "status": "error",
        "pesan": (
            "Semua metode scraping gagal. "
            "Situs ini diproteksi sangat ketat (Cloudflare Enterprise / Login Required). "
            "Coba salin teks artikel secara manual."
        )
    }