# File: radar/config.py
"""
Konfigurasi bersama SI-PENA RADAR.

FIX #2 (audit QA): sebelumnya ambang skor minimum "6" di-hardcode secara
independen di 3 tempat berbeda tanpa saling terhubung:
  1. Prompt AI di screener.py (field "layak_ekstrak" selalu mensyaratkan skor>=6)
  2. Query SQL di database.py (ambil_artikel_valid, WHERE skor_relevansi >= 6)
  3. Default parameter di pipeline.py (min_skor: int = 6)

Akibatnya, slider "Skor Minimum Lolos" di UI (app.py) tidak pernah benar-benar
mengontrol ambang batas AI untuk nilai di bawah 6 — AI selalu menolak artikel
skor <6 terlepas dari posisi slider, karena field "layak_ekstrak" murni hasil
keputusan internal AI yang hardcode.

Modul ini jadi SATU-SATUNYA tempat nilai default dideklarasikan. Semua modul
lain WAJIB mengimpor dari sini, bukan menuliskan angka 6 secara manual lagi.
"""

DEFAULT_MIN_SKOR = 6