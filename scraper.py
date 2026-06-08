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
        len(teks) < 300  # Teks terlalu pendek = kemungkinan bukan artikel
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
        return {
            "judul": data.get("title", ""),
            "teks": data.get("content", "")
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
        teks = _html_ke_teks(resp.text)
        
        # Ambil judul dari tag <title>
        judul = ""
        match = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
        if match:
            judul = match.group(1).strip()
            
        return {"judul": judul, "teks": teks}
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
        teks = _html_ke_teks(resp.text)
        return {"judul": "Dari Google Cache", "teks": teks}
    except Exception:
        return None


def bersihkan_teks_artikel(teks: str) -> str:
    """
    Preprocessing teks hasil scraping sebelum dikirim ke AI.
    Menghapus noise umum dari halaman web.
    """
    # 1. Normalisasi line ending
    teks = teks.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Hapus baris yang sangat pendek (< 25 karakter) — biasanya noise navigasi
    baris = teks.split('\n')
    baris_bersih = [b for b in baris if len(b.strip()) >= 25]
    teks = '\n'.join(baris_bersih)
    
    # 3. Hapus multiple whitespace horizontal
    teks = re.sub(r'[ \t]{2,}', ' ', teks)
    
    # 4. Kompres multiple baris kosong jadi maks 2
    teks = re.sub(r'\n{3,}', '\n\n', teks)
    
    # 5. Hapus karakter kontrol non-printable
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
    # PERBAIKAN PENTING: Bersihkan URL dari pelacak (?utm_source=...) agar tidak dicurigai bot
    clean_url = url.split('?')[0]
    
    metode_list = [
        ("Jina Reader API",   _metode_jina),
        ("Direct Request",    _metode_direct),
        ("Google Cache",      _metode_google_cache),
    ]

    for nama_metode, fungsi in metode_list:
        print(f"   -> [Mencoba] {nama_metode}...")
        
        # Gunakan clean_url yang sudah bersih dari pelacak
        hasil = fungsi(clean_url)

        if hasil is None:
            print(f"   -> [Gagal] {nama_metode}: Tidak ada respons.")
            continue

        judul = hasil.get("judul", "")
        teks  = hasil.get("teks", "")

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
            "status":  "sukses",
            "metode":  nama_metode,
            "url":     clean_url, # Simpan URL bersih di database BPS
            "judul":   judul or "Judul diekstrak AI",
            "tanggal": "Diekstrak otomatis oleh AI",
            "teks":    teks_bersih
        }

    # Semua metode gagal
    return {
        "status": "error",
        "pesan": (
            "Semua metode scraping gagal. "
            "Situs ini diproteksi sangat ketat (Cloudflare Enterprise / Login Required). "
            "Coba salin teks artikel secara manual."
        )
    }