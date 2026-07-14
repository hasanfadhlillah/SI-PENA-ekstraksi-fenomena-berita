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
import contextvars

_LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s |%(job_tag)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_sudah_dikonfigurasi = False
# Sisipkan ID job (mis. "[job:1a2b3c4d]") otomatis ke baris log via set_job_context() untuk pisahkan log multi-scan paralel di HF Spaces.
_job_context: contextvars.ContextVar[str] = contextvars.ContextVar("job_context", default="")

def set_job_context(tag: str):
    """Panggil di awal fungsi target thread background untuk menandai log dari thread ini."""
    _job_context.set(tag)

class _JobTagFilter(logging.Filter):
    def filter(self, record):
        tag = _job_context.get()
        record.job_tag = f" {tag}" if tag else ""
        return True

def _konfigurasi_root_logger():
    """Inisialisasi root logger "sipena" secara idempoten untuk mencegah pencetakan log duplikat akibat rerun Streamlit."""
    global _sudah_dikonfigurasi
    if _sudah_dikonfigurasi:
        return
    root = logging.getLogger("sipena")
    root.setLevel(_LOG_LEVEL)
    if not root.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
        handler.addFilter(_JobTagFilter())
        root.addHandler(handler)
    root.propagate = False
    _sudah_dikonfigurasi = True

def get_logger(nama_modul: str) -> logging.Logger:
    """Ambil logger untuk sebuah modul, dengan namespace "sipena.<nama_modul>"."""
    _konfigurasi_root_logger()
    return logging.getLogger(f"sipena.{nama_modul}")