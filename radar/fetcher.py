# File: radar/fetcher.py
"""
Modul D: Parallel Scraping
Mengambil isi artikel dari banyak URL sekaligus menggunakan ThreadPoolExecutor.
Memanfaatkan scrape_berita() dari SI-FENO yang sudah ada.
"""

import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import scraper dari folder induk
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scraper import scrape_berita

# FIX #1d: import fungsi validasi rentang tanggal untuk lapis pertahanan kedua
from .searcher import dalam_rentang_tanggal


def fetch_parallel(
    list_url: list[str],
    metadata_by_url: dict | None = None,
    tanggal_mulai: str | None = None,
    tanggal_selesai: str | None = None,
    max_workers: int = 5,
) -> list[dict]:
    """
    Scraping semua URL secara paralel.

    FIX #1d: sekarang menerima `metadata_by_url` — dict {url: item_hasil_pencarian}
    yang berisi tanggal/judul ASLI dari Modul B (searcher.py), supaya tidak hilang
    begitu saja saat masuk tahap scraping seperti kode lama. Juga menerima
    `tanggal_mulai`/`tanggal_selesai` untuk memvalidasi ULANG rentang tanggal
    setelah tanggal final (gabungan pencarian + hasil scraping) diketahui.

    Return: list dict hasil scraping (hanya yang sukses & DALAM rentang tanggal).
    """
    if not list_url:
        return []

    metadata_by_url = metadata_by_url or {}

    print(f"\n   📥 Scraping {len(list_url)} URL secara paralel (max {max_workers} thread)...")
    hasil_semua = []
    gagal = 0
    dibuang_tanggal = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(scrape_berita, url): url
            for url in list_url
        }

        for future in as_completed(future_to_url):
            url  = future_to_url[future]
            meta = metadata_by_url.get(url, {})

            try:
                hasil = future.result(timeout=60)

                if hasil["status"] != "sukses" or len(hasil.get("teks", "")) <= 200:
                    print(f"      ❌ Gagal/Kosong: {url[:60]}...")
                    gagal += 1
                    continue

                hasil["url_asli"] = url

                # ═══════════════════════════════════════════════════════════
                # FIX #1d — Gabungkan metadata tanggal & judul dari hasil pencarian
                # ═══════════════════════════════════════════════════════════
                # Prioritas tanggal:
                #   1. Tanggal dari mesin pencari, JIKA sudah tervalidasi pasti
                #   2. Tanggal hasil ekstraksi HTML (dari scraper.py, fix #1c)
                #   3. Tanggal dari mesin pencari walau belum pasti
                #   4. Kosong (benar-benar tidak diketahui)
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

                # Utamakan judul dari mesin pencari (biasanya lebih relevan/bersih
                # dibanding title tag mentah hasil scrape)
                judul_search = meta.get("judul", "")
                if judul_search:
                    hasil["judul"] = judul_search

                hasil["tanggal"]       = tanggal_final
                hasil["tanggal_pasti"] = tanggal_final_pasti

                # ═══════════════════════════════════════════════════════════
                # FIX #1d — LAPIS PERTAHANAN KEDUA: validasi ulang rentang tanggal
                # ═══════════════════════════════════════════════════════════
                if tanggal_final_pasti and tanggal_mulai and tanggal_selesai:
                    lolos, _ = dalam_rentang_tanggal(tanggal_final, tanggal_mulai, tanggal_selesai)
                    if not lolos:
                        print(
                            f"      🚫 Dibuang (tanggal {tanggal_final} di luar rentang "
                            f"{tanggal_mulai} s.d. {tanggal_selesai}): {url[:60]}..."
                        )
                        dibuang_tanggal += 1
                        continue

                hasil_semua.append(hasil)
                print(f"      ✅ OK: {hasil['judul'][:60]}...")

            except Exception as e:
                print(f"      ❌ Exception: {url[:60]}... → {e}")
                gagal += 1

    print(
        f"   📊 Scraping selesai: {len(hasil_semua)} sukses, {gagal} gagal, "
        f"{dibuang_tanggal} dibuang (di luar rentang tanggal)"
    )
    return hasil_semua