# File: radar/query_expander.py
"""
Modul A: Semantic Query Expander
Mengubah nomenklatur kaku PDRB menjadi keyword jurnalistik natural.
Menggunakan static dictionary (cepat) + AI fallback (untuk kategori tidak dikenal).
Mendukung edit keyword dinamis via keywords.json (Tab 5 di app.py).
"""

import json
import os
import re
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

from .logger_config import get_logger

logger = get_logger(__name__)

load_dotenv()

_KEYWORDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.json")


def _load_keywords() -> dict:
    """
    Load keyword dictionary.
    Membaca dari keywords.json. Jika file tidak ada/rusak, kembalikan dictionary kosong.
    """
    if os.path.exists(_KEYWORDS_PATH):
        try:
            with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Dipanggil SANGAT sering (tiap scan kategori) -> DEBUG
                logger.debug(f"[Keywords] Dimuat dari {_KEYWORDS_PATH}")
                return data
        except Exception as e:
            logger.error(f"[Keywords] Gagal baca keywords.json: {e}. Menggunakan dictionary kosong.")
            return {}
    return {}


def _save_keywords(data: dict):
    """
    Simpan keyword dictionary ke file keywords.json.
    Dipanggil dari Tab 5 (Kelola Keyword) di app.py.
    """
    try:
        with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[Keywords] Disimpan ke {_KEYWORDS_PATH}")
    except Exception as e:
        raise IOError(f"Gagal menyimpan keywords: {e}")


_POLA_TAHUN = re.compile(r'\b20\d{2}\b')

def _perbarui_tahun_keyword(keyword: str) -> str:
    """Ganti angka tahun berformat 20XX di dalam sebuah keyword dengan tahun berjalan."""
    return _POLA_TAHUN.sub(str(datetime.now().year), keyword)


def _perbarui_tahun_keywords_dict(keywords: dict) -> dict:
    """Terapkan _perbarui_tahun_keyword() ke semua keyword di 3 level wilayah."""
    return {
        level: [_perbarui_tahun_keyword(kw) for kw in daftar]
        for level, daftar in keywords.items()
    }


KEYWORD_DICT = _load_keywords()

# ─── FUNGSI EXPANSION ─────────────────────────────────────────────────────────
def expand_query_dari_dict(nama_kategori: str) -> dict | None:
    """
    Cari keyword dari dictionary (JSON atau bawaan).
    Return dict {magelang, jateng, nasional} atau None jika tidak ditemukan.
    """
    kw_dict = _load_keywords()

    if nama_kategori in kw_dict:
        return _perbarui_tahun_keywords_dict(kw_dict[nama_kategori])

    nama_lower = nama_kategori.lower()
    for key, val in kw_dict.items():
        if nama_lower in key.lower() or key.lower() in nama_lower:
            return _perbarui_tahun_keywords_dict(val)

    return None

def expand_query_via_ai(nama_kategori: str, api_keys: str) -> dict:
    """
    Fallback: generate keyword menggunakan AI jika tidak ada di dictionary.
    """
    first_key = api_keys.split(",")[0].strip() if api_keys else ""
    if not first_key:
        logger.warning("Groq API Key kosong, menggunakan keyword generik.")
        return _bikin_keyword_generik(nama_kategori)

    client = Groq(api_key=first_key)
    tahun_sekarang = datetime.now().year
    prompt = f"""Kamu adalah asisten riset BPS (Badan Pusat Statistik) Indonesia.
Tugasmu: ubah kategori PDRB berikut menjadi keyword pencarian berita jurnalistik.

Kategori PDRB: "{nama_kategori}"
Lokasi fokus: KOTA Magelang, Jawa Tengah, Indonesia

Hasilkan HANYA JSON ini tanpa penjelasan:
{{
  "magelang": ["keyword 1 kota magelang", "keyword 2 kota magelang", "keyword 3 kota magelang"],
  "jateng": ["keyword 1 jawa tengah", "keyword 2 jateng", "keyword 3 jateng"],
  "nasional": ["keyword 1 indonesia", "keyword 2 nasional", "keyword 3 indonesia {tahun_sekarang}"]
}}

ATURAN PENTING:
- Gunakan bahasa wartawan lokal, BUKAN bahasa akademis BPS.
- Untuk area magelang, HARUS gunakan frasa "kota magelang", JANGAN HANYA "magelang" agar tidak tertukar dengan Kabupaten Magelang.
- Setiap level wilayah: berikan 3-4 keyword berbeda yang sering muncul di judul berita online.
- Jika menyebut tahun, HARUS pakai tahun berjalan ({tahun_sekarang}), jangan pakai tahun lain."""

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        hasil_ai = json.loads(resp.choices[0].message.content)
        hasil_ai = _perbarui_tahun_keywords_dict(hasil_ai)
        kw_data = _load_keywords()
        kw_data[nama_kategori] = hasil_ai
        _save_keywords(kw_data)
        logger.info(f"Hasil AI untuk '{nama_kategori}' berhasil disimpan ke keywords.json")
        try:
            from .backup import auto_backup_ke_hf_dataset
            auto_backup_ke_hf_dataset()
        except Exception as e_backup:
            logger.debug(f"[Keywords] Auto-backup setelah AI fallback dilewati: {e_backup}")
        return hasil_ai

    except Exception as e:
        logger.warning(f"AI Query Expansion gagal: {e}. Pakai keyword generik.")
        return _bikin_keyword_generik(nama_kategori)



def _bikin_keyword_generik(nama_kategori: str) -> dict:
    """Fungsi pembantu untuk membuat keyword darurat jika AI gagal."""
    kata = nama_kategori.lower().replace(",", "").replace("dan", "").strip()
    tahun_sekarang = datetime.now().year
    return {
        "magelang": [f"{kata} kota magelang", f"kondisi {kata} kota magelang"],
        "jateng":   [f"{kata} jawa tengah", f"{kata} jateng"],
        "nasional": [f"{kata} indonesia {tahun_sekarang}", f"{kata} nasional"],
    }


def dapatkan_keywords(nama_kategori: str, api_key: str) -> dict:
    """
    Fungsi utama Modul A.
    Coba dict dulu, fallback ke AI jika tidak ditemukan.
    """
    hasil = expand_query_dari_dict(nama_kategori)
    if hasil:
        logger.debug(f"Keyword dari dictionary ({len(hasil['magelang'])} keyword level Kota)")
        return hasil

    logger.info(f"Kategori '{nama_kategori}' tidak ada di dictionary, generate via AI...")
    return expand_query_via_ai(nama_kategori, api_key)