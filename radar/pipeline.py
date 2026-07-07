# File: radar/pipeline.py
"""
Pipeline Utama SI-PENA RADAR
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
from .config         import DEFAULT_MIN_SKOR
from .logger_config  import get_logger
from .backup         import auto_backup_ke_hf_dataset

logger = get_logger(__name__)

load_dotenv()

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

def _hitung_triwulan(tanggal_mulai: str) -> str:
    """
    Konversi tanggal ke label triwulan. Format: 'TW1-2026'
    """
    try:
        dt = datetime.strptime(tanggal_mulai, "%Y-%m-%d")
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Format tanggal tidak valid: '{tanggal_mulai}'. "
            f"Format yang benar adalah YYYY-MM-DD, contoh: '2026-01-01'."
        ) from e
    tw = (dt.month - 1) // 3 + 1
    return f"TW{tw}-{dt.year}"


def _jalankan_pipeline_satu_level(
    nama_kategori: str,
    keywords_dict: dict,
    level_cfg: dict,
    tanggal_mulai: str,
    tanggal_selesai: str,
    triwulan: str,
    min_skor: int = DEFAULT_MIN_SKOR,
    paksa_proses_ulang: bool = False,
    target_minimal: int = 3,
    callback_log=None,
) -> list[dict]:
    """
    Jalankan pipeline untuk 1 level wilayah.
    Return list artikel yang lolos screening.
    """
    wilayah_nama = level_cfg["nama"]
    wilayah_key  = level_cfg["key"]

    def _log(pesan: str, level: str = "info"):
        getattr(logger, level)(pesan)
        if callback_log:
            callback_log(pesan)

    logger.debug("=" * 55)
    logger.info(f"🌍 Level Wilayah: {wilayah_nama}")
    logger.debug("=" * 55)

    keyword_list = siapkan_keyword_fallback(level_cfg, keywords_dict)

    _log(f"🔍 Mencari di {wilayah_nama} ({len(keyword_list)} keyword)...")

    keywords_siap = {wilayah_key: keyword_list}

    hasil_search = cari_berita_multi_sumber(
        keywords_siap, wilayah_key, tanggal_mulai, tanggal_selesai,
        label_tampilan=wilayah_nama
    )
    if not hasil_search:
        _log(f"⚠️ 0 artikel ditemukan di {wilayah_nama}", level="warning")
        return []

    _log(f"📰 {len(hasil_search)} artikel dari search engine")

    metadata_by_url = {item["url"]: item for item in hasil_search}
    list_url = [item["url"] for item in hasil_search]
    url_baru, warnings = filter_url_baru(
        list_url, paksa_proses_ulang,
        level_saat_ini=level_cfg["level"],   # BARU
    )

    if warnings:
        _log(f"⏭️ {len(warnings)} URL dilewati (sudah pernah diproses sebelumnya)")
        for w in warnings:
            logger.debug(f"   • {w['judul'][:60]} → {w['pesan']}")

    if not url_baru:
        _log("⚠️ Semua URL sudah ada di database — dilewati", level="warning")
        return []

    _log(f"🔗 {len(url_baru)} URL baru akan diproses (dari {len(list_url)} total)")

    _log(f"📥 Scraping {len(url_baru)} artikel secara paralel...")
    artikel_scraped = fetch_parallel(
        url_baru,
        metadata_by_url=metadata_by_url,
        tanggal_mulai=tanggal_mulai,
        tanggal_selesai=tanggal_selesai,
        max_workers=8,
    )
    if not artikel_scraped:
        _log("⚠️ Semua URL gagal di-scrape", level="warning")
        return []

    _log(f"📄 {len(artikel_scraped)}/{len(url_baru)} artikel berhasil di-scrape")

    _log(f"🤖 AI screening {len(artikel_scraped)} artikel...")
    lolos, tidak_lolos = screening_batch(
        api_keys=API_KEYS_DICT,
        list_artikel=artikel_scraped,
        nama_kategori=nama_kategori,
        wilayah=wilayah_nama,
        min_skor=min_skor,
        target_minimal=target_minimal,
        callback_log=callback_log,
    )

    _log(f"✅ Screening selesai: {len(lolos)} lolos | {len(tidak_lolos)} tidak lolos")

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
            level_wilayah=level_cfg["level"],   # BARU
        )

    return lolos


def scan_kategori(
    nama_kategori: str,
    tanggal_mulai: str,
    tanggal_selesai: str,
    min_skor: int = DEFAULT_MIN_SKOR,
    aktifkan_fallback: bool = True,
    paksa_proses_ulang: bool = False,
    scan_semua_level: bool = True,
    target_minimal: int = 3,
    callback_log=None,
) -> dict:
    """
    Fungsi utama RADAR untuk scan 1 kategori PDRB.
    """
    logger.info("#" * 55)
    logger.info(f"🎯 SI-PENA RADAR — Scan Kategori: {nama_kategori}")
    logger.info(f"📅 {tanggal_mulai} s.d. {tanggal_selesai}")
    if paksa_proses_ulang:
        logger.info("🔄 MODE: Paksa Proses Ulang Aktif!")
    logger.info("#" * 55)

    def _log(pesan: str, level: str = "info"):
        getattr(logger, level)(pesan)
        if callback_log:
            callback_log(pesan)

    inisialisasi_database()
    triwulan = _hitung_triwulan(tanggal_mulai)

    _log(f"🎯 Target: {nama_kategori} | {tanggal_mulai} s.d. {tanggal_selesai}")

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
        _log(f"🌍 [Level {level_sekarang}/{len(URUTAN_FALLBACK)}] Memindai: {level_cfg['nama']}...")

        lolos = _jalankan_pipeline_satu_level(
            nama_kategori=nama_kategori,
            keywords_dict=keywords,
            level_cfg=level_cfg,
            tanggal_mulai=tanggal_mulai,
            tanggal_selesai=tanggal_selesai,
            triwulan=triwulan,
            min_skor=min_skor,
            paksa_proses_ulang=paksa_proses_ulang,
            target_minimal=target_minimal,
            callback_log=callback_log,
        )

        semua_artikel_valid.extend(lolos)

        if lolos:
            _log(
                f"✅ +{len(lolos)} artikel dari Level {level_sekarang} "
                f"({level_cfg['nama']}). Total: {len(semua_artikel_valid)}"
            )

        if not aktifkan_fallback:
            break

        if scan_semua_level:
            continue
        else:
            if len(semua_artikel_valid) >= target_minimal:
                _log(f"🎯 Target minimal {target_minimal} artikel tercapai. Berhenti di Level {level_sekarang}.")
                break

    update_status_kategori(nama_kategori, triwulan, len(semua_artikel_valid))

    auto_backup_ke_hf_dataset()

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


def batch_scan_semua_kategori(
    daftar_kategori: list[str],
    tanggal_mulai: str,
    tanggal_selesai: str,
    min_skor: int = DEFAULT_MIN_SKOR,
    paksa_proses_ulang: bool = False,
    scan_semua_level: bool = False,
    target_minimal: int = 3,
    callback_progress=None
) -> dict:
    """
    Scan semua kategori PDRB secara berurutan.
    """
    logger.info("#" * 55)
    logger.info(f"🚀 BATCH SCAN — {len(daftar_kategori)} kategori")
    logger.info("#" * 55)

    hasil_per_kategori = {}
    ada_berita = []
    tidak_ada  = []

    for i, kategori in enumerate(daftar_kategori, 1):
        logger.info(f"[{i}/{len(daftar_kategori)}] ▶ {kategori}")
        hasil = scan_kategori(
            kategori,
            tanggal_mulai,
            tanggal_selesai,
            min_skor,
            aktifkan_fallback=True,
            paksa_proses_ulang=paksa_proses_ulang,
            scan_semua_level=scan_semua_level,
            target_minimal=target_minimal,
            callback_log=None,
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