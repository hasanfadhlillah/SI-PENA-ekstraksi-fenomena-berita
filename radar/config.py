# File: radar/config.py
"""
Konfigurasi bersama SI-PENA RADAR.
Modul ini jadi SATU-SATUNYA tempat nilai default dideklarasikan.
"""
DEFAULT_MIN_SKOR = 6

DEFAULT_TARGET_MINIMAL = 5

# Batas maksimal proses SCAN paralel global (lintas user) untuk mencegah 
# overload server Hugging Face Spaces gratis, dikombinasikan dengan lock per-kategori.
MAKSIMAL_SCAN_BERSAMAAN = 3

# Daftar 51 kategori PDRB resmi BPS
DAFTAR_KATEGORI_PDRB = [
    "Tanaman Pangan", "Tanaman Hortikultura Semusim", "Perkebunan Semusim",
    "Tanaman Hortikultura Tahunan", "Perkebunan Tahunan", "Peternakan",
    "Jasa Pertanian dan Perburuan", "Kehutanan dan Penebangan Kayu", "Perikanan",
    "Pertambangan Minyak dan Gas Bumi", "Pertambangan Batubara dan Lignit",
    "Pertambangan Bijih Logam", "Pertambangan dan Penggalian Lainnya",
    "Industri Makanan dan Minuman", "Pengolahan Tembakau",
    "Industri Tekstil dan Pakaian Jadi", "Industri Kulit, Barang dari Kulit dan Alas Kaki",
    "Industri Kayu, Barang dari Kayu dan Gabus", "Industri Kertas dan Percetakan",
    "Industri Kimia, Farmasi dan Obat Tradisional", "Industri Karet, Barang dari Karet dan Plastik",
    "Industri Barang Galian bukan Logam", "Industri Logam Dasar",
    "Industri Barang dari Logam, Komputer, Elektronik", "Industri Alat Angkutan", "Industri Furnitur",
    "Industri Pengolahan Lainnya, Jasa Reparasi, Pemasangan Mesin dan Peralatan",
    "Ketenagalistrikan", "Pengadaan Gas dan Produksi Es", "Pengadaan Air", "Konstruksi",
    "Perdagangan Mobil, Sepeda Motor dan Reparasinya", "Perdagangan Besar dan Eceran",
    "Angkutan Rel", "Angkutan Darat", "Angkutan Laut", "Angkutan Udara",
    "Pergudangan dan Jasa Penunjang Angkutan", "Penyediaan Akomodasi", "Penyediaan Makan Minum",
    "Informasi dan Komunikasi", "Jasa Perantara Keuangan", "Asuransi dan Dana Pensiun",
    "Jasa Keuangan Lainnya", "Real Estate", "Jasa Perusahaan",
    "Administrasi Pemerintahan dan Jaminan Sosial", "Jasa Pendidikan",
    "Jasa Kesehatan dan Kegiatan Sosial", "Jasa Lainnya", "PRODUK DOMESTIK BRUTO"
]