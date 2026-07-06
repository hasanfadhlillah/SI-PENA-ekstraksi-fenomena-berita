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

from .logger_config import get_logger

logger = get_logger(__name__)


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
    """
    if not google_url or "news.google.com" not in google_url:
        return google_url

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
        if "google.com" not in final_url and final_url != google_url:
            return _normalisasi_url(final_url)
    except Exception:
        pass

    try:
        match = re.search(r'/articles/([A-Za-z0-9_-]+)', google_url)
        if match:
            encoded = match.group(1)
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding
            decoded = base64.urlsafe_b64decode(encoded).decode("utf-8", errors="ignore")
            url_match = re.search(r'https?://[^\s\x00-\x1f]+', decoded)
            if url_match:
                return _normalisasi_url(url_match.group(0))
    except Exception:
        pass

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
            return datetime.strptime(tanggal_str[:35], fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    tahun = re.search(r'\d{4}', tanggal_str)
    return tahun.group() if tahun else tanggal_str[:10]


def _hitung_timelimit_ddgs(tanggal_selesai: str) -> str | None:
    """
    Tentukan parameter `timelimit` DDGS berdasarkan seberapa jauh tanggal_selesai
    dari HARI INI — bukan dari lebar rentang tanggal_mulai-tanggal_selesai.
    """
    try:
        dt_selesai = datetime.strptime(tanggal_selesai, "%Y-%m-%d")
    except Exception:
        return None

    jarak_hari = (datetime.now() - dt_selesai).days
    if jarak_hari < 0:
        jarak_hari = 0

    if jarak_hari <= 7:
        return "d"
    elif jarak_hari <= 30:
        return "w"
    elif jarak_hari <= 90:
        return "m"
    return None


def dalam_rentang_tanggal(tanggal_artikel: str, mulai: str, selesai: str) -> tuple[bool, bool]:
    """
    Cek apakah tanggal artikel ada dalam rentang [mulai, selesai].
    Return (lolos, tanggal_pasti).
    """
    if not tanggal_artikel or len(tanggal_artikel) < 10:
        return True, False

    try:
        dt         = datetime.strptime(tanggal_artikel[:10], "%Y-%m-%d")
        dt_mulai   = datetime.strptime(mulai,   "%Y-%m-%d")
        dt_selesai = datetime.strptime(selesai, "%Y-%m-%d")
        lolos = dt_mulai <= dt <= dt_selesai
        return lolos, True
    except Exception:
        return True, False


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
            if irisan / gabungan > 0.8:
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
        if "news.google.com" in url:
            pesan_gagal = f"      [Filter] Buang URL Google belum ter-resolve: {url[:60]}"
            logger.debug(pesan_gagal)
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
                logger.debug(pesan_hp)
                if callback_log: callback_log(pesan_hp)
        except Exception:
            hasil.append(item)
    return hasil


_KATA_FUNGSI_ID = {
    "dan", "di", "ke", "dari", "yang", "untuk", "dengan", "ini", "itu", "akan",
    "pada", "tidak", "adalah", "juga", "atau", "karena", "dalam", "oleh",
    "telah", "sudah", "masih", "bisa", "dapat", "warga", "daerah", "kota",
    "desa", "kabupaten", "provinsi", "menteri", "pemerintah", "harga", "naik",
    "turun", "persen", "juta", "ribu", "hingga", "usai", "saat", "kini",
}
_KATA_FUNGSI_EN = {
    "the", "and", "for", "with", "this", "that", "will", "from", "are", "was",
    "were", "has", "have", "had", "not", "but", "you", "your", "best", "how",
    "what", "when", "where", "is", "it", "of", "in", "to", "as", "be", "by",
    "at", "an", "its", "they", "their", "more", "most", "than", "then",
    "into", "out", "up", "down", "over", "under", "about", "after", "before",
    "being", "been", "do", "does", "did", "can", "could", "would", "should",
    "must", "we", "our", "us", "he", "she", "his", "her", "if", "so", "no",
    "yes", "all", "some", "any", "each", "every", "other", "such", "only",
    "own", "same", "now", "here", "there", "who", "which", "watch", "price",
    "review", "guide", "top", "news", "today", "never", "truly", "looked",
    "years", "celebrates",
}


def _kemungkinan_berita_indonesia(judul: str) -> bool:
    """
    Heuristik cepat (BUKAN AI) untuk menebak apakah judul kemungkinan berita
    berbahasa Indonesia, berdasarkan rasio kata fungsi ID vs EN.
    """
    kata = re.findall(r"[a-zA-Z]+", judul.lower())
    if not kata:
        return True

    skor_id = sum(1 for k in kata if k in _KATA_FUNGSI_ID)
    skor_en = sum(1 for k in kata if k in _KATA_FUNGSI_EN)

    if skor_en >= 2 and skor_en > skor_id:
        return False
    return True


def _buang_bukan_bahasa_indonesia(list_artikel: list[dict], callback_log=None) -> list[dict]:
    """Buang hasil pencarian yang judulnya kemungkinan besar bukan Bahasa Indonesia."""
    hasil = []
    for item in list_artikel:
        judul = item.get("judul", "")
        if _kemungkinan_berita_indonesia(judul):
            hasil.append(item)
        else:
            pesan = f"      [Filter] Buang (kemungkinan bukan berita Indonesia): {judul[:60]}"
            logger.debug(pesan)
            if callback_log: callback_log(pesan)
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
    timelimit = _hitung_timelimit_ddgs(tanggal_selesai)

    try:
        with DDGS() as ddgs:
            for keyword in keywords:
                pesan_log = f"      [DDG News] '{keyword}'..."
                logger.debug(pesan_log)
                if callback_log: callback_log(pesan_log)

                try:
                    ddgs_kwargs = dict(
                        max_results=max_per_keyword,
                        region="id-id",
                    )
                    if timelimit:
                        ddgs_kwargs["timelimit"] = timelimit
                    berita = list(ddgs.news(keyword, **ddgs_kwargs))

                    for item in berita:
                        url = _normalisasi_url(item.get("url", ""))
                        tgl = _parse_tanggal(item.get("date", ""))
                        lolos, tanggal_pasti = dalam_rentang_tanggal(tgl, tanggal_mulai, tanggal_selesai)
                        if url and lolos:
                            hasil.append({
                                "url":           url,
                                "judul":         item.get("title", ""),
                                "tanggal":       tgl,
                                "tanggal_pasti": tanggal_pasti,
                                "sumber":        item.get("source", ""),
                                "sumber_search": "DuckDuckGo News"
                            })
                    time.sleep(1.0)
                except Exception as e:
                    pesan_err = f"      [DDG News] Error '{keyword}': {e}"
                    logger.warning(pesan_err)
                    if callback_log: callback_log(pesan_err)
                    time.sleep(3)
                    continue
    except Exception as e:
        logger.warning(f"[DDG News] Gagal inisialisasi: {e}")

    logger.info(f"DuckDuckGo News: {len(hasil)} artikel")
    return hasil


# ─── SUMBER 2: GOOGLE NEWS RSS ─────────────────────────────────────────────────
def cari_google_news_rss(
    keywords: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    max_per_keyword: int = 10,
    callback_log=None
) -> list[dict]:
    """Sumber 2: Google News RSS Feed. 100% GRATIS UNLIMITED."""
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
        logger.debug(pesan_log)
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
                logger.warning(f"[Google RSS] HTTP {resp.status_code} untuk '{keyword}'")
                continue
            feed  = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                if count >= max_per_keyword:
                    break
                url_google = entry.get("link", "")
                if not url_google:
                    continue
                url_asli = _resolve_google_news_url(url_google)
                url = _normalisasi_url(url_asli)
                judul = entry.get("title", "")
                if " - " in judul:
                    judul = judul.rsplit(" - ", 1)[0].strip()
                tgl = _parse_tanggal(entry.get("published", ""))
                lolos, tanggal_pasti = dalam_rentang_tanggal(tgl, tanggal_mulai, tanggal_selesai)
                if url and lolos:
                    hasil.append({
                        "url":           url,
                        "judul":         judul,
                        "tanggal":       tgl,
                        "tanggal_pasti": tanggal_pasti,
                        "sumber":        entry.get("source", {}).get("title", ""),
                        "sumber_search": "Google News RSS"
                    })
                    count += 1
            time.sleep(0.5)
        except Exception as e:
            pesan_err = f"      [Google RSS] Error: {e}"
            logger.warning(pesan_err)
            if callback_log: callback_log(pesan_err)
            time.sleep(1)
            continue
    logger.info(f"Google News RSS: {len(hasil)} artikel")
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
                logger.debug(pesan_log)
                if callback_log: callback_log(pesan_log)

                try:
                    web_results = list(ddgs.text(
                        keyword_tahun,
                        max_results=max_per_keyword,
                        region="id-id",
                    ))
                    for item in web_results:
                        url = _normalisasi_url(item.get("href", ""))
                        if url:
                            hasil.append({
                                "url":           url,
                                "judul":         item.get("title", ""),
                                "tanggal":       "",
                                "tanggal_pasti": False,
                                "sumber":        "",
                                "sumber_search": "DuckDuckGo Web"
                            })
                    time.sleep(1)
                except Exception as e:
                    pesan_err = f"      [DDG Web] Error: {e}"
                    logger.warning(pesan_err)
                    if callback_log: callback_log(pesan_err)
                    continue
    except Exception as e:
        logger.warning(f"[DDG Web] Gagal inisialisasi: {e}")
    logger.info(f"DuckDuckGo Web: {len(hasil)} artikel")
    return hasil


# ─── FUNGSI UTAMA ──────────────────────────────────────────────────────────────
def cari_berita_multi_sumber(
    keywords_per_wilayah: dict,
    wilayah: str,
    tanggal_mulai: str,
    tanggal_selesai: str,
    callback_log=None,
    label_tampilan: str = None
) -> list[dict]:
    """Fungsi utama Modul B — 100% Gratis Unlimited."""
    keywords = keywords_per_wilayah.get(wilayah, [])
    if not keywords:
        return []

    if label_tampilan:
        tampilan = label_tampilan.upper()
    else:
        tampilan = "KOTA MAGELANG" if wilayah == "magelang" else wilayah.upper()

    pesan_header = f"📡 Mencari di wilayah: {tampilan} ({len(keywords)} keyword) \n📅 Rentang: {tanggal_mulai} s.d. {tanggal_selesai}"
    logger.info(pesan_header.replace("\n", " | "))
    if callback_log: callback_log(pesan_header)

    hasil_ddg = cari_duckduckgo_news(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)
    hasil_rss = cari_google_news_rss(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)

    gabungan = _deduplikasi(hasil_ddg + hasil_rss)
    gabungan = _deduplikasi_judul(gabungan)
    gabungan = _buang_homepage(gabungan, callback_log=callback_log)
    gabungan = _buang_bukan_bahasa_indonesia(gabungan, callback_log=callback_log)

    if len(gabungan) < 5:
        pesan_fallback = f"⚠️ Gabungan DDG+RSS hanya {len(gabungan)} → aktifkan DDG Web..."
        logger.info(pesan_fallback)
        if callback_log: callback_log(pesan_fallback)

        hasil_web = cari_duckduckgo_web(keywords, tanggal_mulai, tanggal_selesai, callback_log=callback_log)

        gabungan  = _deduplikasi(gabungan + hasil_web)
        gabungan  = _deduplikasi_judul(gabungan)
        gabungan  = _buang_homepage(gabungan, callback_log=callback_log)
        gabungan  = _buang_bukan_bahasa_indonesia(gabungan, callback_log=callback_log)

    pesan_akhir = f"📦 Total unik artikel (filter URL, Judul Mirip, Homepage & Bahasa): {len(gabungan)}"
    logger.info(pesan_akhir)
    if callback_log: callback_log(pesan_akhir)

    return gabungan