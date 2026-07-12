# File: radar/database.py
"""
Modul C: SQLite State Tracker
Mengelola database untuk tracking artikel dan status kategori.
Mencegah duplikasi berita antar sesi dan antar kategori.
"""

import sqlite3
import os
from datetime import datetime

from .config import DEFAULT_MIN_SKOR
from .logger_config import get_logger

logger = get_logger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sifeno_tracker.db")


def get_connection() -> sqlite3.Connection:
    """
    Membuat koneksi ke database SQLite.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
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
            tanggal_diekstrak DATETIME,
            level_wilayah    INTEGER DEFAULT 0,
            sumber_media     TEXT    DEFAULT '',
            teks_artikel     TEXT    DEFAULT ''
        )
    """)
    # Migrasi otomatis untuk DB lama yang belum punya kolom ini
    cursor.execute("PRAGMA table_info(riwayat_artikel)")
    kolom_ada = [baris[1] for baris in cursor.fetchall()]
    if "level_wilayah" not in kolom_ada:
        cursor.execute("ALTER TABLE riwayat_artikel ADD COLUMN level_wilayah INTEGER DEFAULT 0")
        logger.info("[Database] Migrasi: kolom 'level_wilayah' ditambahkan ke riwayat_artikel.")
    if "sumber_media" not in kolom_ada:
        cursor.execute("ALTER TABLE riwayat_artikel ADD COLUMN sumber_media TEXT DEFAULT ''")
        logger.info("[Database] Migrasi: kolom 'sumber_media' ditambahkan ke riwayat_artikel.")
    if "teks_artikel" not in kolom_ada:
        cursor.execute("ALTER TABLE riwayat_artikel ADD COLUMN teks_artikel TEXT DEFAULT ''")
        logger.info("[Database] Migrasi: kolom 'teks_artikel' ditambahkan ke riwayat_artikel.")
    
    # ── Migrasi tabel hasil_ekstraksi: tema_topik -> kategori_pdrb ──
    cursor.execute("PRAGMA table_info(hasil_ekstraksi)")
    kolom_ekstraksi_ada = [baris[1] for baris in cursor.fetchall()]
    if "kategori_pdrb" not in kolom_ekstraksi_ada:
        cursor.execute("ALTER TABLE hasil_ekstraksi ADD COLUMN kategori_pdrb TEXT DEFAULT ''")
        logger.info("[Database] Migrasi: kolom 'kategori_pdrb' ditambahkan ke hasil_ekstraksi.")
        if "tema_topik" in kolom_ekstraksi_ada:
            # Backward-compat: isi otomatis dari tema_topik lama supaya data lama
            # tidak kosong total di kolom baru (best-effort, boleh dikoreksi manual).
            cursor.execute(
                "UPDATE hasil_ekstraksi SET kategori_pdrb = tema_topik "
                "WHERE kategori_pdrb = '' OR kategori_pdrb IS NULL"
            )
            logger.info("[Database] Migrasi: kategori_pdrb dibackfill dari tema_topik lama.")

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
            kategori_pdrb         TEXT,
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
    logger.debug("[Database] Inisialisasi selesai.")


def cek_url_sudah_ada(url: str) -> dict | None:
    """Cek apakah URL sudah pernah masuk database."""
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
    layak_ekstrak: bool,
    level_wilayah: int = 0,
    sumber_media: str = "",
    teks_artikel: str = "",
):
    """Menyimpan artikel baru ke database."""
    conn = get_connection()
    cursor = conn.cursor()
    status = "ditemukan" if layak_ekstrak else "tidak_lolos"
    try:
        cursor.execute("""
            INSERT INTO riwayat_artikel
            (url_berita, judul_berita, kategori_pdrb, triwulan,
             skor_relevansi, alasan_ai, ada_data_angka, ada_perbandingan,
             relevan_kategori, status, tanggal_ditemukan, level_wilayah, sumber_media, teks_artikel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                tanggal_ditemukan = excluded.tanggal_ditemukan,
                level_wilayah = excluded.level_wilayah,
                sumber_media = excluded.sumber_media,
                teks_artikel = CASE
                    WHEN excluded.teks_artikel != '' THEN excluded.teks_artikel
                    ELSE riwayat_artikel.teks_artikel
                END
        """, (
            url, judul, kategori, triwulan,
            skor, alasan,
            int(ada_data_angka), int(ada_perbandingan), int(relevan_kategori),
            status, datetime.now().isoformat(), level_wilayah, sumber_media, teks_artikel
        ))
        conn.commit()
    finally:
        conn.close()


def ambil_konten_artikel_tersimpan(url: str) -> dict | None:
    """
    Fungsi ini menggunakan kembali judul dan teks lengkap dari hasil scrape radar screening 
    pada Tab Ekstraktor demi konsistensi data dan efisiensi proses. Langkah ini mencegah 
    scraping ulang yang tidak deterministik sekaligus menghemat waktu round-trip.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT judul_berita, teks_artikel FROM riwayat_artikel
        WHERE url_berita = ?
    """, (url,))
    baris = cursor.fetchone()
    conn.close()
    if not baris:
        return None
    judul, teks = baris["judul_berita"], baris["teks_artikel"]
    if not teks or len(teks.strip()) < 500:
        return None
    return {"judul": judul or "", "teks": teks}


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
    min_skor: int = DEFAULT_MIN_SKOR,
) -> list[dict]:
    """Ambil semua artikel yang lolos seleksi untuk kategori & triwulan tertentu."""
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


def hitung_total_artikel_valid(kategori: str, triwulan: str, min_skor: int = DEFAULT_MIN_SKOR) -> int:
    """
    Hitung TOTAL artikel valid kumulatif (status 'ditemukan' MAUPUN 'diekstrak')
    untuk kategori+triwulan tertentu, sesuai ambang skor saat ini.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM riwayat_artikel
        WHERE kategori_pdrb = ?
          AND triwulan      = ?
          AND status IN ('ditemukan', 'diekstrak')
          AND skor_relevansi >= ?
    """, (kategori, triwulan, min_skor))
    hasil = cursor.fetchone()
    conn.close()
    return hasil[0] if hasil else 0


def filter_url_baru(
    list_url: list[str],
    paksa_proses_ulang: bool = False,
    level_saat_ini: int = 0,
) -> tuple[list[str], list[dict]]:
    """
    Memisahkan URL menjadi dua kelompok:
    - url_baru: lolos untuk di-scrape (baru, dipaksa ulang, ATAU layak dinilai
      ulang karena level sekarang lebih longgar daripada level yang menghasilkan
      verdict 'tidak_lolos' sebelumnya)
    - daftar_warning: peringatan artikel yang DILEWATI, beserta ALASANNYA
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
        elif info["status"] == "tidak_lolos":
            level_sebelumnya = info.get("level_wilayah", 0) or 0
            if paksa_proses_ulang:
                logger.info(f"Memproses ulang URL yang pernah gagal: {url}")
                url_baru.append(url)
            elif level_saat_ini > level_sebelumnya:
                # Level sekarang lebih longgar -> layak dinilai ulang
                logger.info(
                    f"🔁 [Cross-Level] Menilai ulang di Level {level_saat_ini} "
                    f"(sebelumnya tidak lolos di Level {level_sebelumnya}): {url[:60]}..."
                )
                url_baru.append(url)
            else:
                daftar_warning.append({
                    "url": url,
                    "judul": info.get("judul_berita", ""),
                    "kategori_lama": info.get("kategori_pdrb", ""),
                    "tanggal_ekstrak": "",
                    "pesan": (
                        f"⏭️ Dilewati — tidak lolos screening AI di Level {level_sebelumnya} "
                        f"untuk kategori '{info.get('kategori_pdrb', '?')}'. Aktifkan toggle "
                        f"'Proses Ulang Artikel Lama' di sidebar untuk memindai ulang manual."
                    )
                })
        elif info["status"] == "ditolak_user":
            if paksa_proses_ulang:
                logger.info(f"Memproses ulang URL yang pernah ditolak user: {url}")
                url_baru.append(url)
            else:
                daftar_warning.append({
                    "url": url,
                    "judul": info.get("judul_berita", ""),
                    "kategori_lama": info.get("kategori_pdrb", ""),
                    "tanggal_ekstrak": "",
                    "pesan": (
                        f"⏭️ Dilewati — ditolak manual oleh staf untuk kategori "
                        f"'{info.get('kategori_pdrb', '?')}'. Aktifkan toggle "
                        f"'Proses Ulang Artikel Lama' di sidebar untuk memindai ulang."
                    )
                })
    return url_baru, daftar_warning


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
    """Ambil ringkasan status semua kategori untuk satu triwulan."""
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


def simpan_hasil_ekstraksi(url: str, json_final: dict) -> bool:
    """Simpan variabel hasil ekstraksi ke tabel hasil_ekstraksi."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO hasil_ekstraksi
            (url_berita, kategori_pdrb, judul_dan_tanggal, sumber_dan_link,
             ringkasan_fenomena, data_angka, kutipan_tokoh, lokasi_spesifik,
             intervensi_pemerintah, periode_kejadian, kata_kunci,
             sentimen_dampak, kategori_perbandingan, waktu_ekstraksi, model_ai)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url_berita) DO UPDATE SET
                kategori_pdrb         = excluded.kategori_pdrb,
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
            str(json_final.get("kategori_pdrb", "")),
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
        return True
    except Exception as e:
        logger.error(f"[DB] Gagal simpan hasil ekstraksi untuk {url[:50]}: {e}")
        return False
    finally:
        conn.close()
        
def reset_total_database():
    """
    Menghapus SEMUA riwayat artikel, status kategori, dan hasil ekstraksi dari
    database. Dipakai untuk mulai dari nol sama sekali. TIDAK BISA DIBATALKAN!
    Struktur tabel (schema) tetap ada, hanya isinya yang dikosongkan.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM riwayat_artikel")
    cursor.execute("DELETE FROM status_kategori")
    cursor.execute("DELETE FROM hasil_ekstraksi")
    try:
        cursor.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('riwayat_artikel', 'status_kategori', 'hasil_ekstraksi')"
        )
    except sqlite3.OperationalError:
        pass  # tabel sqlite_sequence belum ada — aman diabaikan
    conn.commit()
    conn.close()
    logger.warning(
        "[Database] RESET TOTAL dilakukan — seluruh riwayat, status kategori, "
        "dan hasil ekstraksi dihapus."
    )