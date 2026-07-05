# File: radar/screener.py
"""
Modul E: AI Pre-Screening & Scoring
Membaca cepat isi artikel dan memberikan skor relevansi 1-10.
Dilengkapi dengan Auto-Fallback Model Stack untuk mencegah limit kuota.
"""
import json
import time
import openai
from groq import Groq
from google import genai as google_genai
from google.genai import types as google_types

from .config import DEFAULT_MIN_SKOR
from .model_stack import AI_MODEL_CATALOG as SCREENER_STACK, MAX_TOKENS_SCREENING


# ═══════════════════════════════════════════════════════════════════════════
# FIX #11 — Referensi eksplisit wilayah Jawa Tengah untuk validasi geografi
# ═══════════════════════════════════════════════════════════════════════════
# 35 Kabupaten/Kota resmi Provinsi Jawa Tengah (29 kabupaten + 6 kota).
# Dipakai sebagai (a) ground-truth di prompt AI, dan (b) validasi programatik
# non-AI sebagai lapis kedua.
DAFTAR_KABKOTA_JATENG = [
    "cilacap", "banyumas", "purbalingga", "banjarnegara", "kebumen", "purworejo",
    "wonosobo", "magelang", "boyolali", "klaten", "sukoharjo", "wonogiri",
    "karanganyar", "sragen", "grobogan", "blora", "rembang", "pati", "kudus",
    "jepara", "demak", "semarang", "temanggung", "kendal", "batang",
    "pekalongan", "pemalang", "tegal", "brebes", "surakarta", "solo", "salatiga",
]

# Kabupaten/kota dari provinsi LAIN yang namanya rawan tertukar/rancu dengan
# konteks pencarian generik kita (mis. "panen padi", "harga beras") padahal
# BUKAN Jawa Tengah. Dipakai untuk mendeteksi kasus false-positive
DAFTAR_KABKOTA_RAWAN_TERTUKAR_BUKAN_JATENG = [
    "tulungagung", "kediri", "blitar", "jombang", "ngawi", "madiun", "ponorogo",
    "nganjuk", "trenggalek", "pacitan", "magetan", "bojonegoro", "tuban",
    "lamongan", "gresik", "sidoarjo", "mojokerto", "pasuruan", "probolinggo",
    "situbondo", "bondowoso", "jember", "banyuwangi", "malang", "surabaya",
    "denpasar", "badung", "gianyar", "palembang", "medan", "makassar",
]


def _validasi_wilayah_programatik(judul: str, teks: str, wilayah: str) -> bool | None:
    """
    Lapis kedua (non-AI) untuk validasi wilayah, khusus level Jawa Tengah..

    Return:
        True  -> terdeteksi menyebut kab/kota Jateng resmi (mendukung wilayah_valid)
        False -> terdeteksi menyebut kab/kota provinsi lain yang rawan tertukar,
                 TANPA disertai penyebutan Jateng/Jawa Tengah/Magelang -> AI
                 kemungkinan salah, override jadi tidak valid
        None  -> tidak ada sinyal kuat ke arah manapun, serahkan ke keputusan AI
    """
    if "jawa tengah" not in wilayah.lower() and "jateng" not in wilayah.lower():
        return None  # cek ini hanya relevan untuk level Provinsi Jawa Tengah

    gabungan = f"{judul} {teks}".lower()

    sebut_jateng_eksplisit = (
        "jawa tengah" in gabungan or "jateng" in gabungan or
        any(k in gabungan for k in DAFTAR_KABKOTA_JATENG)
    )
    sebut_rawan_tertukar = any(k in gabungan for k in DAFTAR_KABKOTA_RAWAN_TERTUKAR_BUKAN_JATENG)

    if sebut_rawan_tertukar and not sebut_jateng_eksplisit:
        return False
    if sebut_jateng_eksplisit:
        return True
    return None


def _call_ai_screening(api_keys: dict, prompt: str) -> tuple[str, str]:
    """
    Menjalankan request AI dengan fallback stack dan API Key Pooling.
    """
    import random

    for cfg in SCREENER_STACK:
        provider = cfg["provider"]
        model_id = cfg["model_id"]
        api_key_raw = api_keys.get(provider, "")
        pool_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]
        if not pool_keys:
            continue

        # FIX #12: max_tokens per provider dari 1 sumber kebenaran bersama
        max_tokens = MAX_TOKENS_SCREENING.get(provider, 2000)

        random.shuffle(pool_keys)
        for idx, api_key in enumerate(pool_keys):
            try:
                if provider == "groq":
                    client = Groq(api_key=api_key)
                    groq_kwargs = dict(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": "Validator berita BPS. Balas HANYA JSON murni tanpa markdown."},
                            {"role": "user",   "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=max_tokens,
                        response_format={"type": "json_object"}
                    )
                    if "gpt-oss" in model_id:
                        groq_kwargs["reasoning_effort"] = "low"
                    resp = client.chat.completions.create(**groq_kwargs)
                    teks = resp.choices[0].message.content
                    if teks is None or teks.strip() == "":
                        raise ValueError("Groq mengembalikan respons kosong")
                    return teks, cfg["nama"]

                elif provider == "gemini":
                    client = google_genai.Client(api_key=api_key)
                    gabung = f"SYSTEM: Validator berita BPS. Balas HANYA JSON murni.\n\nUSER: {prompt}"
                    gemini_config_kwargs = dict(
                        temperature=0.1,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                    )
                    thinking = cfg.get("thinking", "level")
                    if thinking == "level":
                        gemini_config_kwargs["thinking_config"] = google_types.ThinkingConfig(thinking_level="medium")
                    resp = client.models.generate_content(
                        model=model_id,
                        contents=gabung,
                        config=google_types.GenerateContentConfig(**gemini_config_kwargs)
                    )
                    teks = resp.text if resp.text is not None else ""
                    if teks.strip() == "":
                        raise ValueError("Gemini mengembalikan respons kosong")
                    return teks, cfg["nama"]

                elif provider == "cerebras":
                    client = openai.OpenAI(
                        api_key=api_key,
                        base_url="https://api.cerebras.ai/v1"
                    )
                    cerebras_kwargs = dict(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": "Validator berita BPS. Balas HANYA JSON murni tanpa markdown."},
                            {"role": "user",   "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=max_tokens,
                        response_format={"type": "json_object"}
                    )
                    if "gpt-oss" in model_id:
                        cerebras_kwargs["reasoning_effort"] = "low"
                    resp = client.chat.completions.create(**cerebras_kwargs)
                    teks = resp.choices[0].message.content
                    if teks is None or teks.strip() == "":
                        raise ValueError("Cerebras mengembalikan respons kosong")
                    return teks, cfg["nama"]

                elif provider == "mistral":
                    client = openai.OpenAI(
                        api_key=api_key,
                        base_url="https://api.mistral.ai/v1"
                    )
                    resp = client.chat.completions.create(
                        model=model_id,
                        messages=[
                            {"role": "system", "content": "Validator berita BPS. Balas HANYA JSON murni tanpa markdown."},
                            {"role": "user",   "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=max_tokens,   # FIX #12: dulu hardcode 600, sekarang 2000 (konsisten dgn provider lain)
                        response_format={"type": "json_object"}
                    )
                    teks = resp.choices[0].message.content
                    if teks is None or teks.strip() == "":
                        raise ValueError("Mistral mengembalikan respons kosong")
                    return teks, cfg["nama"]

            except Exception as e:
                err = str(e).lower()
                is_limit = any(k in err for k in [
                    "429", "rate limit", "quota", "exhausted",
                    "too many requests", "resource_exhausted"
                ])
                if is_limit:
                    print(f"         ⚠️ {cfg['nama']} [Kunci {idx+1}] Limit! Coba kunci cadangan...")
                    time.sleep(1)
                    continue
                elif "503" in err or "unavailable" in err:
                    print(f"         ⚠️ {cfg['nama']} Server sibuk (503). Pindah ke model berikutnya...")
                    break
                elif "404" in err or "not found" in err or "does not exist" in err:
                    print(f"         ⚠️ {cfg['nama']} Model 404! Pindah ke model berikutnya...")
                    break
                else:
                    print(f"         ⚠️ {cfg['nama']} Error: {str(e)[:80]}")
                    break
    raise Exception("Semua model dan puluhan API Key error atau habis kuota. Coba lagi besok.")


def screening_satu_artikel(
    api_keys: dict,
    artikel: dict,
    nama_kategori: str,
    wilayah: str,
    min_skor: int = DEFAULT_MIN_SKOR,
) -> dict:
    """
    Screening artikel untuk BPS Kota Magelang.

    ATURAN GEOGRAFI YANG BENAR:
    ✅ LOLOS: Artikel menyebut Kota Magelang secara eksplisit
    ✅ LOLOS: Artikel dari wilayah Kabupaten Magelang/sekitarnya YANG JUGA menyebut/berkaitan
              langsung dengan Kota Magelang (fokus tetap Kota Magelang, bukan sekadar sama-sama
              "Magelang")
    ✅ LOLOS: Artikel Jawa Tengah (provinsi Kota Magelang berada)
    ✅ LOLOS: Artikel NASIONAL dari Kementerian/Badan/Pemerintah Pusat
              yang dampaknya ke SELURUH Indonesia (otomatis termasuk Kota Magelang)
    ❌ TOLAK: Artikel murni Kabupaten Magelang (topik administratif/lokal Kabupaten semata)
              yang TIDAK menyebut dan TIDAK jelas berkaitan dengan Kota Magelang
    ❌ TOLAK: Artikel dari provinsi LAIN (Jatim, Bali, Sumsel, Kalsel, dll)
              yang tidak menyebut Magelang/Jawa Tengah sama sekali
    ❌ TOLAK: Artikel opini/berita tanpa data angka apapun
    """
    teks_pendek = artikel.get("teks", "")[:4000]
    judul       = artikel.get("judul", "")
    # FIX #6: prioritaskan "url" (bersih dari scraper.py) di atas "url_asli"
    url         = artikel.get("url", artikel.get("url_asli", ""))

    wilayah_lower = wilayah.lower()
    if "kota magelang" in wilayah_lower:
        level_info = "Level 1 - KOTA MAGELANG (target utama)"
    elif "kabupaten magelang" in wilayah_lower:
        level_info = "Level 2 - KABUPATEN MAGELANG (fallback, HARUS tetap terkait Kota Magelang)"
    elif "kedu" in wilayah_lower:
        level_info = "Level 3 - WILAYAH SEKITAR MAGELANG (fallback, HARUS tetap terkait Kota Magelang/Jateng)"
    elif "jawa tengah" in wilayah_lower or "jateng" in wilayah_lower:
        level_info = "Level 4 - PROVINSI JAWA TENGAH (fallback)"
    else:
        level_info = "Level 5 - NASIONAL/INDONESIA (fallback terakhir)"

    # FIX #11: daftar 35 kab/kota Jateng resmi disisipkan sebagai ground-truth
    daftar_jateng_str = ", ".join(k.title() for k in DAFTAR_KABKOTA_JATENG)

    prompt = f"""
        Kamu adalah validator berita untuk BPS KOTA MAGELANG, Jawa Tengah, Indonesia.
        TUGAS: Nilai apakah artikel ini LAYAK DIEKSTRAK untuk keperluan data PDRB Kota Magelang.
        LANGKAH WAJIB SEBELUM MENJAWAB:
        Baca ULANG seluruh isi artikel di bawah dari awal sampai akhir, kalimat demi kalimat —
        JANGAN hanya menilai dari judul atau paragraf pertama saja. Banyak angka dan perbandingan
        waktu justru baru muncul di paragraf tengah/akhir.
        === KONTEKS PENCARIAN ===
        Kategori PDRB: "{nama_kategori}"
        Level Pencarian: {level_info}
        Ambang Skor Minimum yang berlaku SAAT INI: {min_skor}/10
        FOKUS UTAMA: Data/fenomena untuk KOTA MAGELANG. Wilayah lain (Kabupaten Magelang, Jateng,
        Nasional) hanya relevan sebagai KONTEKS/DAMPAK terhadap Kota Magelang, bukan topik yang
        berdiri sendiri.
        === REFERENSI RESMI: 35 KABUPATEN/KOTA PROVINSI JAWA TENGAH ===
        {daftar_jateng_str}
        Jika sebuah artikel menyebut nama kabupaten/kota yang TIDAK ADA di daftar ini (dan bukan
        berasal dari Kementerian/Lembaga Pusat), KEMUNGKINAN BESAR itu BUKAN wilayah Jawa Tengah.
        JANGAN tandai wilayah_valid=true hanya karena kebetulan ada kata "Jawa" atau nama daerah yang
        mirip — pastikan daerah yang disebut benar-benar masuk daftar di atas, ATAU artikel juga
        secara eksplisit menyebut "Jawa Tengah"/"Jateng"/"Magelang".
        === DATA ARTIKEL ===
        JUDUL: {judul}
        URL: {url}
        ISI ARTIKEL:
        {teks_pendek}
        === ATURAN GEOGRAFI (WAJIB DIPATUHI) ===
        PENTING: Kota Magelang adalah kota kecil yang secara geografis terletak DI DALAM/dikelilingi
        oleh Kabupaten Magelang. Karena itu, berita soal Kabupaten Magelang TIDAK OTOMATIS relevan
        untuk Kota Magelang — harus benar-benar ada kaitan/dampak ke Kota Magelang, bukan sekadar
        kebetulan sama-sama memakai nama "Magelang".
        JENIS ARTIKEL YANG WAJIB DILOLOSKAN (jika memenuhi syarat data):
        1. ✅ Artikel yang secara EKSPLISIT menyebut "Kota Magelang"
        2. ✅ Artikel tentang Kabupaten Magelang/wilayah sekitar Magelang YANG JUGA menyebut "Kota
           Magelang" secara eksplisit, ATAU yang jelas-jelas menggambarkan kondisi/kebijakan yang
           sama-sama berlaku untuk Kota Magelang (misal harga pasar regional, kebijakan gabungan
           Kota-Kabupaten, bencana yang berdampak ke keduanya)
        3. ✅ Artikel yang membahas kondisi di "Jawa Tengah" atau "Jateng" (provinsi Kota Magelang),
           DENGAN kabupaten/kota yang disebut benar-benar terdaftar di 35 kab/kota Jateng di atas
        4. ✅ Artikel NASIONAL dari KEMENTERIAN/BADAN/PEMERINTAH PUSAT (contoh: Kementan, Bulog, BPS Pusat, Bapanas, dll) yang menetapkan kebijakan/data berlaku SELURUH Indonesia — otomatis berdampak ke Kota Magelang
        JENIS ARTIKEL YANG WAJIB DITOLAK:
        1. ❌ Artikel yang HANYA membahas Kabupaten Magelang secara administratif/lokal (misal proyek desa, kegiatan pemkab semata) TANPA menyebut atau berkaitan jelas dengan Kota Magelang
        2. ❌ Artikel dari PROVINSI LAIN (Jawa Timur, Bali, Sumatera Selatan, Kalimantan, Papua, dll) yang TIDAK menyebut Magelang atau Jawa Tengah sama sekali — termasuk kabupaten/kota yang TIDAK ADA di daftar 35 kab/kota Jateng di atas
        3. ❌ Artikel yang hanya membahas kota/kabupaten lain di luar Jawa Tengah tanpa kaitan ke Magelang
        4. ❌ Artikel opini/lifestyle/hiburan tanpa data statistik apapun
        5. ❌ Artikel tentang topik yang SAMA SEKALI tidak berkaitan dengan kategori "{nama_kategori}"
        CONTOH KEPUTUSAN:
        - "Produksi Padi Jatim Tembus 8,7 Juta Ton" → ❌ TOLAK (Jatim bukan Jateng, tidak sebut Magelang)
        - "Harga Beras di Bali Stabil" → ❌ TOLAK (Bali bukan Jateng)
        - "Bulog Tulungagung Gelontorkan Ratusan Ton Beras" → ❌ TOLAK (Tulungagung TIDAK ADA di daftar 35 kab/kota Jateng — itu Jawa Timur, meski sekilas mirip konteks Jawa)
        - "Pemkab Magelang Resmikan Jalan Desa di Kecamatan Salaman" → ❌ TOLAK (murni administratif Kabupaten, tidak menyebut/berkaitan dengan Kota Magelang)
        - "Harga Cabai di Pasar Rejowinangun Kota Magelang dan Pasar Muntilan Kabupaten Magelang Kompak Naik" → ✅ LOLOS (menyebut Kota Magelang secara eksplisit meski juga membahas Kabupaten)
        - "Kementan: Produksi Beras Nasional Naik 15%" → ✅ LOLOS (kebijakan nasional, berdampak ke semua daerah termasuk Kota Magelang)
        - "Harga Beras Jawa Tengah Naik Menjelang Lebaran" → ✅ LOLOS (Jawa Tengah = provinsi Kota Magelang)
        - "BPS: Inflasi Pangan Nasional Bulan Ini 0,5%" → ✅ LOLOS (data nasional BPS berlaku semua daerah)
        - "Bulog Pastikan Stok Beras Nasional Aman" → ✅ LOLOS (kebijakan nasional Bulog)
        === KRITERIA DATA FENOMENA STATISTIK ===
        Minimal SALAH SATU harus terpenuhi untuk skor ≥ {min_skor}:
        A. Ada DATA ANGKA SPESIFIK: harga (Rp), persentase (%), berat (ton/kuintal/kg), luas (ha), jumlah unit/orang, tanggal pencatatan data
        B. Ada PERBANDINGAN WAKTU: baik eksplisit ("naik X% dari bulan lalu", "turun dibanding tahun lalu", "y-on-y", "q-to-q") MAUPUN implisit/naratif (misal dibandingkan dengan kejadian serupa tahun sebelumnya, proyeksi ke depan yang dibandingkan kondisi saat ini)
        C. Ada PERNYATAAN DATA RESMI dari pejabat/instansi pemerintah tentang kondisi sektor
        PENTING UNTUK FIELD "ada_data_angka" DAN "ada_perbandingan_waktu":
        - SISIR seluruh teks kalimat demi kalimat sebelum memutuskan. Jangan buru-buru menjawab false
          hanya karena angka/perbandingan tidak ada di judul atau paragraf pertama.
        - "ada_data_angka" = true jika ADA SATU SAJA angka spesifik disebutkan di manapun dalam teks.
        - "ada_perbandingan_waktu" = true jika ADA perbandingan waktu eksplisit MAUPUN implisit
          (termasuk perbandingan naratif seperti "sama seperti tahun lalu kita berhasil melewati
          El Nino" atau proyeksi ke bulan/tahun depan).
        - Cek ULANG dua kali sebelum menjawab false pada kedua field ini.
        === FORMAT JAWABAN ===
        Balas HANYA dengan JSON ini (tanpa markdown, tanpa teks lain):
        {{
        "skor_relevansi": <angka 1-10>,
        "alasan_singkat": "<2-3 kalimat: sebutkan isi artikel, kenapa lolos/tidak, dan data apa yang ada>",
        "ada_data_angka": <true/false>,
        "ada_perbandingan_waktu": <true/false>,
        "relevan_dengan_kategori": <true/false>,
        "wilayah_valid": <true jika lolos aturan geografi di atas, false jika artikel provinsi lain atau Kabupaten Magelang murni tanpa kaitan Kota>,
        "sumber_nasional_resmi": <true jika dari Kementerian/Badan/Pemerintah Pusat yang berdampak nasional>,
        "layak_ekstrak": <true HANYA jika: skor>={min_skor} DAN relevan_dengan_kategori=true DAN wilayah_valid=true>
        }}
        === PANDUAN SKOR DETAIL ===
        10  : Ada data angka SPESIFIK + perbandingan waktu + menyebut Kota Magelang LANGSUNG
        9   : Ada data angka spesifik + perbandingan waktu + konteks Jawa Tengah
        8   : Ada data angka spesifik + relevan kategori + wilayah valid (Magelang/Jateng/Nasional resmi)
        7   : Ada data angka + relevan kategori + wilayah valid, tapi perbandingan waktu kurang eksplisit
        6   : Ada data angka atau pernyataan resmi + relevan kategori + wilayah valid, tapi data kurang spesifik
        5   : Relevan kategori + wilayah valid, tapi minim data konkret
        3-4 : Ada kaitan dengan kategori tapi data sangat kurang atau wilayah kurang relevan
        1-2 : Artikel tidak relevan kategori, atau berasal dari provinsi lain / Kabupaten Magelang murni yang tidak berdampak ke Kota Magelang

        ATURAN: Jangan pernah membuat-buat data (No Hallucination).
        """
    try:
        teks_json, model_terpakai = _call_ai_screening(api_keys, prompt)
        teks_json = teks_json.strip().replace('```json', '').replace('```', '').strip()
        hasil = json.loads(teks_json)
        hasil["url"]             = url
        hasil["judul"]           = judul
        hasil["teks"]            = artikel.get("teks", "")
        hasil["_model_screener"] = model_terpakai

        # ═══════════════════════════════════════════════════════════════════
        # FIX #11 — Lapis kedua non-AI: override wilayah_valid kalau AI keliru
        # ═══════════════════════════════════════════════════════════════════
        validasi_programatik = _validasi_wilayah_programatik(judul, artikel.get("teks", ""), wilayah)
        if validasi_programatik is False and hasil.get("wilayah_valid") is True:
            print(
                f"      ⚠️ [Validasi Geografi] AI bilang wilayah_valid=True tapi artikel menyebut "
                f"kab/kota di luar Jateng tanpa konteks Jateng/Magelang. Override jadi False."
            )
            hasil["wilayah_valid"] = False
            hasil["layak_ekstrak"] = False
            hasil["alasan_singkat"] = (
                str(hasil.get("alasan_singkat", "")) +
                " [Dikoreksi otomatis: artikel menyebut kabupaten/kota di luar Jawa Tengah "
                "tanpa kaitan eksplisit ke Jawa Tengah/Magelang.]"
            )

        return hasil
    except Exception as e:
        print(f"      ⚠️ Screening Gagal Total untuk {url[:50]}: {e}")
        return {
            "url": url, "judul": judul, "teks": artikel.get("teks", ""),
            "skor_relevansi": 0, "alasan_singkat": f"Error AI: {str(e)[:60]}",
            "ada_data_angka": False, "ada_perbandingan_waktu": False,
            "relevan_dengan_kategori": False, "wilayah_valid": False,
            "sumber_nasional_resmi": False, "layak_ekstrak": False
        }


def screening_batch(
    api_keys: dict,
    list_artikel: list[dict],
    nama_kategori: str,
    wilayah: str,
    min_skor: int = DEFAULT_MIN_SKOR,
    jeda_detik: float = 1.0,
    max_artikel: int = 15,
    target_minimal: int | None = None,   # FIX #10: opsional, aktifkan batch lanjutan
    callback_log=None,                   # FIX #10: teruskan log ke UI, bukan cuma print
) -> tuple[list[dict], list[dict]]:
    """
    FIX #10: dulu artikel yang melebihi `max_artikel` (default 15) langsung
    dibuang tanpa pernah dinilai AI sama sekali — tanpa notifikasi jelas ke
    user. Sekarang:
    1. Log eksplisit berapa artikel yang TIDAK dinilai pada batch pertama.
    2. Jika target_minimal diberikan dan hasil batch pertama masih kurang,
       lanjutkan screening batch KEDUA (dibatasi hanya 1 putaran tambahan,
       supaya waktu eksekusi tetap terkendali — lihat juga fix #3) dari sisa
       artikel yang belum dinilai.
    3. Log eksplisit lagi kalau masih ada sisa yang benar-benar tidak sempat
       dinilai setelah 2 putaran.
    """
    if not list_artikel:
        return [], []

    def _log(pesan: str):
        print(pesan)
        if callback_log:
            callback_log(pesan)

    def skor_prioritas(art):
        teks_cek = (art.get("judul", "") + art.get("url", "")).lower()
        if "kota magelang" in teks_cek:
            return 0
        elif "magelang" in teks_cek:
            return 1
        elif "jawa tengah" in teks_cek or "jateng" in teks_cek:
            return 2
        else:
            return 3

    list_artikel_sorted = sorted(list_artikel, key=skor_prioritas)
    total_tersedia = len(list_artikel_sorted)

    wilayah_lower = wilayah.lower()
    if "kota magelang" in wilayah_lower:
        tampilan = "KOTA MAGELANG"
    elif "kabupaten magelang" in wilayah_lower:
        tampilan = "KABUPATEN MAGELANG"
    elif "kedu" in wilayah_lower:
        tampilan = "WILAYAH SEKITAR MAGELANG"
    elif "jawa tengah" in wilayah_lower or "jateng" in wilayah_lower:
        tampilan = "PROVINSI JAWA TENGAH"
    else:
        tampilan = "NASIONAL / INDONESIA"

    def _screening_satu_batch(batch: list[dict], nomor_batch: int) -> tuple[list[dict], list[dict]]:
        _log(
            f"\n   🤖 AI Screening batch #{nomor_batch}: {len(batch)} artikel untuk "
            f"'{nama_kategori}' di {tampilan} (ambang skor: {min_skor}/10)..."
        )
        lolos_batch, gagal_batch = [], []
        for i, artikel in enumerate(batch, 1):
            _log(f"      [{i}/{len(batch)}] Menilai: {artikel.get('judul', '')[:55]}...")
            hasil = screening_satu_artikel(api_keys, artikel, nama_kategori, wilayah, min_skor=min_skor)
            skor  = hasil.get("skor_relevansi", 0)
            layak = hasil.get("layak_ekstrak", False)
            wilayah_valid = hasil.get("wilayah_valid", False)
            if skor >= min_skor and layak:
                badge = "🟢" if skor >= 8 else "🟡"
                _log(f"         {badge} LOLOS — Skor {skor}/10 | Wilayah valid: {wilayah_valid} | by {hasil.get('_model_screener', 'AI')}")
                lolos_batch.append(hasil)
            else:
                _log(f"         🔴 TIDAK LOLOS — Skor {skor}/10 | Wilayah valid: {wilayah_valid} | by {hasil.get('_model_screener', 'AI')}")
                gagal_batch.append(hasil)
            time.sleep(jeda_detik)
        return lolos_batch, gagal_batch

    # ── Batch pertama ──
    batch_pertama = list_artikel_sorted[:max_artikel]
    sisa_belum_dinilai = list_artikel_sorted[max_artikel:]

    if sisa_belum_dinilai:
        _log(
            f"   ⚠️ {total_tersedia} artikel tersedia, dibatasi {max_artikel} untuk batch "
            f"pertama (prioritas: Magelang > Jateng > Nasional). {len(sisa_belum_dinilai)} "
            f"artikel BELUM dinilai sama sekali pada tahap ini."
        )

    lolos, gagal = _screening_satu_batch(batch_pertama, nomor_batch=1)

    # ── FIX #10: batch lanjutan (maksimal 1 putaran tambahan) ──
    if target_minimal is not None and len(lolos) < target_minimal and sisa_belum_dinilai:
        batch_kedua = sisa_belum_dinilai[:max_artikel]
        sisa_setelah_batch_kedua = sisa_belum_dinilai[max_artikel:]
        _log(
            f"   🔁 Hasil batch pertama ({len(lolos)} lolos) belum capai target minimal "
            f"({target_minimal}). Melanjutkan screening {len(batch_kedua)} artikel tambahan..."
        )
        lolos_2, gagal_2 = _screening_satu_batch(batch_kedua, nomor_batch=2)
        lolos.extend(lolos_2)
        gagal.extend(gagal_2)

        if sisa_setelah_batch_kedua:
            _log(
                f"   ℹ️ Masih ada {len(sisa_setelah_batch_kedua)} artikel yang belum dinilai "
                f"setelah 2 batch (dihentikan agar waktu eksekusi tetap wajar)."
            )
    elif sisa_belum_dinilai:
        _log(
            f"   ℹ️ {len(sisa_belum_dinilai)} artikel tidak dinilai pada level ini "
            f"(target_minimal tidak diaktifkan, atau hasil batch pertama sudah mencukupi)."
        )

    _log(f"\n   📊 Screening selesai: {len(lolos)} lolos, {len(gagal)} tidak lolos")
    return lolos, gagal