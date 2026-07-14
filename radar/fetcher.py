# File: radar/fetcher.py
"""
Modul D: Parallel Scraping
Mengambil isi artikel dari banyak URL sekaligus menggunakan ThreadPoolExecutor.
Memanfaatkan scrape_berita() dari SI-FENO yang sudah ada.
"""
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scraper import scrape_berita

from .searcher import dalam_rentang_tanggal
from .logger_config import get_logger

logger = get_logger(__name__)


def fetch_parallel(
    list_url: list[str],
    metadata_by_url: dict | None = None,
    tanggal_mulai: str | None = None,
    tanggal_selesai: str | None = None,
    max_workers: int = 8,   # <-- BARU: naik dari 5 ke 8 biar lebih cepat
) -> list[dict]:
    if not list_url:
        return []
    metadata_by_url = metadata_by_url or {}

    # ── BARU: PRE-FILTER sebelum scraping ──────────────────────────────────
    url_final = []
    dibuang_sebelum_scrape = 0
    for url in list_url:
        meta = metadata_by_url.get(url, {})
        tgl_search = meta.get("tanggal", "")
        tgl_search_pasti = meta.get("tanggal_pasti", False)
        if tgl_search_pasti and tgl_search and tanggal_mulai and tanggal_selesai:
            lolos, _ = dalam_rentang_tanggal(tgl_search, tanggal_mulai, tanggal_selesai)
            if not lolos:
                dibuang_sebelum_scrape += 1
                continue
        url_final.append(url)

    if dibuang_sebelum_scrape:
        logger.info(f"🗓️ Pre-filter: {dibuang_sebelum_scrape} URL dibuang SEBELUM scraping (tanggal search sudah pasti di luar rentang).")

    if not url_final:
        return []

    logger.info(f"Scraping {len(url_final)} URL secara paralel (max {max_workers} thread)...")
    hasil_semua = []
    gagal = 0
    dibuang_tanggal = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(scrape_berita, url): url
            for url in url_final   # <-- diganti dari list_url
        }
        for future in as_completed(future_to_url):
            url  = future_to_url[future]
            meta = metadata_by_url.get(url, {})
            try:
                hasil = future.result(timeout=60)
                if hasil["status"] != "sukses" or len(hasil.get("teks", "")) <= 200:
                    logger.debug(f"Gagal/Kosong: {url[:60]}...")
                    gagal += 1
                    continue
                hasil["url_asli"] = url
                hasil["sumber"]   = meta.get("sumber", "")
                tanggal_search       = meta.get("tanggal", "")
                tanggal_search_pasti = meta.get("tanggal_pasti", False)
                tanggal_scrape       = hasil.get("tanggal", "")
                tanggal_scrape_pasti = hasil.get("tanggal_pasti_scrape", False)
                if tanggal_search_pasti and tanggal_search:
                    tanggal_final, tanggal_final_pasti = tanggal_search, True
                elif tanggal_scrape_pasti and tanggal_scrape:
                    tanggal_final, tanggal_final_pasti = tanggal_scrape, True
                elif tanggal_search:
                    tanggal_final, tanggal_final_pasti = tanggal_search, False
                else:
                    tanggal_final, tanggal_final_pasti = "", False
                judul_search = meta.get("judul", "")
                if judul_search:
                    hasil["judul"] = judul_search
                hasil["tanggal"]       = tanggal_final
                hasil["tanggal_pasti"] = tanggal_final_pasti
                if tanggal_final_pasti and tanggal_mulai and tanggal_selesai:
                    lolos, _ = dalam_rentang_tanggal(tanggal_final, tanggal_mulai, tanggal_selesai)
                    if not lolos:
                        logger.warning(
                            f"Dibuang (tanggal {tanggal_final} di luar rentang "
                            f"{tanggal_mulai} s.d. {tanggal_selesai}): {url[:60]}..."
                        )
                        dibuang_tanggal += 1
                        continue
                hasil_semua.append(hasil)
                logger.debug(f"OK: {hasil['judul'][:60]}...")
            except Exception as e:
                logger.warning(f"Exception: {url[:60]}... → {e}")
                gagal += 1
    logger.info(
        f"Scraping selesai: {len(hasil_semua)} sukses, {gagal} gagal, "
        f"{dibuang_tanggal} dibuang (di luar rentang tanggal)"
    )
    return hasil_semua