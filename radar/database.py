# File: radar/database.py
"""
Modul C: SQLite State Tracker
Mengelola database untuk tracking artikel dan status kategori.
Mencegah duplikasi berita antar sesi dan antar kategori.
"""

import sqlite3
import os
from datetime import datetime

# FIX #2: satu sumber kebenaran untuk ambang skor minimum, bukan hardcode lagi
from .config import DEFAULT_MIN_SKOR

# Path database — selalu di root folder proyek
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sifeno_tracker.db")


def get_connection() -> sqlite3.Connection:
    """Membuat koneksi ke database SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inisialisasi_database():
    """
    Membuat semua tabel jika belum ada.
    Aman untuk dipanggil berkali-kali (idempotent).
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS riwayat_artikel (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            url_berita       TEXT    UNIQUE NOT NULL,
            judul_berita     TEXT,
            kategori_pdrb    TEXT,
            triwulan         TEXT,
            skor_relevansi   INTEGER DEFAULT 0,
            alasan_ai        TEXT,
            ada_data_angka   INTEGER DEFAULT 0,
            ada_perbandingan INTEGER DEFAULT 0,
            relevan_kategori INTEGER DEFAULT 0,
            status           TEXT    DEFAULT 'ditemukan',
            tanggal_ditemukan DATETIME,
            tanggal_diekstrak DATETIME
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS status_kategori (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            kategori_pdrb         TEXT    NOT NULL,
            triwulan              TEXT    NOT NULL,
            status_berita         TEXT    DEFAULT 'belum_scan',
            jumlah_artikel_valid  INTEGER DEFAULT 0,
            terakhir_scan         DATETIME,
            UNIQUE(kategori_pdrb, triwulan)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hasil_ekstraksi (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            url_berita            TEXT    UNIQUE NOT NULL,
            tema_topik            TEXT,
            judul_dan_tanggal     TEXT,
            sumber_dan_link       TEXT,
            ringkasan_fenomena    TEXT,
            data_angka            TEXT,
            kutipan_tokoh         TEXT,
            lokasi_spesifik       TEXT,
            intervensi_pemerintah TEXT,
            periode_kejadian      TEXT,
            kata_kunci            TEXT,
            sentimen_dampak       TEXT,
            kategori_perbandingan TEXT,
            waktu_ekstraksi       TEXT,
            model_ai              TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("✅ [Database] Inisialisasi selesai.")


# ─── FUNGSI ARTIKEL ────────────────────────────────────────────────────────────

def cek_url_sudah_ada(url: str) -> dict | None:
    """
    Cek apakah URL sudah pernah masuk database.
    Return: dict info artikel jika ada, None jika belum.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM riwayat_artikel WHERE url_berita = ?", (url,))
    baris = cursor.fetchone()
    conn.close()
    return dict(baris) if baris else None


def simpan_artikel(
    url: str,
    judul: str,
    kategori: str,
    triwulan: str,
    skor: int,
    alasan: str,
    ada_data_angka: bool,
    ada_perbandingan: bool,
    relevan_kategori: bool,
    layak_ekstrak: bool
):
    """
    Menyimpan artikel baru ke database.
    Jika URL sudah ada (diproses ulang), datanya akan di-OVERWRITE dengan hasil AI terbaru.
    """
    conn = get_connection()
    cursor = conn.cursor()
    status = "ditemukan" if layak_ekstrak else "tidak_lolos"
    try:
        cursor.execute("""
            INSERT INTO riwayat_artikel
            (url_berita, judul_berita, kategori_pdrb, triwulan,
             skor_relevansi, alasan_ai, ada_data_angka, ada_perbandingan,
             relevan_kategori, status, tanggal_ditemukan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url_berita) DO UPDATE SET
                judul_berita = excluded.judul_berita,
                kategori_pdrb = excluded.kategori_pdrb,
                triwulan = excluded.triwulan,
                skor_relevansi = excluded.skor_relevansi,
                alasan_ai = excluded.alasan_ai,
                ada_data_angka = excluded.ada_data_angka,
                ada_perbandingan = excluded.ada_perbandingan,
                relevan_kategori = excluded.relevan_kategori,
                status = excluded.status,
                tanggal_ditemukan = excluded.tanggal_ditemukan
        """, (
            url, judul, kategori, triwulan,
            skor, alasan,
            int(ada_data_angka), int(ada_perbandingan), int(relevan_kategori),
            status, datetime.now().isoformat()
        ))
        conn.commit()
    finally:
        conn.close()


def tandai_artikel_diekstrak(url: str):
    """Mengubah status artikel menjadi 'diekstrak' saat staf mengekstraknya."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE riwayat_artikel
        SET status = 'diekstrak', tanggal_diekstrak = ?
        WHERE url_berita = ?
    """, (datetime.now().isoformat(), url))
    conn.commit()
    conn.close()


def tandai_artikel_ditolak(url: str):
    """Mengubah status artikel menjadi 'ditolak_user' agar tidak muncul lagi."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE riwayat_artikel
        SET status = 'ditolak_user'
        WHERE url_berita = ?
    """, (url,))
    conn.commit()
    conn.close()


def ambil_artikel_valid(
    kategori: str,
    triwulan: str,
    min_skor: int = DEFAULT_MIN_SKOR,   # FIX #2: parameter baru, bukan hardcode 6 lagi
) -> list[dict]:
    """
    Ambil semua artikel yang lolos seleksi untuk kategori & triwulan tertentu.
    Hanya yang status = 'ditemukan' (belum diekstrak, belum ditolak) DAN
    skor_relevansi >= min_skor.

    FIX #2: dulu ambang skor di query ini di-hardcode `>= 6` secara independen
    dari slider "Skor Minimum Lolos" di UI. Sekarang menerima parameter
    `min_skor` (default ke `DEFAULT_MIN_SKOR` dari config.py) supaya staf bisa
    menyaring ulang tampilan antrean sesuai ambang yang sedang dipilih di UI,
    tanpa perlu scan ulang.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM riwayat_artikel
        WHERE kategori_pdrb = ?
          AND triwulan      = ?
          AND status        = 'ditemukan'
          AND skor_relevansi >= ?
        ORDER BY skor_relevansi DESC
    """, (kategori, triwulan, min_skor))
    hasil = [dict(b) for b in cursor.fetchall()]
    conn.close()
    return hasil


def filter_url_baru(list_url: list[str], paksa_proses_ulang: bool = False) -> tuple[list[str], list[dict]]:
    """
    Memisahkan URL menjadi dua kelompok:
    - url_baru: lolos untuk di-scrape (baru, atau dipaksa ulang)
    - daftar_warning: peringatan artikel sudah diekstrak
    """
    url_baru = []
    daftar_warning = []

    for url in list_url:
        info = cek_url_sudah_ada(url)

        if info is None:
            url_baru.append(url)

        elif info["status"] == "diekstrak":
            tanggal = info.get('tanggal_diekstrak', 'Tanggal tidak diketahui')
            tanggal_rapi = tanggal[:10] if tanggal else ""
            daftar_warning.append({
                "url": url,
                "judul": info["judul_berita"],
                "kategori_lama": info["kategori_pdrb"],
                "tanggal_ekstrak": tanggal_rapi,
                "pesan": f"⚠️ Sudah diekstrak untuk '{info['kategori_pdrb']}' pada {tanggal_rapi}"
            })

        elif info["status"] == "ditemukan":
            pass

        elif info["status"] in ["ditolak_user", "tidak_lolos"]:
            if paksa_proses_ulang:
                print(f"   🔄 Memproses ulang URL yang pernah gagal/ditolak: {url}")
                url_baru.append(url)
            else:
                pass

    return url_baru, daftar_warning


# ─── FUNGSI STATUS KATEGORI ────────────────────────────────────────────────────

def update_status_kategori(kategori: str, triwulan: str, jumlah_valid: int):
    """Update atau insert status kategori setelah scan selesai."""
    conn = get_connection()
    cursor = conn.cursor()
    status = "ada_berita" if jumlah_valid > 0 else "tidak_ada_berita"
    cursor.execute("""
        INSERT INTO status_kategori
            (kategori_pdrb, triwulan, status_berita, jumlah_artikel_valid, terakhir_scan)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(kategori_pdrb, triwulan)
        DO UPDATE SET
            status_berita        = excluded.status_berita,
            jumlah_artikel_valid = excluded.jumlah_artikel_valid,
            terakhir_scan        = excluded.terakhir_scan
    """, (kategori, triwulan, status, jumlah_valid, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def ambil_semua_status_kategori(triwulan: str) -> list[dict]:
    """Ambil ringkasan status semua kategori untuk satu triwulan (untuk Batch Dashboard)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM status_kategori
        WHERE triwulan = ?
        ORDER BY kategori_pdrb
    """, (triwulan,))
    hasil = [dict(b) for b in cursor.fetchall()]
    conn.close()
    return hasil


# ─── FUNGSI HASIL EKSTRAKSI (BARU) ────────────────────────────────────────────

def simpan_hasil_ekstraksi(url: str, json_final: dict):
    """
    Simpan 12 variabel hasil ekstraksi ke tabel hasil_ekstraksi.
    Dipanggil saat user menekan 'Finalisasi' di Tab 2.
    Jika URL sudah ada, data akan di-overwrite (UPSERT).
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO hasil_ekstraksi
            (url_berita, tema_topik, judul_dan_tanggal, sumber_dan_link,
             ringkasan_fenomena, data_angka, kutipan_tokoh, lokasi_spesifik,
             intervensi_pemerintah, periode_kejadian, kata_kunci,
             sentimen_dampak, kategori_perbandingan, waktu_ekstraksi, model_ai)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url_berita) DO UPDATE SET
                tema_topik            = excluded.tema_topik,
                judul_dan_tanggal     = excluded.judul_dan_tanggal,
                sumber_dan_link       = excluded.sumber_dan_link,
                ringkasan_fenomena    = excluded.ringkasan_fenomena,
                data_angka            = excluded.data_angka,
                kutipan_tokoh         = excluded.kutipan_tokoh,
                lokasi_spesifik       = excluded.lokasi_spesifik,
                intervensi_pemerintah = excluded.intervensi_pemerintah,
                periode_kejadian      = excluded.periode_kejadian,
                kata_kunci            = excluded.kata_kunci,
                sentimen_dampak       = excluded.sentimen_dampak,
                kategori_perbandingan = excluded.kategori_perbandingan,
                waktu_ekstraksi       = excluded.waktu_ekstraksi,
                model_ai              = excluded.model_ai
        """, (
            url,
            str(json_final.get("tema_topik", "")),
            str(json_final.get("judul_dan_tanggal", "")),
            str(json_final.get("sumber_dan_link", "")),
            str(json_final.get("ringkasan_fenomena", "")),
            str(json_final.get("data_angka", "")),
            str(json_final.get("kutipan_tokoh", "")),
            str(json_final.get("lokasi_spesifik", "")),
            str(json_final.get("intervensi_pemerintah", "")),
            str(json_final.get("periode_kejadian", "")),
            str(json_final.get("kata_kunci", "")),
            str(json_final.get("sentimen_dampak", "")),
            str(json_final.get("kategori_perbandingan", "")),
            str(json_final.get("_waktu_ekstraksi", "")),
            str(json_final.get("_model_digunakan", "")),
        ))
        conn.commit()
    except Exception as e:
        print(f"⚠️ [DB] Gagal simpan hasil ekstraksi untuk {url[:50]}: {e}")
    finally:
        conn.close()