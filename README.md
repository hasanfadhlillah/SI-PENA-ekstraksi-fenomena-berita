<div align="center">

# ✒️ SI-PENA

### Sistem Informasi Pencari Berita & Ekstraksi Fenomena

_"Menulis ulang fakta dari ribuan narasi berita."_

**🌐 Akses Langsung Aplikasi:** [clips.id/SI-PENA](https://clips.id/SI-PENA)

<br>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.38%2B-ff4b4b?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20Mode-003b57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![HuggingFace](https://img.shields.io/badge/🤗%20Backup-HF%20Dataset-ffbf00?style=for-the-badge)](https://huggingface.co/)

[![BPS Kota Magelang](https://img.shields.io/badge/BPS-Kota%20Magelang-003366?style=flat-square)]()
[![Status](https://img.shields.io/badge/Status-Aktif%20Dikembangkan-brightgreen?style=flat-square)]()
[![License](https://img.shields.io/badge/License-Internal%20Use-blue?style=flat-square)]()
[![Maintained](https://img.shields.io/badge/Maintained-Yes-success?style=flat-square)]()

<img src="https://img.shields.io/badge/🎯%20Kategori%20PDRB-51-blue?style=flat-square" />
<img src="https://img.shields.io/badge/🌍%20Level%20Fallback-5-blue?style=flat-square" />
<img src="https://img.shields.io/badge/🤖%20Model%20AI-8-blue?style=flat-square" />
<img src="https://img.shields.io/badge/📝%20Variabel%20Ekstraksi-12-blue?style=flat-square" />

</div>

---

## 📌 Daftar Isi

- [Tentang SI-PENA](#-tentang-si-pena)
- [Fitur Utama](#-fitur-utama)
- [Alur Kerja Pipeline Radar](#-alur-kerja-pipeline-radar)
- [Tech Stack](#️-tech-stack)
- [Instalasi & Menjalankan Lokal](#️-instalasi--menjalankan-lokal)
- [Struktur Proyek](#-struktur-proyek)
- [Sistem Multi-Sesi & Auto-Backup](#-sistem-multi-sesi--auto-backup)
- [Screenshot / Tab Aplikasi](#-tab-aplikasi)
- [Pengembang](#-pengembang)
- [Kontak](#️-kontak)

---

## 📖 Tentang SI-PENA

Dalam proses penyusunan data **PDRB (Produk Domestik Regional Bruto)** Kota Magelang, analis BPS membutuhkan referensi fenomena ekonomi tiap triwulan — mulai dari fluktuasi harga komoditas, kondisi sektor industri, hingga kebijakan pemerintah yang berdampak ke perekonomian lokal.

Selama ini proses pencarian dilakukan **manual**: membuka mesin pencari, menelusuri satu per satu artikel, menentukan relevansi, menyalin data penting, lalu memformatnya ke formulir — memakan waktu berjam-jam per kategori.

**SI-PENA hadir sebagai solusi**: mengotomasi seluruh alur kerja tersebut dengan bantuan kecerdasan buatan (AI), sehingga analis dapat fokus pada validasi dan analisis — bukan pencarian manual. Sistem tetap menerapkan prinsip **human-in-the-loop**: AI mengekstrak, staf yang memvalidasi dan memfinalisasi.

🚀 **Coba dan jalankan SI-PENA secara langsung melalui:** [clips.id/SI-PENA](https://clips.id/SI-PENA)

> 🎓 Dikembangkan sebagai bagian dari program Magang mahasiswa Fakultas Ilmu Komputer Universitas Brawijaya di **BPS Kota Magelang**.

---

## 🚀 Fitur Utama

| Fitur                            | Deskripsi                                                                                                                                                                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 📡 **Radar Pencari Berita**      | Mencari berita otomatis dari DuckDuckGo News, Google News RSS, dan DuckDuckGo Web. Dilengkapi **5 level fallback wilayah** (Kota Magelang → Kabupaten Magelang → Eks-Karesidenan Kedu → Jawa Tengah → Nasional) dan skoring relevansi AI skala 1–10.         |
| 📝 **Ekstraktor Fenomena AI**    | Membaca artikel secara penuh (termasuk yang berhalaman-halaman) dan mengekstrak **12 variabel BPS**: ringkasan fenomena, data angka kuantitatif, kutipan narasumber, lokasi spesifik, intervensi pemerintah, periode kejadian, sentimen dampak, dan lainnya. |
| 🗄️ **History & Download Massal** | Riwayat pencarian & hasil ekstraksi tersimpan permanen di SQLite, bisa diunduh sebagai **Excel** (berformat rapi siap cetak), **CSV**, atau **JSON** — satu per satu maupun sekaligus massal.                                                                |
| 📈 **Dashboard Analisis**        | Visualisasi interaktif (Altair): tren penemuan berita harian, distribusi status antrean, dan Top 10 sektor PDRB paling banyak diberitakan.                                                                                                                   |
| ⚙️ **Manajemen Keyword**         | Edit, tambah, atau hapus keyword pencarian per kategori PDRB langsung dari UI Streamlit — tanpa sentuh kode, tanpa restart aplikasi.                                                                                                                         |
| 🤖 **Multi-AI Auto-Fallback**    | Stack **8 model AI** (Groq, Google Gemini/Gemma, Cerebras, Mistral) dengan _pooling_ multi-API-key per provider. Kalau satu model/key kena limit atau error, sistem otomatis pindah ke model cadangan berikutnya.                                            |
| 🔀 **Multi-Sesi Aman**           | Sampai 3 staf bisa scan **bersamaan** tanpa bentrok data, lewat sistem kunci per-kategori + kuota global + live-log yang bisa dipantau lintas sesi.                                                                                                          |
| ☁️ **Auto-Backup Zero-Cost**     | Karena dideploy di tier gratis (storage ephemeral), seluruh data (riwayat artikel, hasil ekstraksi, keyword) otomatis ter-_backup_ ke **Hugging Face Dataset** setiap ada perubahan penting, dan otomatis di-_restore_ saat Space baru saja restart.         |

---

## 🧠 Alur Kerja Pipeline Radar

Setiap kali tombol **▶ SCAN** ditekan, sistem menjalankan 6 modul secara berurutan:

                    Kategori PDRB
                           │
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [A] Query Expansion                          │
    │  Kamus statis (keywords.json) atau AI fallback│
    │  → keyword pencarian jurnalistik natural      │
    └──────────────────────┬─────────────────────────┘
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [B] Multi-Source Search                      │
    │  DuckDuckGo News + Google News RSS            │
    │  + DuckDuckGo Web (fallback jika hasil tipis) │
    └──────────────────────┬─────────────────────────┘
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [C] Database Filter                          │
    │  Skip URL yang sudah pernah diproses (SQLite) │
    └──────────────────────┬─────────────────────────┘
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [D] Parallel Scraping (ThreadPoolExecutor)   │
    │  Jina Reader API → Direct Request →           │
    │  Wayback Machine  (+ deteksi artikel          │
    │  berhalaman & auto-gabung ?page=all)          │
    └──────────────────────┬─────────────────────────┘
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [E] AI Pre-Screening & Scoring               │
    │  Skor relevansi 1–10 berdasarkan geografi,    │
    │  data angka, kesesuaian kategori PDRB         │
    └──────────────────────┬─────────────────────────┘
                           ▼
    ┌──────────────────────────────────────────────┐
    │  [F] Auto-Expand Fallback                     │
    │  Kalau hasil masih kosong/kurang, otomatis    │
    │  turun ke level wilayah yang lebih luas       │
    └──────────────────────┬─────────────────────────┘
                           ▼
              📥  Antrean Artikel Siap Ekstrak

Artikel yang lolos screening masuk ke antrean **Tab 2 — Ekstraktor Fenomena**. Di sana AI membaca artikel secara penuh dan memecahnya menjadi **12 variabel BPS**, staf memvalidasi & mengedit hasilnya (_human-in-the-loop_), lalu menekan **Finalisasi** — data otomatis tersimpan ke database dan siap diunduh dari Tab History.

---

## 🛠️ Tech Stack

<div align="center">

| Kategori               | Teknologi                                                                                                                                                                                                                                                                                                   |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Framework & Bahasa** | ![Python](https://img.shields.io/badge/-Python%203.10+-3776ab?logo=python&logoColor=white) ![Streamlit](https://img.shields.io/badge/-Streamlit-ff4b4b?logo=streamlit&logoColor=white)                                                                                                                      |
| **Database**           | ![SQLite](<https://img.shields.io/badge/-SQLite%20(WAL)-003b57?logo=sqlite&logoColor=white>)                                                                                                                                                                                                                |
| **Model AI**           | ![Groq](https://img.shields.io/badge/-Groq%20GPT--OSS%20120B-f55036) ![Gemini](https://img.shields.io/badge/-Gemini%203.x%20%2F%20Gemma%204-4285f4?logo=google&logoColor=white) ![Cerebras](https://img.shields.io/badge/-Cerebras-7c3aed) ![Mistral](https://img.shields.io/badge/-Mistral%20Small-ff7000) |
| **Sumber Berita**      | DuckDuckGo News · Google News RSS · DuckDuckGo Web · Jina Reader API · Wayback Machine                                                                                                                                                                                                                      |
| **Backup**             | ![HuggingFace](https://img.shields.io/badge/-HF%20Dataset%20Repo-ffbf00?logo=huggingface&logoColor=black)                                                                                                                                                                                                   |
| **Visualisasi**        | ![Altair](https://img.shields.io/badge/-Altair-f9a03c)                                                                                                                                                                                                                                                      |
| **Ekspor Data**        | `openpyxl` (Excel berformat), CSV, JSON                                                                                                                                                                                                                                                                     |

</div>

**Library kunci lainnya:** `feedparser` (parsing RSS), `requests` (HTTP), `ddgs` (DuckDuckGo Search API), `python-dateutil` (parsing tanggal robust), `python-dotenv`, `pandas`, `huggingface_hub`.

---

## ⚙️ Instalasi & Menjalankan Lokal

### 1. Clone & Install Dependensi

```bash
git clone <repo-url>
cd si-pena

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Konfigurasi Environment

Buat file `.env` di root project:

```env
# ─── API Key AI (bisa isi lebih dari 1, pisahkan koma untuk load balancing) ───
GROQ_API_KEYS=key1,key2,key3
GEMINI_API_KEYS=key1,key2
CEREBRAS_API_KEYS=key1
MISTRAL_API_KEYS=key1

# ─── Auto-Backup ke Hugging Face Dataset (SANGAT direkomendasikan) ───────────
# Wajib jika deploy di HF Spaces tier gratis, karena storage bersifat ephemeral
# (data hilang tiap restart/tidur-bangun) tanpa backup ini.
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
HF_BACKUP_REPO_ID=username/nama-dataset-backup

# ─── Opsional ─────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
TZ=Asia/Jakarta
```

> ⚠️ **Jangan pernah commit file `.env`** ke repository. Pastikan sudah ada di `.gitignore`.

### 3. Jalankan

```bash
streamlit run app.py
```

Buka `http://localhost:8501` di browser.

---

## 📂 Struktur Proyek

```text
si-pena/
├── app.py                  # Entry point Streamlit — 6 tab UI
├── ai_engine.py            # Ekstraksi 12 variabel BPS (dispatcher multi-model + retry koreksi)
├── scraper.py              # Scraper berlapis 3 (Jina/Direct/Wayback) + deteksi artikel berhalaman
├── requirements.txt
├── .env                    # (tidak di-commit — buat sendiri, lihat panduan di atas)
│
└── radar/
    ├── config.py           # Konfigurasi bersama — single source of truth (51 kategori PDRB, dll)
    ├── database.py         # SQLite: riwayat_artikel, status_kategori, hasil_ekstraksi
    ├── query_expander.py   # Modul A — kategori PDRB → keyword pencarian jurnalistik
    ├── searcher.py         # Modul B — multi-source search engine (DDG News/RSS/Web)
    ├── fetcher.py          # Modul D — orkestrator parallel scraping (ThreadPoolExecutor)
    ├── screener.py         # Modul E — AI pre-screening & skoring relevansi
    ├── fallback.py         # Modul F — fallback 5 level wilayah
    ├── pipeline.py         # Orchestrator utama Modul A → F
    ├── scan_manager.py     # Background job registry (thread-safe, multi-sesi)
    ├── backup.py           # Auto-backup/restore ke Hugging Face Dataset
    ├── model_stack.py      # Katalog & urutan fallback 8 model AI
    ├── logger_config.py    # Logger terpusat (sipena.<modul>)
    └── keywords.json       # Kamus keyword pencarian per kategori PDRB
```

---

## 🔀 Sistem Multi-Sesi & Auto-Backup

SI-PENA dirancang untuk dipakai **beberapa staf secara bersamaan** tanpa saling mengganggu:

- **Kuota Global** — maksimal 3 proses scan boleh berjalan bersamaan (menjaga server & kuota API tidak overload).
- **Kunci Per-Kategori** — 1 kategori PDRB hanya boleh di-scan 1 orang dalam satu waktu; kategori lain tetap bebas dipakai user lain secara paralel, termasuk saat Batch Scan berjalan.
- **Live-Log Lintas Sesi** — refresh halaman atau pindah tab itu aman, proses tetap berjalan di server; progress bisa disambungkan kembali dari sesi manapun lewat tombol **👁️ Pantau**.

Karena umumnya dideploy di **Hugging Face Spaces tier gratis** (storage tidak persisten), SI-PENA otomatis:

1. **Auto-backup** seluruh database & keyword ke HF Dataset setiap ada perubahan penting (finalisasi ekstraksi, edit keyword, dll), dengan jeda minimal 5 menit untuk mencegah spam commit.
2. **Auto-restore** dari backup terakhir setiap kali Space baru saja restart dan mendeteksi data lokal kosong/hilang.

---

## 🗂️ Tab Aplikasi

| Tab                        | Fungsi                                                           |
| -------------------------- | ---------------------------------------------------------------- |
| 📡 **RADAR BERITA**        | Jalankan pencarian & lihat status kelengkapan tiap kategori PDRB |
| 📝 **EKSTRAKTOR FENOMENA** | Meja operasi AI untuk membedah artikel jadi 12 variabel BPS      |
| 🗄️ **HISTORY BERITA**      | Arsip & ekspor massal riwayat radar + hasil ekstraksi            |
| 📈 **DASHBOARD ANALISIS**  | Visualisasi tren & performa mesin pencari berita                 |
| ⚙️ **KELOLA KEYWORD**      | Edit kamus keyword pencarian per kategori                        |
| ℹ️ **TENTANG SI-PENA**     | Latar belakang, fitur, alur kerja, dan tech stack                |

---

## 👥 Pengembang

Dikembangkan oleh mahasiswa Fakultas Ilmu Komputer, Universitas Brawijaya, sebagai bagian dari program Magang di **BPS Kota Magelang**:

<div align="center">

|     |                                |
| --- | ------------------------------ |
| 👨‍💻  | **Muhammad Hasan Fadhlillah**  |
| 👨‍💻  | **Muhammad Husain Fadhlillah** |

</div>

Platform ini bersifat _open-source internal_ dan terbuka untuk dikembangkan lebih lanjut oleh tim BPS Kota Magelang maupun kontributor berikutnya.

---

## 🏛️ Kontak

**Badan Pusat Statistik — Kota Magelang**

Jl. Jend. Gatot Soebroto No. 54-D, Jurangombo Selatan, Kec. Magelang Selatan, Kota Magelang, Jawa Tengah 56123

🌐 [magelangkota.bps.go.id](https://magelangkota.bps.go.id)

---

<div align="center">

**SI-PENA v1.0**

Made with ❤️ for BPS Kota Magelang

</div>
