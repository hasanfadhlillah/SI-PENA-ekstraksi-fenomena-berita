# File: radar/logger_config.py
"""
Konfigurasi logging terpusat untuk SI-PENA RADAR.

Semua modul WAJIB mengambil logger dari sini via `get_logger(__name__)`,
bukan membuat logger sendiri-sendiri atau memakai print() lagi, supaya
format & level konsisten di seluruh aplikasi.

Level log bisa diatur lewat environment variable LOG_LEVEL (default: INFO).
Di Hugging Face Spaces, ini bisa diset lewat menu "Settings" > "Variables and
secrets" pada Space kamu.
"""

import logging
import os
import sys

_LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_sudah_dikonfigurasi = False


def _konfigurasi_root_logger():
    """
    Konfigurasi root logger "sipena" sekali saja (idempotent), dengan
    StreamHandler ke stdout.

    Guard idempotent ini PENTING khusus untuk Streamlit: karena Streamlit
    menjalankan ULANG seluruh script setiap kali ada interaksi user (klik
    tombol, ganti slider, dll.), tanpa guard ini handler akan didaftarkan
    berkali-kali dan setiap baris log akan tercetak berulang-ulang (duplikat).
    """
    global _sudah_dikonfigurasi
    if _sudah_dikonfigurasi:
        return

    root = logging.getLogger("sipena")
    root.setLevel(_LOG_LEVEL)

    if not root.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)

    root.propagate = False
    _sudah_dikonfigurasi = True


def get_logger(nama_modul: str) -> logging.Logger:
    """
    Ambil logger untuk sebuah modul, dengan namespace "sipena.<nama_modul>".

    Contoh pemakaian di tiap file:
        from radar.logger_config import get_logger
        logger = get_logger(__name__)
        logger.debug("Detail teknis, hanya terlihat kalau LOG_LEVEL=DEBUG")
        logger.info("Pesan info normal")
        logger.warning("Pesan peringatan — perlu perhatian tapi bukan error")
        logger.error("Pesan error — sesuatu gagal")
    """
    _konfigurasi_root_logger()
    return logging.getLogger(f"sipena.{nama_modul}")