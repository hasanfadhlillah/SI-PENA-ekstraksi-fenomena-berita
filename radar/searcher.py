# File: radar/searcher.py
"""
Modul B: Multi-Source Search Engine Integrator
Sumber: DuckDuckGo News + Google News RSS + DuckDuckGo Web
"""

import time
import re
import base64
import requests
import feedparser
from datetime import datetime
from ddgs import DDGS


# ─── HELPER ────────────────────────────────────────────────────────────────────

def _normalisasi_url(url: str) -> str:
    """Hapus parameter tracking agar deduplikasi lebih akurat."""
    for param in ["?utm_source", "?ref=", "&utm", "?from=", "#"]:
        if param in url:
            url = url.split(param)[0]
    return url.rstrip("/")


def _resolve_google_news_url(google_url: str) -> str:
    """
    FUNGSI KUNCI: Decode/resolve URL redirect Google News RSS ke URL artikel asli.
    Google News RSS membungkus URL dalam format:
    https://news.google.com/rss/articles/CBMi[base64_encoded_data]
    
    Strategi:
    1. Coba decode base64 dari path URL (cepat, tanpa request)
    2. Jika gagal, follow redirect HTTP (lebih lambat tapi reliable)
    """
    if not google_url or "news.google.com" not in google_url:
        return google_url  # Bukan URL Google, kembalikan apa adanya

    # STRATEGI 1: Follow HTTP redirect (paling reliable)
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(google_url, headers=headers, timeout=10, allow_redirects=True)
        final_url = resp.url
        
        # Pastikan bukan halaman Google sendiri
        if "google.com" not in final_url and final_url != google_url:
            return _normalisasi_url(final_url)
    except Exception:
        pass

    # STRATEGI 2: Coba decode dari encoded path (tanpa request, cepat)
    try:
        # Format: /rss/articles/[encoded] atau /articles/[encoded]
        match = re.search(r'/articles/([A-Za-z0-9_-]+)', google_url)
        if match:
            encoded = match.group(1)
            # Tambahkan padding base64 jika perlu
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding
            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8", errors="ignore")
            # Cari URL di dalam decoded string
            url_match = re.search(r'https?://[^\s\x00-\x1f]+', decoded)
            if url_match:
                return _normalisasi_url(url_match.group(0))
    except Exception:
        pass

    # Jika semua gagal, kembalikan URL Google aslinya
    return google_url


def _parse_tanggal(tanggal_str: str) -> str:
    """Normalisasi berbagai format tanggal ke YYYY-MM-DD."""
    if not tanggal_str:
        return ""
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d"
    ]:
        try:
            # Potong string ke panjang format + buffer
            return datetime.strptime(tanggal_str[:35], fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    tahun = re.search(r'\d{4}', tanggal_str)
    return tahun.group() if tahun else tanggal_str[:10]


def _dalam_rentang_tanggal(tanggal_artikel: str, mulai: str, selesai: str) -> bool:
    """Cek apakah tanggal artikel masuk dalam rentang yang diminta."""
    if not tanggal_artikel or len(tanggal_artikel) < 10:
        return True
    try:
        dt         = datetime.strptime(tanggal_artikel[:10], "%Y-%m-%d")
        dt_mulai   = datetime.strptime(mulai,   "%Y-%m-%d")
        dt_selesai = datetime.strptime(selesai, "%Y-%m-%d")
        return dt_mulai <= dt <= dt_selesai
    except Exception:
        return True


def _deduplikasi(list_artikel: list[dict]) -> list[dict]:
    """Hapus duplikat berdasarkan URL."""
    url_seen = set()
    hasil = []
    for item in list_artikel:
        url = item.get("url", "")
        if url and url not in url_seen:
            url_seen.add(url)
            hasil.append(item)
    return hasil

def _deduplikasi_judul(list_artikel: list[dict]) -> list[dict]:
    """
    Hapus artikel dengan judul yang sangat mirip (sindikasi berita).
    Dua judul dianggap duplikat jika 80%+ kata-katanya sama.
    """
    def _normalize(s):
        return set(re.sub(r'[^\w\s]', '', s.lower()).split())
    
    hasil = []
    judul_seen = []
    
    for item in list_artikel:
        judul = item.get("judul", "")
        kata_judul = _normalize(judul)
        
        is_duplikat = False
        for kata_lama in judul_seen:
            if len(kata_judul) == 0 or len(kata_lama) == 0:
                continue
            irisan = len(kata_judul & kata_lama)
            gabungan = len(kata_judul | kata_lama)
            if irisan / gabungan > 0.8:  # Jaccard similarity > 80%
                is_duplikat = True
                break
        
        if not is_duplikat:
            judul_seen.append(kata_judul)
            hasil.append(item)
    
    return hasil

def _buang_homepage(list_artikel: list[dict], callback_log=None) -> list[dict]:
    """Filter homepage + URL Google News yang belum ter-resolve."""
    hasil = []
    for item in list_artikel:
        url = item.get("url", "")
        if not url:
            continue

        # Buang URL Google News yang belum ter-resolve ───
        if "news.google.com" in url:
            pesan_gagal = f"      [Filter] Buang URL Google belum ter-resolve: {url[:60]}"
            print(pesan_gagal)
            if callback_log: callback_log(pesan_gagal)
            continue

        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path   = parsed.path.strip("/")
            if len(path) >= 10:
                hasil.append(item)
            else:
                pesan_hp = f"      [Filter] Buang homepage: {url}"
                print(pesan_hp)
                if callback_log: callback_log(pesan_hp)
        except Exception:
            hasil.append(item)
    return hasil


# ─── SUMBER 1: DUCKDUCKGO NEWS ─────────────────────────────────────────────────

def cari_duckduckgo_news(
    keywords: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    max_per_keyword: int = 8,
    callback_log=None 
) -> list[dict]:
    """Sumber 1: DuckDuckGo News. Gratis unlimited."""
    hasil = []
    selisih_hari = (
        datetime.strptime(tanggal_selesai, "%Y-%m-%d") -
        datetime.strptime(tanggal_mulai,   "%Y-%m-%d")
    ).days
    timelimit = "d" if selisih_hari <= 7 else "w" if selisih_hari <= 30 else "m"

    try:
        with DDGS() as ddgs:
            for keyword in keywords:
                pesan_log = f"      [DDG News] '{keyword}'..."
                print(pesan_log)
                if callback_log: callback_log(pesan_log)
                
                try:
                    berita = list(ddgs.news(keyword, max_results=max_per_keyword, timelimit=timelimit))
                    for item in berita:
                        url = _normalisasi_url(item.get("url", ""))
                        tgl = _parse_tanggal(item.get("date", ""))
                        if url and _dalam_rentang_tanggal(tgl, tanggal_mulai, tanggal_selesai):
                            hasil.append({
                                "url":           url,
                                "judul":         item.get("title", ""),
                                "tanggal":       tgl,
                                "sumber":        item.get("source", ""),
                                "sumber_search": "DuckDuckGo News"
                            })
                    time.sleep(1.0)
                except Exception as e:
                    pesan_err = f"      [DDG News] Error '{keyword}': {e}"
                    print(pesan_err)
                    if callback_log: callback_log(pesan_err)
                    time.sleep(3)
                    continue
    except Exception as e:
        print(f"      [DDG News] Gagal inisialisasi: {e}")

    print(f"   → DuckDuckGo News: {len(hasil)} artikel")
    return hasil


# ─── SUMBER 2: GOOGLE NEWS RSS ─────────────────────────────────────────────────

def cari_google_news_rss(
    keywords: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    max_per_keyword: int = 10,
    callback_log=None 
) -> list[dict]:
    """
    Sumber 2: Google News RSS Feed. 100% GRATIS UNLIMITED.
    DIPERBAIKI: Resolve redirect URL Google ke URL artikel asli.
    """
    hasil = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    for keyword in keywords:
        pesan_log = f"      [Google RSS] '{keyword}'..."
        print(pesan_log)
        if callback_log: callback_log(pesan_log)
        
        try:
            keyword_encoded = requests.utils.quote(keyword)
            rss_url = (
                f"https://news.google.com/rss/search"
                f"?q={keyword_encoded}"
                f"&hl=id&gl=ID&ceid=ID:id"
            )

            resp = requests.get(rss_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"      [Google RSS] HTTP {resp.status_code}")
                continue

            feed  = feedparser.parse(resp.content)
            count = 0

            for entry in feed.entries:
                if count >= max_per_keyword:
                    break

                # ─── PERBAIKAN UTAMA: Resolve URL Google ke URL artikel asli ───
                url_google = entry.get("link", "")
                if not url_google:
                    continue

                # Follow redirect untuk dapat URL artikel asli
                url_asli = _resolve_google_news_url(url_google)
                url = _normalisasi_url(url_asli)

                judul = entry.get("title", "")
                # Bersihkan " - Nama Media" dari judul RSS Google
                if " - " in judul:
                    judul = judul.rsplit(" - ", 1)[0].strip()

                tgl = _parse_tanggal(entry.get("published", ""))

                if url and _dalam_rentang_tanggal(tgl, tanggal_mulai, tanggal_selesai):
                    hasil.append({
                        "url":           url,
                        "judul":         judul,
                        "tanggal":       tgl,
                        "sumber":        entry.get("source", {}).get("title", ""),
                        "sumber_search": "Google News RSS"
                    })
                    count += 1

            time.sleep(0.5)

        except Exception as e:
            pesan_err = f"      [Google RSS] Error: {e}"
            print(pesan_err)
            if callback_log: callback_log(pesan_err)
            time.sleep(1)
            continue

    print(f"   → Google News RSS: {len(hasil)} artikel")
    return hasil


# ─── SUMBER 3: DUCKDUCKGO WEB (FALLBACK) ──────────────────────────────────────

def cari_duckduckgo_web(
    keywords: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    max_per_keyword: int = 5,
    callback_log=None 
) -> list[dict]:
    """Sumber 3: DDG Web Search. Fallback jika News+RSS < 5 artikel."""
    hasil = []
    tahun = tanggal_mulai[:4]

    try:
        with DDGS() as ddgs:
            for keyword in keywords[:3]:
                keyword_tahun = f"{keyword} {tahun}"
                pesan_log = f"      [DDG Web] '{keyword_tahun}'..."
                print(pesan_log)
                if callback_log: callback_log(pesan_log)
                
                try:
                    web_results = list(ddgs.text(keyword_tahun, max_results=max_per_keyword))
                    for item in web_results:
                        url = _normalisasi_url(item.get("href", ""))
                        if url:
                            hasil.append({
                                "url":           url,
                                "judul":         item.get("title", ""),
                                "tanggal":       "",
                                "sumber":        "",
                                "sumber_search": "DuckDuckGo Web"
                            })
                    time.sleep(1)
                except Exception as e:
                    pesan_err = f"      [DDG Web] Error: {e}"
                    print(pesan_err)
                    if callback_log: callback_log(pesan_err)
                    continue
    except Exception as e:
        print(f"      [DDG Web] Gagal inisialisasi: {e}")

    print(f"   → DuckDuckGo Web: {len(hasil)} artikel")
    return hasil


# ─── FUNGSI UTAMA ──────────────────────────────────────────────────────────────

def cari_berita_multi_sumber(
    keywords_per_wilayah: dict,
    wilayah: str,
    tanggal_mulai: str,
    tanggal_selesai: str,
    callback_log=None 
) -> list[dict]:
    """Fungsi utama Modul B — 100% Gratis Unlimited."""
    keywords = keywords_per_wilayah.get(wilayah, [])
    if not keywords:
        return []

    tampilan = "KOTA MAGELANG" if wilayah == "magelang" else wilayah.upper()
    pesan_header = f"📡 Mencari di wilayah: {tampilan} ({len(keywords)} keyword) \n📅 Rentang: {tanggal_mulai} s.d. {tanggal_selesai}"
    print(f"\n   {pesan_header}")
    if callback_log: callback_log(pesan_header)

    hasil_ddg = cari_duckduckgo_news(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)
    hasil_rss = cari_google_news_rss(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)

    # Lapis 1: Hapus URL yang persis sama
    gabungan = _deduplikasi(hasil_ddg + hasil_rss)
    
    # Lapis 2: Hapus artikel yang judulnya 80% mirip (DIPASANG DI SINI)
    gabungan = _deduplikasi_judul(gabungan)

    # Lapis 3: Buang homepage sebelum masuk scraping
    gabungan = _buang_homepage(gabungan, callback_log=callback_log)

    if len(gabungan) < 5:
        pesan_fallback = f"⚠️ Gabungan DDG+RSS hanya {len(gabungan)} → aktifkan DDG Web..."
        print(f"   {pesan_fallback}")
        if callback_log: callback_log(pesan_fallback)
        
        hasil_web = cari_duckduckgo_web(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)
        
        # Terapkan 3 lapis filter yang sama jika Fallback Web menyala
        gabungan  = _deduplikasi(gabungan + hasil_web)
        gabungan  = _deduplikasi_judul(gabungan)
        gabungan  = _buang_homepage(gabungan, callback_log=callback_log)

    pesan_akhir = f"📦 Total unik artikel (filter URL, Judul Mirip & Homepage): {len(gabungan)}"
    print(f"\n   {pesan_akhir}")
    if callback_log: callback_log(pesan_akhir)
    
    return gabungan