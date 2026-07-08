# File: radar/scan_manager.py
"""
Modul Background Job Manager untuk SI-PENA RADAR.

Menjaga proses SCAN tetap berjalan di background thread, sehingga tidak ter-cancel 
otomatis oleh Streamlit saat user berinteraksi dengan antarmuka (misal: pindah tab). 
Progress dan hasil disimpan di registry global yang thread-safe.
"""
import threading
import uuid
import time

_lock = threading.Lock()
_JOBS: dict[str, dict] = {}


def buat_job() -> str:
    """Buat entry job baru, return job_id unik. Sekalian housekeeping job lama."""
    _bersihkan_job_lama()
    job_id = str(uuid.uuid4())
    with _lock:
        _JOBS[job_id] = {
            "status": "berjalan",     # berjalan | selesai | error
            "log": [],
            "hasil": None,
            "pesan_error": None,
            "dibuat_pada": time.time(),
        }
    return job_id


def tambah_log(job_id: str, pesan: str):
    """Callback thread-safe untuk menambah baris log ke job tertentu."""
    with _lock:
        if job_id in _JOBS:
            _JOBS[job_id]["log"].append(pesan)


def set_selesai(job_id: str, hasil):
    with _lock:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "selesai"
            _JOBS[job_id]["hasil"] = hasil


def set_error(job_id: str, pesan_error: str):
    with _lock:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["pesan_error"] = pesan_error


def ambil_job(job_id: str) -> dict | None:
    """Return SALINAN data job (bukan referensi langsung) supaya aman dibaca di luar lock."""
    with _lock:
        if job_id not in _JOBS:
            return None
        job = _JOBS[job_id]
        return {
            "status": job["status"],
            "log": list(job["log"]),
            "hasil": job["hasil"],
            "pesan_error": job["pesan_error"],
        }


def hapus_job(job_id: str):
    with _lock:
        _JOBS.pop(job_id, None)


def _bersihkan_job_lama(maks_umur_detik: int = 3600):
    """Housekeeping: buang job yang sudah lebih dari 1 jam, cegah memory leak di server."""
    sekarang = time.time()
    with _lock:
        kadaluarsa = [
            jid for jid, job in _JOBS.items()
            if sekarang - job["dibuat_pada"] > maks_umur_detik
        ]
        for jid in kadaluarsa:
            _JOBS.pop(jid, None)