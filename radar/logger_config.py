# File: radar/logger_config.py
"""
Konfigurasi logging terpusat untuk SI-PENA RADAR.
Semua modul WAJIB mengambil logger dari sini via `get_logger(__name__)`,
bukan membuat logger sendiri-sendiri atau memakai print() lagi, supaya
format & level konsisten di seluruh aplikasi.
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
    Konfigurasi root logger "sipena" sekali saja (idempotent). Guard ini
    penting untuk Streamlit, yang menjalankan ulang seluruh script tiap
    interaksi — tanpa guard, log akan tercetak duplikat berkali-kali.
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
    """Ambil logger untuk sebuah modul, dengan namespace "sipena.<nama_modul>"."""
    _konfigurasi_root_logger()
    return logging.getLogger(f"sipena.{nama_modul}")