"""
Modul Background Job Manager untuk SI-PENA RADAR.
Menjalankan proses SCAN pada background thread agar tidak terputus oleh interaksi 
antarmuka Streamlit. Progress disimpan di registry global yang thread-safe dan 
mendukung beberapa scan berjalan bersamaan secara paralel.
"""
import threading
import uuid
import time
from datetime import datetime

_lock = threading.Lock()
_JOBS: dict[str, dict] = {}

def buat_job(kategori: str = "", triwulan: str = "") -> str:
    """
    Membuat entry job baru, mengembalikan `job_id`, dan memicu housekeeping memori.
    Metadata (kategori & triwulan) disimpan secara global lintas sesi Streamlit. 
    Khusus Batch Scan, `kategori_sekarang` diupdate secara LIVE setiap kali pindah 
    kategori agar sistem lock tetap presisi dan tidak terpaku pada label global.
    """
    _bersihkan_job_lama()
    job_id = str(uuid.uuid4())
    is_batch = kategori == "✨ SEMUA KATEGORI (BATCH SCAN)"
    with _lock:
        _JOBS[job_id] = {
            "status": "berjalan",     # berjalan | selesai | error
            "log": [],
            "hasil": None,
            "pesan_error": None,
            "dibuat_pada": time.time(),
            "kategori": kategori,
            "kategori_sekarang": "" if is_batch else kategori,
            "is_batch": is_batch,
            "triwulan": triwulan,
            "mulai_pukul": datetime.now().strftime("%H:%M:%S"),
        }
    return job_id

def set_kategori_sekarang(job_id: str, kategori: str):
    """
    Update kategori aktif di dalam Batch Scan tepat SEBELUM fungsi scan berjalan.
    Pengecekan di awal via `callback_mulai_kategori` ini memastikan lock per-kategori 
    aktif seketika, mencegah balapan proses (race condition) antar-sesi user.
    """
    with _lock:
        if job_id in _JOBS:
            _JOBS[job_id]["kategori_sekarang"] = kategori

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
            "kategori": job.get("kategori", ""),
            "kategori_sekarang": job.get("kategori_sekarang", ""),
            "is_batch": job.get("is_batch", False),
            "triwulan": job.get("triwulan", ""),
            "mulai_pukul": job.get("mulai_pukul", ""),
        }

def ambil_semua_job_aktif() -> list[dict]:
    """
    Mengembalikan list semua job aktif secara global (lintas sesi Streamlit).

    Kegunaan:
    1. Mencegah tabrakan scan kategori/triwulan yang sama antar-user.
    2. Menegakkan batas kuota paralel `MAKSIMAL_SCAN_BERSAMAAN`.
    3. Menampilkan banner aktivitas global untuk seluruh user (SI-PENA tidak memiliki sistem login).
    """
    with _lock:
        return [
            {
                "job_id": job_id,
                "kategori": job.get("kategori", ""),
                "kategori_sekarang": job.get("kategori_sekarang", ""),
                "is_batch": job.get("is_batch", False),
                "triwulan": job.get("triwulan", ""),
                "mulai_pukul": job.get("mulai_pukul", ""),
            }
            for job_id, job in _JOBS.items()
            if job["status"] == "berjalan"
        ]

def hapus_job(job_id: str):
    with _lock:
        _JOBS.pop(job_id, None)

def _bersihkan_job_lama(maks_umur_detik: int = 3600):
    """
    Housekeeping memori: Menghapus job selesai/error yang berusia >1 jam untuk mencegah memory leak.
    Job status 'berjalan' sengaja dilewati karena Batch Scan (51 kategori) bisa memakan 
    waktu berjam-jam; menghapusnya akan memutuskan referensi pelacakan progress thread.
    """
    sekarang = time.time()
    with _lock:
        kadaluarsa = [
            jid for jid, job in _JOBS.items()
            if job["status"] != "berjalan" and sekarang - job["dibuat_pada"] > maks_umur_detik
        ]
        for jid in kadaluarsa:
            _JOBS.pop(jid, None)