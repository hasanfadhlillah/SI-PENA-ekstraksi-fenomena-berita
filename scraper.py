# File: scraper.py
import requests
from html.parser import HTMLParser
import re
from radar.logger_config import get_logger
logger = get_logger(__name__)
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
# Ekstraksi tanggal publikasi ASLI dari HTML
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
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
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
        tanggal_terbit = _ekstrak_tanggal_terbit(html_mentah)
        return {"judul": judul, "teks": teks, "tanggal_terbit": tanggal_terbit}
    except Exception:
        return None
def _metode_wayback(url: str) -> dict | None:
    """
    Metode 3: Wayback Machine (archive.org) — PENGGANTI Google Cache.
    """
    try:
        avail_resp = requests.get(
            "https://archive.org/wayback/available",
            params={"url": url},
            timeout=10
        )
        if avail_resp.status_code != 200:
            return None
        data = avail_resp.json()
        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        snapshot_url = snapshot.get("url", "")
        if not snapshot_url or not snapshot.get("available", False):
            return None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(snapshot_url, headers=headers, timeout=25)
        if resp.status_code != 200:
            return None
        html_mentah = resp.text
        teks = _html_ke_teks(html_mentah)
        judul = ""
        match = re.search(r'<title[^>]*>(.*?)</title>', html_mentah, re.IGNORECASE | re.DOTALL)
        if match:
            judul = match.group(1).strip()
            judul = re.sub(r'\s*[\|\-–]\s*wayback machine\s*$', '', judul, flags=re.IGNORECASE).strip()
        tanggal_terbit = _ekstrak_tanggal_terbit(html_mentah)
        return {"judul": judul, "teks": teks, "tanggal_terbit": tanggal_terbit}
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

# Memaksa muat halaman penuh via "?page=all" pada domain tertentu demi efisiensi proses.
_SITUS_SERING_BERHALAMAN = ("kompas.com", "bisnis.com", "liputan6.com")
def _kemungkinan_situs_berhalaman(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(situs in domain for situs in _SITUS_SERING_BERHALAMAN)
_POLA_INDIKATOR_BERHALAMAN = [
    r'halaman\s*:?\s*\d+\s*,?\s*\d*',   # "Halaman: 1, 2" / "Halaman 1 2"
    r'\bshow\s*all\b',
    r'\blihat\s*semua\b',
    r'\bpage\s*\d+\s*of\s*\d+\b',
]
def _terdeteksi_artikel_berhalaman(teks_mentah: str) -> bool:
    """
    Mendeteksi tanda artikel multi-halaman pada teks mentah sebelum baris navigasi 
    pendek (<25 karakter) terhapus oleh `bersihkan_teks_artikel()`. Jika ditemukan, 
    `scrape_berita()` akan memicu coba ulang menggunakan parameter '?page=all'.
    """
    if not teks_mentah:
        return False
    t = teks_mentah.lower()
    return any(re.search(pola, t) for pola in _POLA_INDIKATOR_BERHALAMAN)
def _coba_scrape_satu_url(clean_url: str) -> dict | None:
    """
    Coba scrape SATU url spesifik lewat 3 metode berlapis (Jina Reader →
    Direct Request → Wayback Machine). Return dict hasil sukses, atau None
    kalau ketiga metode gagal untuk url ini.
    """
    metode_list = [
        ("Jina Reader API",   _metode_jina),
        ("Direct Request",    _metode_direct),
        ("Wayback Machine",   _metode_wayback),
    ]
    for nama_metode, fungsi in metode_list:
        logger.debug(f"[Mencoba] {nama_metode} untuk {clean_url[:60]}...")
        hasil = fungsi(clean_url)
        if hasil is None:
            logger.debug(f"[Gagal] {nama_metode}: Tidak ada respons untuk {clean_url[:60]}...")
            continue
        judul          = hasil.get("judul", "")
        teks_mentah    = hasil.get("teks", "")
        tanggal_terbit = hasil.get("tanggal_terbit", "")
        if _is_cloudflare_block(judul, teks_mentah):
            logger.debug(f"[Diblokir] {nama_metode}: Kena Cloudflare challenge di {clean_url[:60]}...")
            continue
        teks_bersih = bersihkan_teks_artikel(teks_mentah)
        if hitung_kata(teks_bersih) < 80:
            logger.debug(
                f"[Gagal] {nama_metode}: Teks terlalu sedikit kata "
                f"({hitung_kata(teks_bersih)} kata) di {clean_url[:60]}..."
            )
            continue
        logger.info(f"[Sukses] Scraping via {nama_metode}: {clean_url[:60]}...")
        return {
            "status":               "sukses",
            "metode":               nama_metode,
            "judul":                judul or "Judul diekstrak AI",
            "tanggal":              tanggal_terbit,
            "tanggal_pasti_scrape": bool(tanggal_terbit),
            "teks":                 teks_bersih,
            "berhalaman":           _terdeteksi_artikel_berhalaman(teks_mentah),
        }
    return None
# ─── Fungsi Utama ─────────────────────────────────────────────────────────────
def scrape_berita(url: str) -> dict:
    """
    Scraper 3-lapis (Jina/Direct/Wayback) yang otomatis menangani artikel multi-halaman
    untuk memastikan seluruh teks terambil, mencegah AI salah menyimpulkan informasi 
    hilang akibat halaman berikutnya gagal ter-scrape.
    """
    clean_url = url.split('?')[0]

    # Bypass ke versi gabungan untuk domain multi-halaman guna menghemat round-trip.
    if _kemungkinan_situs_berhalaman(clean_url):
        url_gabungan = f"{clean_url}?page=all"
        hasil = _coba_scrape_satu_url(url_gabungan)
        if hasil is not None:
            hasil.pop("berhalaman", None)
            hasil["url"] = clean_url
            logger.info(f"[Multi-Halaman] Situs dikenal sering berhalaman, langsung pakai versi gabungan: {clean_url[:60]}...")
            return hasil
        # kalau gagal, lanjut ke alur normal di bawah

    hasil = _coba_scrape_satu_url(clean_url)
    if hasil is not None:
        if hasil.get("berhalaman"):
            logger.info(f"[Multi-Halaman Terdeteksi] Mencoba ambil versi gabungan (?page=all): {clean_url[:60]}...")
            url_gabungan  = f"{clean_url}?page=all"
            hasil_gabungan = _coba_scrape_satu_url(url_gabungan)
            if (hasil_gabungan is not None
                    and hitung_kata(hasil_gabungan["teks"]) > hitung_kata(hasil["teks"]) * 1.2):
                logger.info(
                    f"[Multi-Halaman] Versi gabungan lebih lengkap "
                    f"({hitung_kata(hasil_gabungan['teks'])} vs {hitung_kata(hasil['teks'])} kata), dipakai."
                )
                hasil = hasil_gabungan
            else:
                logger.debug("[Multi-Halaman] Versi gabungan tidak lebih lengkap/gagal, tetap pakai versi awal.")
        hasil.pop("berhalaman", None)
        hasil["url"] = clean_url
        return hasil

    # Versi normal gagal total -> coba versi gabungan sebagai upaya terakhir
    logger.debug(f"[Fallback] Coba langsung versi ?page=all untuk {clean_url[:60]}...")
    url_gabungan   = f"{clean_url}?page=all"
    hasil_gabungan = _coba_scrape_satu_url(url_gabungan)
    if hasil_gabungan is not None:
        hasil_gabungan.pop("berhalaman", None)
        hasil_gabungan["url"] = clean_url
        return hasil_gabungan

    logger.warning(f"Semua metode scraping gagal untuk {clean_url[:60]}...")
    return {
        "status": "error",
        "pesan": (
            "Semua metode scraping gagal (Jina Reader, Direct Request, Wayback Machine). "
            "Situs ini diproteksi sangat ketat (Cloudflare Enterprise / Login Required) "
            "dan belum pernah diarsipkan. Coba salin teks artikel secara manual."
        )
    }