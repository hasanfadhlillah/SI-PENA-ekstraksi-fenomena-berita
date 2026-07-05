# File: radar/pipeline.py
"""
Pipeline Utama SI-FENO RADAR
Mengintegrasikan semua modul: A (Query) → B (Search) → C (DB) → D (Scrape) → E (Screen) → F (Fallback)
"""

import os
from datetime import datetime
from dotenv import load_dotenv

from .database       import (inisialisasi_database, filter_url_baru,
                             simpan_artikel, update_status_kategori, ambil_artikel_valid)
from .query_expander import dapatkan_keywords
from .searcher       import cari_berita_multi_sumber
from .fetcher        import fetch_parallel
from .screener       import screening_batch
from .fallback       import (URUTAN_FALLBACK, dapatkan_level_fallback_berikutnya,
                             buat_pesan_anti_buntu, siapkan_keyword_fallback)

load_dotenv()

# Membaca kunci API Jamak (Pooling) memprioritaskan yang pakai "S"
GROQ_KEYS     = os.environ.get("GROQ_API_KEYS", os.environ.get("GROQ_API_KEY", ""))
GEMINI_KEYS   = os.environ.get("GEMINI_API_KEYS", os.environ.get("GEMINI_API_KEY", ""))
CEREBRAS_KEYS = os.environ.get("CEREBRAS_API_KEYS", os.environ.get("CEREBRAS_API_KEY", ""))
MISTRAL_KEYS  = os.environ.get("MISTRAL_API_KEYS", os.environ.get("MISTRAL_API_KEY", ""))

API_KEYS_DICT = {
    "groq"    : GROQ_KEYS,
    "gemini"  : GEMINI_KEYS,
    "cerebras": CEREBRAS_KEYS,
    "mistral" : MISTRAL_KEYS,
}

# ─── Helper ────────────────────────────────────────────────────────────────────
def _hitung_triwulan(tanggal_mulai: str) -> str:
    """Konversi tanggal ke label triwulan. Format: 'TW1-2026'"""
    dt = datetime.strptime(tanggal_mulai, "%Y-%m-%d")
    tw = (dt.month - 1) // 3 + 1
    return f"TW{tw}-{dt.year}"


# ─── Fungsi Inti Pipeline (1 Kategori, 1 Level Wilayah) ───────────────────────

def _jalankan_pipeline_satu_level(
    nama_kategori: str,
    keywords_dict: dict,
    level_cfg: dict,
    tanggal_mulai: str,
    tanggal_selesai: str,
    triwulan: str,
    min_skor: int = 6,
    paksa_proses_ulang: bool = False,
    callback_log=None,
) -> list[dict]:
    """
    Jalankan pipeline untuk 1 level wilayah.
    Return list artikel yang lolos screening.
    """
    wilayah_nama = level_cfg["nama"]
    wilayah_key  = level_cfg["key"]

    # ─── Helper log lokal ───
    def _log(pesan: str):
        print(pesan)
        if callback_log:
            callback_log(pesan)

    print(f"\n{'='*55}")
    print(f"  🌍 Level Wilayah: {wilayah_nama}")
    print(f"{'='*55}")

    # Terapkan fungsi replace untuk perlindungan Kota/Kabupaten Magelang
    keyword_list = siapkan_keyword_fallback(level_cfg, keywords_dict)

    _log(f"🔍 Mencari di {wilayah_nama} ({len(keyword_list)} keyword)...")

    # Bungkus ke dalam dictionary agar formatnya sesuai dengan input searcher.py
    keywords_siap = {wilayah_key: keyword_list}

    # Gerbang 2: Search
    hasil_search = cari_berita_multi_sumber(
        keywords_siap, wilayah_key, tanggal_mulai, tanggal_selesai,
        label_tampilan=wilayah_nama
    )
    if not hasil_search:
        _log(f"⚠️ 0 artikel ditemukan di {wilayah_nama}")
        return []

    _log(f"📰 {len(hasil_search)} artikel dari search engine")

    # Gerbang 3: Filter URL sudah ada di DB
    # FIX #1d: simpan dulu metadata (tanggal, judul, tanggal_pasti) dari hasil
    # pencarian SEBELUM disederhanakan jadi daftar URL — supaya tidak hilang
    # begitu saja saat masuk tahap scraping (bug lama).
    metadata_by_url = {item["url"]: item for item in hasil_search}
    list_url = [item["url"] for item in hasil_search]
    url_baru, warnings = filter_url_baru(list_url, paksa_proses_ulang)

    if warnings:
        print(f"\n  ⚠️ {len(warnings)} artikel sudah pernah diekstrak (akan dilewati):")
        for w in warnings:
            print(f"     • {w['judul'][:60]} → {w['pesan']}")

    if not url_baru:
        _log("⚠️ Semua URL sudah ada di database — dilewati")
        return []

    _log(f"🔗 {len(url_baru)} URL baru akan diproses (dari {len(list_url)} total)")

    # Gerbang 4: Parallel Scraping
    _log(f"📥 Scraping {len(url_baru)} artikel secara paralel...")
    # FIX #1d: teruskan metadata_by_url + rentang tanggal supaya fetcher.py bisa
    # melakukan validasi ulang rentang tanggal (lapis pertahanan kedua)
    artikel_scraped = fetch_parallel(
        url_baru,
        metadata_by_url=metadata_by_url,
        tanggal_mulai=tanggal_mulai,
        tanggal_selesai=tanggal_selesai,
        max_workers=5,
    )
    if not artikel_scraped:
        _log("⚠️ Semua URL gagal di-scrape")
        return []

    _log(f"📄 {len(artikel_scraped)}/{len(url_baru)} artikel berhasil di-scrape")

    # Gerbang 5: AI Screening
    _log(f"🤖 AI screening {len(artikel_scraped)} artikel...")
    lolos, tidak_lolos = screening_batch(
        api_keys=API_KEYS_DICT,
        list_artikel=artikel_scraped,
        nama_kategori=nama_kategori,
        wilayah=wilayah_nama,
        min_skor=min_skor
    )

    _log(f"✅ Screening selesai: {len(lolos)} lolos | {len(tidak_lolos)} tidak lolos")

    # Simpan semua ke database (baik yang lolos maupun tidak)
    for artikel in lolos + tidak_lolos:
        url   = artikel.get("url", "")
        judul = artikel.get("judul", "")
        simpan_artikel(
            url=url,
            judul=judul,
            kategori=nama_kategori,
            triwulan=triwulan,
            skor=artikel.get("skor_relevansi", 0),
            alasan=artikel.get("alasan_singkat", ""),
            ada_data_angka=artikel.get("ada_data_angka", False),
            ada_perbandingan=artikel.get("ada_perbandingan_waktu", False),
            relevan_kategori=artikel.get("relevan_dengan_kategori", False),
            layak_ekstrak=artikel.get("layak_ekstrak", False),
        )

    return lolos


# ─── FUNGSI UTAMA: SCAN 1 KATEGORI ────────────────────────────────────────────

def scan_kategori(
    nama_kategori: str,
    tanggal_mulai: str,
    tanggal_selesai: str,
    min_skor: int = 6,
    aktifkan_fallback: bool = True,
    paksa_proses_ulang: bool = False,
    scan_semua_level: bool = True,
    target_minimal: int = 3,
    callback_log=None,
) -> dict:
    """
    Fungsi utama RADAR untuk scan 1 kategori PDRB.
    """
    print(f"\n{'#'*55}")
    print(f"  🎯 SI-FENO RADAR — Scan Kategori")
    print(f"  📂 {nama_kategori}")
    print(f"  📅 {tanggal_mulai} s.d. {tanggal_selesai}")
    if paksa_proses_ulang:
        print(f"  🔄 MODE: Paksa Proses Ulang Aktif!")
    print(f"{'#'*55}")

    # ─── Helper log lokal ───
    def _log(pesan: str):
        print(pesan)
        if callback_log:
            callback_log(pesan)

    inisialisasi_database()
    triwulan = _hitung_triwulan(tanggal_mulai)

    _log(f"🎯 Target: {nama_kategori} | {tanggal_mulai} s.d. {tanggal_selesai}")

    # Gerbang 1: Query Expansion
    _log("🔑 Menerjemahkan kategori ke keyword pencarian...")
    keywords = dapatkan_keywords(nama_kategori, GROQ_KEYS)
    _log(
        f"✅ Keyword siap — "
        f"Kota: {len(keywords.get('magelang', []))}, "
        f"Jateng: {len(keywords.get('jateng', []))}, "
        f"Nasional: {len(keywords.get('nasional', []))}"
    )

    semua_artikel_valid = []
    level_sekarang = 0

    for level_cfg in URUTAN_FALLBACK:
        level_sekarang = level_cfg["level"]
        _log(f"\n🌍 [Level {level_sekarang}/{len(URUTAN_FALLBACK)}] Memindai: {level_cfg['nama']}...")

        lolos = _jalankan_pipeline_satu_level(
            nama_kategori=nama_kategori,
            keywords_dict=keywords,
            level_cfg=level_cfg,
            tanggal_mulai=tanggal_mulai,
            tanggal_selesai=tanggal_selesai,
            triwulan=triwulan,
            min_skor=min_skor,
            paksa_proses_ulang=paksa_proses_ulang,
            callback_log=callback_log,
        )

        semua_artikel_valid.extend(lolos)

        if lolos:
            _log(
                f"✅ +{len(lolos)} artikel dari Level {level_sekarang} "
                f"({level_cfg['nama']}). Total: {len(semua_artikel_valid)}"
            )

        # Logika lanjut/berhenti
        if not aktifkan_fallback:
            break

        if scan_semua_level:
            continue
        else:
            if len(semua_artikel_valid) >= target_minimal:
                _log(f"🎯 Target minimal {target_minimal} artikel tercapai. Berhenti di Level {level_sekarang}.")
                break

    # Update status kategori di DB
    update_status_kategori(nama_kategori, triwulan, len(semua_artikel_valid))

    if semua_artikel_valid:
        semua_artikel_valid.sort(key=lambda x: x.get("skor_relevansi", 0), reverse=True)
        return {
            "status":          "sukses",
            "kategori":        nama_kategori,
            "triwulan":        triwulan,
            "artikel_valid":   semua_artikel_valid,
            "jumlah_valid":    len(semua_artikel_valid),
            "level_ditemukan": level_sekarang,
        }
    else:
        pesan_buntu = buat_pesan_anti_buntu(nama_kategori, keywords)
        return {
            "status":        "buntu",
            "kategori":      nama_kategori,
            "triwulan":      triwulan,
            "artikel_valid": [],
            "jumlah_valid":  0,
            **pesan_buntu,
        }


# ─── FUNGSI BATCH SCAN ─────────────────────────────────────────────────────────

def batch_scan_semua_kategori(
    daftar_kategori: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    min_skor: int = 6,
    paksa_proses_ulang: bool = False,
    callback_progress=None
) -> dict:
    """
    Scan semua kategori PDRB secara berurutan.
    Batch scan tidak menggunakan callback_log per-step (terlalu verbose).
    Progress ditampilkan via callback_progress (per kategori).
    """
    print(f"\n{'#'*55}")
    print(f"  🚀 BATCH SCAN — {len(daftar_kategori)} kategori")
    print(f"{'#'*55}")

    hasil_per_kategori = {}
    ada_berita = []
    tidak_ada  = []

    for i, kategori in enumerate(daftar_kategori, 1):
        print(f"\n[{i}/{len(daftar_kategori)}] ▶ {kategori}")
        hasil = scan_kategori(
            kategori,
            tanggal_mulai,
            tanggal_selesai,
            min_skor,
            aktifkan_fallback=True,
            paksa_proses_ulang=paksa_proses_ulang,
            callback_log=None,  # Batch scan: log per-step tidak dikirim ke UI
        )
        hasil_per_kategori[kategori] = hasil

        if hasil["status"] == "sukses":
            ada_berita.append({"kategori": kategori, "jumlah": hasil["jumlah_valid"]})
        else:
            tidak_ada.append({"kategori": kategori})

        if callback_progress:
            callback_progress(kategori, i, len(daftar_kategori))

    return {
        "total_kategori"  : len(daftar_kategori),
        "ada_berita"      : ada_berita,
        "tidak_ada_berita": tidak_ada,
        "detail"          : hasil_per_kategori,
        "ringkasan": {
            "sukses"       : len(ada_berita),
            "buntu"        : len(tidak_ada),
            "persen_sukses": round(len(ada_berita) / len(daftar_kategori) * 100, 1) if daftar_kategori else 0
        }
    }