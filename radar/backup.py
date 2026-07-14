# File: radar/backup.py
"""
Modul Backup & Restore untuk SI-PENA RADAR.
"""

import os
import io
import json
import sqlite3
import tempfile
from datetime import datetime

from .logger_config import get_logger
from .query_expander import _KEYWORDS_PATH
from .database import DB_PATH

logger = get_logger(__name__)

_HF_TOKEN = os.environ.get("HF_TOKEN", "")
_HF_BACKUP_REPO_ID = os.environ.get("HF_BACKUP_REPO_ID", "")

_last_backup_waktu = None
_JEDA_MINIMAL_BACKUP_DETIK = 300  # 5 menit — cegah spam commit saat batch scan panjang


def buat_backup_keywords_bytes() -> bytes:
    """Baca isi keywords.json apa adanya, untuk tombol download di UI."""
    if not os.path.exists(_KEYWORDS_PATH):
        return b"{}"
    with open(_KEYWORDS_PATH, "rb") as f:
        return f.read()


def buat_backup_database_bytes() -> bytes:
    """Menggandakan `sifeno_tracker.db` via SQLite Online Backup API untuk mencegah file corrupt pada mode WAL."""
    if not os.path.exists(DB_PATH):
        return b""

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        src = sqlite3.connect(DB_PATH, timeout=30)
        dst = sqlite3.connect(tmp_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def pulihkan_keywords_dari_upload(isi_file: bytes) -> tuple[bool, str]:
    """Memulihkan keywords.json dari file upload staf setelah memvalidasi strukturnya untuk mencegah kerusakan sistem."""
    try:
        data = json.loads(isi_file.decode("utf-8"))
    except Exception as e:
        return False, f"File bukan JSON valid: {e}"

    if not isinstance(data, dict):
        return False, "Struktur JSON tidak sesuai (harus berupa dictionary kategori)."

    for kategori, isi in data.items():
        if not isinstance(isi, dict) or not all(k in isi for k in ("magelang", "jateng", "nasional")):
            return False, (
                f"Struktur kategori '{kategori}' tidak sesuai — setiap kategori "
                f"harus punya key 'magelang', 'jateng', dan 'nasional'."
            )

    try:
        with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, f"Gagal menulis ke keywords.json: {e}"

    logger.info(f"keywords.json dipulihkan dari file upload ({len(data)} kategori).")
    return True, f"Berhasil! {len(data)} kategori dipulihkan ke keywords.json."


def auto_backup_ke_hf_dataset():
    """Membatasi jeda minimal 5 menit antar-backup untuk mencegah commit berlebihan ke HF Dataset selama batch scan."""
    global _last_backup_waktu

    if not _HF_TOKEN or not _HF_BACKUP_REPO_ID:
        logger.debug(
            "Auto-backup HF Dataset dilewati (HF_TOKEN/HF_BACKUP_REPO_ID belum diset)."
        )
        return

    sekarang = datetime.now()
    if _last_backup_waktu is not None:
        selisih_detik = (sekarang - _last_backup_waktu).total_seconds()
        if selisih_detik < _JEDA_MINIMAL_BACKUP_DETIK:
            logger.debug(
                f"Auto-backup dilewati (baru {int(selisih_detik)} detik sejak "
                f"backup terakhir, jeda minimal {_JEDA_MINIMAL_BACKUP_DETIK} detik)."
            )
            return

    try:
        from huggingface_hub import HfApi

        api = HfApi(token=_HF_TOKEN)
        timestamp = sekarang.strftime("%Y%m%d_%H%M%S")

        keywords_bytes = buat_backup_keywords_bytes()
        db_bytes = buat_backup_database_bytes()

        api.upload_file(
            path_or_fileobj=io.BytesIO(keywords_bytes),
            path_in_repo="keywords.json",
            repo_id=_HF_BACKUP_REPO_ID,
            repo_type="dataset",
            commit_message=f"Auto-backup keywords.json — {timestamp}",
        )
        if db_bytes:
            api.upload_file(
                path_or_fileobj=io.BytesIO(db_bytes),
                path_in_repo="sifeno_tracker.db",
                repo_id=_HF_BACKUP_REPO_ID,
                repo_type="dataset",
                commit_message=f"Auto-backup sifeno_tracker.db — {timestamp}",
            )
        _last_backup_waktu = sekarang
        logger.info(f"Auto-backup ke HF Dataset '{_HF_BACKUP_REPO_ID}' berhasil ({timestamp}).")
    except Exception as e:
        logger.warning(f"Auto-backup ke HF Dataset gagal (diabaikan, tidak fatal): {e}")


def auto_restore_dari_hf_dataset():
    """Unduh keyword/db dari HF Dataset hanya jika file lokal kosong/hilang (saat restart) dengan mekanisme fail-soft."""
    if not _HF_TOKEN or not _HF_BACKUP_REPO_ID:
        logger.debug(
            "Auto-restore HF Dataset dilewati (HF_TOKEN/HF_BACKUP_REPO_ID belum diset)."
        )
        return

    try:
        from huggingface_hub import hf_hub_download

        # ── Restore keywords.json (hanya kalau lokal kosong/tidak ada) ──
        keywords_lokal_kosong = (
            not os.path.exists(_KEYWORDS_PATH) or os.path.getsize(_KEYWORDS_PATH) <= 2
        )  # <=2 byte artinya cuma isi "{}" atau benar-benar kosong
        if keywords_lokal_kosong:
            try:
                path_terunduh = hf_hub_download(
                    repo_id=_HF_BACKUP_REPO_ID,
                    filename="keywords.json",
                    repo_type="dataset",
                    token=_HF_TOKEN,
                )
                with open(path_terunduh, "rb") as src, open(_KEYWORDS_PATH, "wb") as dst:
                    dst.write(src.read())
                logger.info(
                    "✅ Auto-restore: keywords.json berhasil dipulihkan dari HF Dataset "
                    "(terdeteksi kosong/hilang setelah restart)."
                )
            except Exception as e:
                logger.debug(f"Auto-restore keywords.json dilewati (belum ada backup?): {e}")

        # ── Restore sifeno_tracker.db (hanya kalau lokal tidak ada) ──
        db_lokal_kosong = not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0
        if db_lokal_kosong:
            try:
                path_terunduh = hf_hub_download(
                    repo_id=_HF_BACKUP_REPO_ID,
                    filename="sifeno_tracker.db",
                    repo_type="dataset",
                    token=_HF_TOKEN,
                )
                with open(path_terunduh, "rb") as src, open(DB_PATH, "wb") as dst:
                    dst.write(src.read())
                logger.info(
                    "✅ Auto-restore: sifeno_tracker.db berhasil dipulihkan dari HF Dataset "
                    "(terdeteksi hilang setelah restart)."
                )
            except Exception as e:
                logger.debug(f"Auto-restore sifeno_tracker.db dilewati (belum ada backup?): {e}")

    except Exception as e:
        logger.warning(f"Auto-restore dari HF Dataset gagal total (diabaikan): {e}")
      
        
def force_backup_ke_hf_dataset(alasan: str = "manual") -> bool:
    """Backup instan ke HF Dataset tanpa jeda 5 menit untuk aksi kritis (reset, restore, finalisasi, dll), mengembalikan True/False."""
    global _last_backup_waktu
    if not _HF_TOKEN or not _HF_BACKUP_REPO_ID:
        logger.debug("Force-backup dilewati (HF_TOKEN/HF_BACKUP_REPO_ID belum diset).")
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=_HF_TOKEN)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keywords_bytes = buat_backup_keywords_bytes()
        db_bytes = buat_backup_database_bytes()
        api.upload_file(
            path_or_fileobj=io.BytesIO(keywords_bytes),
            path_in_repo="keywords.json",
            repo_id=_HF_BACKUP_REPO_ID,
            repo_type="dataset",
            commit_message=f"Force backup ({alasan}) keywords.json — {timestamp}",
        )
        if db_bytes:
            api.upload_file(
                path_or_fileobj=io.BytesIO(db_bytes),
                path_in_repo="sifeno_tracker.db",
                repo_id=_HF_BACKUP_REPO_ID,
                repo_type="dataset",
                commit_message=f"Force backup ({alasan}) sifeno_tracker.db — {timestamp}",
            )
        _last_backup_waktu = datetime.now()
        logger.warning(f"Force-backup ({alasan}) ke HF Dataset '{_HF_BACKUP_REPO_ID}' berhasil ({timestamp}).")
        return True
    except Exception as e:
        logger.error(f"Force-backup ({alasan}) ke HF Dataset gagal: {e}")
        return False