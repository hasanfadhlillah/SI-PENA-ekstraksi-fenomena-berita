# File: radar/fallback.py
"""
Modul F: Auto-Expand Fallback & Anti-Buntu
Mengatur logika fallback wilayah dan saran keyword manual jika semua level gagal.
"""

# Urutan level fallback wilayah beserta instruksi manipulasi keyword
URUTAN_FALLBACK = [
    {
        "level": 1,
        "nama": "Kota Magelang",
        "key": "magelang",
        "replace": None,
        "kabupaten_sekitar": None,
    },
    {
        "level": 2,
        "nama": "Kabupaten Magelang",
        "key": "magelang",
        "replace": ("kota magelang", "magelang"),
        "kabupaten_sekitar": None,
    },
    {
        "level": 3,
        "nama": "Wilayah Sekitar Magelang / Eks-Karesidenan Kedu (Temanggung, Wonosobo, Purworejo, Kebumen)",
        "key": "magelang",
        "replace": None,
        "kabupaten_sekitar": ["temanggung", "wonosobo", "purworejo", "kebumen"],
    },
    {
        "level": 4,
        "nama": "Provinsi Jawa Tengah",
        "key": "jateng",
        "replace": None,
        "kabupaten_sekitar": None,
    },
    {
        "level": 5,
        "nama": "Nasional / Indonesia",
        "key": "nasional",
        "replace": None,
        "kabupaten_sekitar": None,
    },
]

# Sumber berita lokal yang disarankan (untuk pesan anti-buntu)
SUMBER_LOKAL = [
    "radarsemarang.jawapos.com/magelang",
    "suaramerdeka.com",
    "magelangkota.go.id",
    "jatengprov.go.id",
    "antaranews.com/jawa-tengah",
    "tribunjateng.com",
    "detik.com/jateng",
]


def dapatkan_level_fallback_berikutnya(level_sekarang: int) -> dict | None:
    """
    Return konfigurasi level fallback berikutnya, atau None jika sudah habis.
    """
    for fb in URUTAN_FALLBACK:
        if fb["level"] > level_sekarang:
            return fb
    return None


def siapkan_keyword_fallback(konfig_level: dict, keywords_per_wilayah: dict) -> list[str]:
    """
    Menyiapkan keyword sesuai wilayah fallback. Level 2: qualifier "kota"
    dihapus jadi "magelang" polos. Level 3: rotasi cyclic ke 4 kabupaten
    tetangga (Temanggung, Wonosobo, Purworejo, Kebumen) — bukan cross-product,
    supaya jumlah keyword tetap sepadan level lain.
    """
    base_key = konfig_level["key"]
    base_keywords = keywords_per_wilayah.get(base_key, [])

    kabupaten_sekitar = konfig_level.get("kabupaten_sekitar")
    if kabupaten_sekitar:
        keyword_baru = []
        for i, kw in enumerate(base_keywords):
            area = kabupaten_sekitar[i % len(kabupaten_sekitar)]
            kw_modifikasi = kw.replace("kota magelang", area)
            keyword_baru.append(kw_modifikasi)
        return keyword_baru

    atur_replace = konfig_level.get("replace")

    # Jika tidak ada instruksi replace (misal level 1, 4, 5), kembalikan aslinya
    if not atur_replace:
        return base_keywords

    # Lakukan find & replace untuk menyesuaikan nama wilayah
    kata_lama, kata_baru = atur_replace
    keyword_baru = []
    for kw in base_keywords:
        kw_modifikasi = kw.replace(kata_lama, kata_baru)
        keyword_baru.append(kw_modifikasi)

    return keyword_baru


def buat_pesan_anti_buntu(nama_kategori: str, keywords_per_wilayah: dict) -> dict:
    """
    Membuat saran keyword manual untuk ditampilkan ke user ketika semua level gagal.
    """
    semua_keyword = []
    for kw in keywords_per_wilayah.get("magelang", []):
        semua_keyword.append(kw)

    saran_google = [f'"{kw}"' for kw in semua_keyword[:6]]

    return {
        "status": "buntu",
        "pesan_utama": f"❌ Tidak ditemukan berita fenomena statistik untuk kategori '{nama_kategori}' di semua level wilayah.",
        "saran_keyword": semua_keyword[:8],
        "saran_google":  " OR ".join(saran_google[:3]),
        "saran_sumber":  SUMBER_LOKAL,
        "tips": [
            "Coba cari di Google News dengan rentang waktu yang lebih lebar.",
            "Periksa website resmi dinas terkait (mis: portal data Pemkot Magelang).",
            "Mungkin tidak ada fenomena ekonomi pada triwulan ini untuk sektor tersebut.",
        ]
    }