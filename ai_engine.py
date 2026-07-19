# File: ai_engine.py
import json
import time
import re
import openai
from groq import Groq
from google import genai as google_genai
from google.genai import types as google_types
from radar.model_stack import (
    AI_MODEL_CATALOG_EKSTRAKSI as MODEL_STACK,
    MAX_TOKENS_EKSTRAKSI,
    format_model_404_message,
)
from radar.config import DAFTAR_KATEGORI_PDRB
from radar.logger_config import get_logger
logger = get_logger(__name__)

# Field deskriptif dasar yang wajib terisi. Jika nilainya "Tidak ada informasi" 
# pada respons pertama AI, sistem otomatis memicu 1x retry khusus untuk field ini.
FIELD_WAJIB_TERISI = [
    "judul_dan_tanggal", "sumber_dan_link", "ringkasan_fenomena",
    "kata_kunci", "sentimen_dampak",
]
_NILAI_KOSONG = {"", "tidak ada informasi", "tidak diketahui", "-", "n/a", "none", "null"}

# Safety-net berbasis regex (bukan AI) untuk mendeteksi pola angka/kutipan di teks sumber.
# Digunakan untuk menangkap kasus di mana AI melewatkan data yang sebenarnya tersedia.
_POLA_ANGKA_KUAT = re.compile(
    r'(rp\s?[\d.,]+|\b\d+([.,]\d+)?\s?(persen|%|ton|kuintal|kg|kilogram|hektar|\bha\b|juta|miliar|triliun|ribu|orang|unit|ekor))',
    re.IGNORECASE
)
_POLA_KUTIPAN_KUAT = re.compile(r'[“"][^"”]{20,}[”"]')

def _ada_indikasi_data_angka(teks: str) -> bool:
    return bool(_POLA_ANGKA_KUAT.search(teks or ""))

def _ada_indikasi_kutipan(teks: str) -> bool:
    return bool(_POLA_KUTIPAN_KUAT.search(teks or ""))

def _cek_field_kosong(hasil: dict, teks: str = "") -> list[str]:
    """
    Return daftar field wajib atau yang terindikasi terlewat oleh AI untuk di-retry.
    Validasi dilakukan dalam 2 lapis:
    1. FIELD_WAJIB_TERISI: Field dasar yang tidak boleh kosong dalam kondisi apa pun.
    2. Heuristik Sumber: Field angka/kutipan yang aslinya kosong, tetapi dipaksa retry 
    jika pola (Rp, %, kata kunci kutipan) terdeteksi ada di teks sumber.
    """
    kosong = []
    for f in FIELD_WAJIB_TERISI:
        nilai = str(hasil.get(f, "")).strip().lower()
        if nilai in _NILAI_KOSONG:
            kosong.append(f)

    nilai_angka = str(hasil.get("data_angka", "")).strip().lower()
    if nilai_angka in _NILAI_KOSONG and _ada_indikasi_data_angka(teks):
        kosong.append("data_angka")

    nilai_kutipan = str(hasil.get("kutipan_tokoh", "")).strip().lower()
    if nilai_kutipan in _NILAI_KOSONG and _ada_indikasi_kutipan(teks):
        kosong.append("kutipan_tokoh")

    return kosong

def _cocokkan_kategori_terdekat(kategori_ai: str) -> str | None:
    """
    Validasi kategori_pdrb dari AI terhadap 51 daftar resmi.
    Menggunakan exact match terlebih dahulu, lalu fallback ke substring match 
    untuk mengatasi variasi teks/kapitalisasi. Mengembalikan None jika tidak cocok.
    """
    if not kategori_ai:
        return None
    kategori_lower = kategori_ai.strip().lower()
    for kat in DAFTAR_KATEGORI_PDRB:
        if kat.lower() == kategori_lower:
            return kat
    for kat in DAFTAR_KATEGORI_PDRB:
        if kategori_lower in kat.lower() or kat.lower() in kategori_lower:
            return kat
    return None

# ─── Buat Prompt ────────────────────────────────────────────────────────────────
def _buat_prompt(data_artikel: dict, max_chars: int, kategori_pdrb: str = "") -> str:
    teks = data_artikel.get('teks', '')[:max_chars]
    url = data_artikel.get('url', data_artikel.get('url_asli', '-'))
    judul = data_artikel.get('judul', 'Judul Tidak Diketahui')
    tanggal = data_artikel.get('tanggal', 'Tanggal Tidak Diketahui')
    kategori_pdrb = (kategori_pdrb or "").strip()

    if kategori_pdrb:
        # ── Kategori SUDAH pasti (dikirim dari Radar) ──
        blok_konteks_kategori = f"Kategori PDRB (SUDAH DITENTUKAN — gunakan sebagai konteks fokus analisis, JANGAN membuat kategori baru): {kategori_pdrb}"
        blok_daftar_key = """
        EKSTRAK KE DALAM JSON DENGAN 11 KEY WAJIB BERIKUT:
        1. "judul_dan_tanggal": Kombinasi judul asli berita dan tanggal publish.
        2. "sumber_dan_link": Nama media massa dan URL berita lengkap.
        3. "ringkasan_fenomena": rangkuman/ringkasan/penjelasan 4-5 Kalimat tentang penyebab kejadian, perubahan data angka, persentase, angka-angka penting (misal jumlah lokasi/daerah yang terdampak, jumlah yang dioptimalkan, dan sejenisnya), dan lain-lainya + beserta alasannya (pastikan dalam ringkasan sudah termasuk ada pernyataan narasumber yang diubah ke kalimat tidak langsung).
        4. "data_angka": WAJIB sebutkan SEMUA nilai kuantitatif yang muncul di teks — harga, persentase %, ton/kuintal/kg, hektar, jumlah unit/orang/korban, tanggal pencatatan data, DURASI WAKTU (mis. "24 jam operasional", "3 bulan pemulihan"), JUMLAH PIHAK/PESERTA/NEGARA TERLIBAT (mis. "800 peserta dari 29 negara"), dsb — dalam bentuk poin-poin singkat yang jelas konteksnya. SISIR seluruh teks kalimat demi kalimat — jangan hanya ambil satu angka lalu berhenti.
        5. "kutipan_tokoh": WAJIB kutip ulang SETIAP kalimat kutipan langsung yang ada di teks — ditandai tanda kutip "...", atau didahului/diikuti kata kerja pelaporan seperti ujarnya, katanya, ucapnya, sambungnya, ungkapnya, jelasnya, tuturnya, menurutnya, dsb. Jika lebih dari satu kutipan, tuliskan SEMUANYA (pisahkan dengan " | "). Sertakan nama & jabatan narasumber jika disebutkan.
        6. "lokasi_spesifik": Fokus area kejadian paling spesifik yang disebut di teks — kecamatan/pasar/desa di Magelang, ATAU jika artikel berskala provinsi/nasional, sebutkan lokasi paling spesifik yang memang ADA di teks (kota, provinsi, nama venue/gedung kegiatan, dsb).
        7. "intervensi_pemerintah": Sebutkan SEMUA kebijakan, program, mekanisme, atau tindakan pemerintah/instansi terkait fenomena tersebut — termasuk program rutin, RENCANA pembangunan/infrastruktur, PENGAJUAN anggaran ke pusat, maupun WACANA/KEKHAWATIRAN narasumber soal rencana kebijakan tertentu (meski belum final) — tulis dengan jelas kalau itu masih wacana/rencana.
        8. "periode_kejadian": Rentang waktu/tanggal relevan — termasuk tanggal pencatatan data, tanggal pelaksanaan kegiatan, proyeksi ke depan, atau perbandingan historis. Jika benar-benar tidak ada rentang waktu spesifik di isi teks, gunakan tanggal publikasi artikel ("Tanggal Web" di atas) sebagai upaya terakhir sebelum menjawab "Tidak ada informasi".
        9. "kata_kunci": 3 hashtags untuk mempermudah pencarian (contoh: #Beras #GagalPanen).
        10. "sentimen_dampak": Pilih salah satu: Positif / Negatif / Netral.
        11. "kategori_perbandingan": Pilih "y-on-y" (dibanding tahun sebelumnya), "q-to-q" (kuartal/bulan sebelumnya), "harga" (fluktuasi harian/mingguan), atau "Tidak ada informasi" (jika tidak ada perbandingan waktu sama sekali).
        """
        aturan_field_wajib = """
        a. Field yang TIDAK PERNAH boleh diisi "Tidak ada informasi" (WAJIB selalu terisi nyata): "judul_dan_tanggal", "sumber_dan_link", "ringkasan_fenomena", "kata_kunci", "sentimen_dampak".
        """
    else:
        # ── Kategori BELUM pasti (user paste URL manual) — AI harus menentukan ──
        daftar_kategori_str = "\n".join(f"        - {k}" for k in DAFTAR_KATEGORI_PDRB)
        blok_konteks_kategori = f"""Kategori PDRB: BELUM DITENTUKAN. Kamu WAJIB menentukan sendiri kategori PDRB yang PALING SESUAI dari daftar 51 kategori resmi BPS berikut. Pilih PERSIS SATU, salin PERSIS SAMA teksnya (termasuk huruf besar/kecil, tanda koma, dan spasi) TANPA modifikasi apapun, JANGAN membuat kategori baru di luar daftar ini:
{daftar_kategori_str}"""
        blok_daftar_key = """
        EKSTRAK KE DALAM JSON DENGAN 12 KEY WAJIB BERIKUT:
        1. "kategori_pdrb": Salin PERSIS SATU teks kategori dari daftar 51 kategori PDRB di atas (harus sama persis, tidak boleh disingkat/dimodifikasi).
        2. "judul_dan_tanggal": Kombinasi judul asli berita dan tanggal publish.
        3. "sumber_dan_link": Nama media massa dan URL berita lengkap.
        4. "ringkasan_fenomena": rangkuman/ringkasan/penjelasan 4-5 Kalimat tentang penyebab kejadian, perubahan data angka, persentase, angka-angka penting (misal jumlah lokasi/daerah yang terdampak, jumlah yang dioptimalkan, dan sejenisnya), dan lain-lainya + beserta alasannya (pastikan dalam ringkasan sudah termasuk ada pernyataan narasumber yang diubah ke kalimat tidak langsung).
        5. "data_angka": WAJIB sebutkan SEMUA nilai kuantitatif yang muncul di teks — harga, persentase %, ton/kuintal/kg, hektar, jumlah unit/orang/korban, tanggal pencatatan data, DURASI WAKTU, JUMLAH PIHAK/PESERTA/NEGARA TERLIBAT, dsb — dalam bentuk poin-poin singkat yang jelas konteksnya. SISIR seluruh teks kalimat demi kalimat.
        6. "kutipan_tokoh": WAJIB kutip ulang SETIAP kalimat kutipan langsung yang ada di teks — ditandai tanda kutip "...", atau didahului/diikuti kata kerja pelaporan seperti ujarnya, katanya, ucapnya, sambungnya, ungkapnya, jelasnya, tuturnya, menurutnya, dsb. Jika lebih dari satu kutipan, tuliskan SEMUANYA (pisahkan dengan " | "). Sertakan nama & jabatan narasumber jika disebutkan.
        7. "lokasi_spesifik": Fokus area kejadian paling spesifik yang disebut di teks.
        8. "intervensi_pemerintah": Sebutkan SEMUA kebijakan, program, mekanisme, atau tindakan pemerintah/instansi terkait fenomena tersebut — termasuk program rutin, RENCANA pembangunan/infrastruktur, PENGAJUAN anggaran ke pusat, maupun WACANA/KEKHAWATIRAN narasumber soal rencana kebijakan tertentu (meski belum final).
        9. "periode_kejadian": Rentang waktu/tanggal relevan. Jika benar-benar tidak ada rentang waktu spesifik, gunakan tanggal publikasi artikel sebagai upaya terakhir.
        10. "kata_kunci": 3 hashtags untuk mempermudah pencarian.
        11. "sentimen_dampak": Pilih salah satu: Positif / Negatif / Netral.
        12. "kategori_perbandingan": Pilih "y-on-y", "q-to-q", "harga", atau "Tidak ada informasi".
        """
        aturan_field_wajib = """
        a. Field yang TIDAK PERNAH boleh diisi "Tidak ada informasi" (WAJIB selalu terisi nyata): "kategori_pdrb", "judul_dan_tanggal", "sumber_dan_link", "ringkasan_fenomena", "kata_kunci", "sentimen_dampak".
        """

    return f"""
        Anda adalah Analis Data Ahli yang Handal dan Professional di Badan Pusat Statistik (BPS) Kota Magelang.
        Tugas Anda adalah menganalisis teks artikel berita dan mengekstrak fenomena yang relevan untuk data statistik DENGAN SUPER LENGKAP, SUPER DETAIL, DAN SUPER TEPAT DAN BENAR TANPA ADA YANG TERTINGGAL.
        LANGKAH WAJIB SEBELUM MENJAWAB:
        Baca ULANG seluruh teks artikel di bawah dari kalimat pertama sampai kalimat terakhir, satu per satu.
        JANGAN hanya berdasar judul atau 1-2 paragraf pertama — banyak angka dan kutipan penting justru muncul di paragraf tengah/akhir.
        JANGAN PERNAH menjawab "Tidak ada informasi" secara terburu-buru. Untuk SETIAP field, kamu WAJIB membaca ulang teks minimal 2 kali sebelum menyimpulkan sebuah data benar-benar tidak ada.

        Data Artikel Sumber:
        {blok_konteks_kategori}
        URL: {url}
        Judul Web: {judul}
        Tanggal Web: {tanggal}

        Teks Artikel:
        {teks}
        {blok_daftar_key}
        ATURAN WAJIB TENTANG KAPAN BOLEH MENJAWAB "Tidak ada informasi":
        {aturan_field_wajib}
        b. Field yang SANGAT JARANG boleh diisi "Tidak ada informasi" karena hampir selalu ada sesuatu yang bisa diekstrak meski implisit: "data_angka", "kutipan_tokoh", "lokasi_spesifik", "intervensi_pemerintah", "periode_kejadian". SEBELUM menjawab "Tidak ada informasi" untuk field ini: (1) baca ulang teks minimal 2x, (2) jika data EKSPLISIT benar-benar tidak ada, WAJIB cari dan tuliskan POTENSI/IMPLIKASI/WACANA/KEKHAWATIRAN yang tersirat di teks sebagai gantinya (harus tetap bersumber dari sesuatu yang disebut di teks, No Hallucination). Contoh: kalau tidak ada kebijakan pemerintah yang benar-benar berjalan tapi ada kekhawatiran narasumber soal rencana kebijakan tertentu, tulis itu di field intervensi_pemerintah dengan jelas menyebutnya "potensi/wacana kebijakan", bukan kebijakan final. HANYA isi "Tidak ada informasi" jika setelah dicek ulang benar-benar nihil total, tanpa secuil pun petunjuk implisit.
        c. Field yang WAJAR/NORMAL diisi "Tidak ada informasi" jika memang tidak ada: HANYA "kategori_perbandingan" — banyak artikel murni tidak membahas perbandingan waktu sama sekali, dan itu valid apa adanya.
        d. Jangan pernah membuat-buat data (No Hallucination) — potensi/implikasi pada poin b tetap HARUS bersumber dari sesuatu yang benar-benar disebut/tersirat di teks, bukan asumsi bebas dari luar teks.
        e. SELF-CHECK WAJIB SEBELUM MENGIRIM JAWABAN AKHIR: baca ulang SEMUA field yang kamu isi. Field-field yang disebut di poin (a) di atas TIDAK BOLEH berisi "Tidak ada informasi" dalam kondisi apapun — bahkan untuk artikel yang sangat pendek atau minim detail, kamu WAJIB tetap memberikan jawaban ringkas berdasarkan apa yang tersedia (judul, lead paragraf, konteks umum artikel). Menjawab "Tidak ada informasi" pada field-field di poin (a) dianggap JAWABAN GAGAL dan tidak akan diterima.
        f. Balas HANYA dengan JSON murni tanpa penjelasan, tanpa markdown, tanpa backtick.
        """

def _buat_prompt_koreksi(data_artikel: dict, max_chars: int, field_kosong: list[str]) -> str:
    """
    Prompt susulan (retry) khusus meminta AI memperbaiki field yang masih
    "Tidak ada informasi" padahal termasuk FIELD_WAJIB_TERISI. Dipanggil
    otomatis oleh ekstrak_fenomena_ai() setelah jawaban pertama gagal
    memenuhi aturan wajib -- ini jaring pengaman di level kode, tidak
    bergantung 100% pada kepatuhan AI terhadap instruksi prompt saja.
    """
    teks = data_artikel.get('teks', '')[:max_chars]
    judul = data_artikel.get('judul', 'Judul Tidak Diketahui')
    label_field = {
        "judul_dan_tanggal": "judul_dan_tanggal (kombinasi judul asli & tanggal publish artikel)",
        "sumber_dan_link":   "sumber_dan_link (nama media & URL berita)",
        "ringkasan_fenomena":"ringkasan_fenomena (4-5 kalimat inti fenomena di artikel)",
        "kata_kunci":        "kata_kunci (3 hashtag relevan)",
        "sentimen_dampak":   "sentimen_dampak (pilih persis: Positif / Negatif / Netral)",
        "data_angka":        "data_angka (SEMUA nilai angka: harga Rp, persentase %, berat kg/ton, dsb -- SISIR ULANG teks kalimat demi kalimat dari awal sampai akhir, jangan lewatkan satupun)",
        "kutipan_tokoh":     "kutipan_tokoh (SEMUA kalimat kutipan langsung bertanda kutip \"...\" atau didahului/diikuti kata ujarnya/katanya/ucapnya/imbuhnya dsb -- salin PERSIS kalimatnya, sertakan nama & jabatan narasumber jika disebutkan)",
    }
    daftar_diminta = "\n".join(f'        - "{f}": {label_field.get(f, f)}' for f in field_kosong)
    return f"""
        Kamu sebelumnya mengekstrak artikel berita ini, tapi field berikut KELIRU dijawab "Tidak ada informasi"
        padahal field tersebut WAJIB selalu bisa diisi dari artikel manapun (bersifat deskriptif dasar,
        bukan data yang mungkin memang tidak ada).

        FIELD YANG WAJIB KAMU PERBAIKI SEKARANG:
        {daftar_diminta}

        Judul Artikel: {judul}

        Teks Artikel (baca ulang dengan teliti):
        {teks}

        INSTRUKSI:
        - Isi HANYA field-field yang diminta di atas dengan analisis nyata dari teks.
        - TIDAK BOLEH menjawab "Tidak ada informasi" lagi untuk field-field ini — kalau artikel pendek/minim
          detail, tetap WAJIB berikan jawaban minimal yang masuk akal berdasarkan judul & isi yang tersedia
          (misal ringkasan minimal 1-2 kalimat inti dari judul & paragraf pertama).
        - Balas HANYA dengan JSON murni berisi field yang diminta saja, tanpa penjelasan, tanpa markdown.
        """

# ─── Caller: Groq ───────────────────────────────────────────────────────────────
def _call_groq(api_key: str, model_id: str, prompt: str, max_tokens: int) -> str:
    client = Groq(api_key=api_key)
    kwargs = dict(
        model=model_id,
        messages=[
            {"role": "system", "content": "Kamu analis data BPS. Balas HANYA JSON murni yang valid."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    if "gpt-oss" in model_id:
        kwargs["reasoning_effort"] = "low"
    resp = client.chat.completions.create(**kwargs)
    u = resp.usage
    logger.debug(f"[Token] in:{u.prompt_tokens} out:{u.completion_tokens} total:{u.total_tokens}")
    return resp.choices[0].message.content

# ─── Caller: Gemini ─────────────────────────────────────────────────────────────
def _call_gemini(api_key: str, model_id: str, prompt: str, thinking: str = "level", max_output_tokens: int = 5000) -> str:
    """
    PENTING: Gemini 3.x (3.1 Flash-Lite, 3.5 Flash) pakai parameter thinking_level,
    BUKAN thinking_budget seperti Gemini 2.x lama. Gemma 4 tidak mendukung parameter
    thinking sama sekali, jadi harus di-skip total (thinking="none").
    """
    client = google_genai.Client(api_key=api_key)
    config_kwargs = dict(
        temperature=0.1,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
    )
    if thinking == "level":
        config_kwargs["thinking_config"] = google_types.ThinkingConfig(thinking_level="medium")
    elif thinking == "budget":
        config_kwargs["thinking_config"] = google_types.ThinkingConfig(thinking_budget=0)
    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=google_types.GenerateContentConfig(**config_kwargs)
    )
    teks = resp.text if resp.text is not None else ""
    if not teks.strip():
        raise ValueError("Gemini mengembalikan respons kosong")
    return teks

# ─── Caller: Cerebras (OpenAI-compatible) ──────────────────────────────────────
def _call_cerebras(api_key: str, model_id: str, prompt: str, max_tokens: int) -> str:
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.cerebras.ai/v1"
    )
    kwargs = dict(
        model=model_id,
        messages=[
            {"role": "system", "content": "Kamu analis data BPS. Balas HANYA JSON murni yang valid."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    if "gpt-oss" in model_id:
        kwargs["reasoning_effort"] = "low"
    resp = client.chat.completions.create(**kwargs)
    teks = resp.choices[0].message.content
    if teks is None or not teks.strip():
        raise ValueError("Cerebras mengembalikan respons kosong")
    return teks

# ─── Caller: Mistral ─────────────────────────────────────────────────────────────
def _call_mistral(api_key: str, model_id: str, prompt: str, max_tokens: int) -> str:
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.mistral.ai/v1"
    )
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": "Kamu analis data BPS. Balas HANYA JSON murni yang valid."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    teks = resp.choices[0].message.content
    if teks is None or not teks.strip():
        raise ValueError("Mistral mengembalikan respons kosong")
    return teks

def _panggil_model(provider: str, api_key: str, model_id: str, prompt: str, cfg: dict, max_tokens: int) -> str:
    """Dispatcher tunggal ke provider yang sesuai -- dipakai baik untuk percobaan
    utama maupun untuk retry koreksi field wajib, supaya logic tidak dobel."""
    if provider == "groq":
        return _call_groq(api_key, model_id, prompt, max_tokens=max_tokens)
    elif provider == "gemini":
        return _call_gemini(api_key, model_id, prompt, cfg.get("thinking", "level"), max_output_tokens=max_tokens)
    elif provider == "cerebras":
        return _call_cerebras(api_key, model_id, prompt, max_tokens=max_tokens)
    elif provider == "mistral":
        return _call_mistral(api_key, model_id, prompt, max_tokens=max_tokens)
    else:
        raise ValueError(f"Provider tidak dikenal: {provider}")

# ─── Fungsi Utama ───────────────────────────────────────────────────────────────
def ekstrak_fenomena_ai(keys: dict, data_artikel: dict, kategori_pdrb: str = "") -> dict:
    """
    kategori_pdrb:
      - Diisi (non-kosong) -> dikirim sebagai konteks PASTI ke AI (biasanya dari Tab Radar).
      - Kosong ("")         -> AI menentukan sendiri dari 51 kategori resmi (biasanya dari
                                paste URL manual). Hasil tebakan AI tetap divalidasi terhadap
                                daftar resmi; kalau tidak cocok, dikosongkan untuk staf koreksi.
    """
    import random
    kategori_pdrb = (kategori_pdrb or "").strip()

    for cfg in MODEL_STACK:
        provider = cfg["provider"]
        api_key_raw = keys.get(provider, "")
        pool_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]

        if not pool_keys:
            logger.debug(f"[Skip] {cfg['nama']}: API key kosong.")
            continue

        logger.debug(f"[Mencoba] {cfg['nama']} (Ada {len(pool_keys)} Kunci Amunisi)...")
        prompt = _buat_prompt(data_artikel, cfg["max_chars"], kategori_pdrb)
        max_tokens = MAX_TOKENS_EKSTRAKSI.get(provider, 3000)

        random.shuffle(pool_keys)

        for idx, api_key in enumerate(pool_keys):
            try:
                teks_json = _panggil_model(provider, api_key, cfg["model_id"], prompt, cfg, max_tokens)
                teks_bersih = teks_json.strip().replace('```json', '').replace('```', '').strip()
                hasil = json.loads(teks_bersih)
                if not isinstance(hasil, dict):
                    raise ValueError(
                        f"AI mengembalikan JSON bertipe {type(hasil).__name__}, seharusnya objek/dict"
                    )
                # ── Tentukan/validasi kategori_pdrb ──
                if kategori_pdrb:
                    hasil["kategori_pdrb"] = kategori_pdrb   # dari input pasti, override apapun jawaban AI
                else:
                    kategori_ai = str(hasil.get("kategori_pdrb", "")).strip()
                    kategori_valid = _cocokkan_kategori_terdekat(kategori_ai)
                    if kategori_valid:
                        hasil["kategori_pdrb"] = kategori_valid
                    else:
                        logger.warning(
                            f"[Kategori] {cfg['nama']}: AI menjawab kategori '{kategori_ai}' yang tidak "
                            f"cocok dengan daftar 51 kategori resmi. Dikosongkan untuk dikoreksi manual staf."
                        )
                        hasil["kategori_pdrb"] = ""

                # Safety-net: Pemicu retry jika field wajib kosong, atau jika regex mendeteksi 
                # adanya data angka/kutipan yang terlewat oleh AI (via _cek_field_kosong()).
                teks_sumber = data_artikel.get("teks", "")
                field_kosong = _cek_field_kosong(hasil, teks_sumber)
                if field_kosong:
                    logger.warning(f"[Koreksi] {cfg['nama']}: field kosong {field_kosong}, retry sekali...")
                    try:
                        max_tokens_koreksi = 2500 if any(f in field_kosong for f in ("data_angka", "kutipan_tokoh")) else 1500
                        prompt_koreksi = _buat_prompt_koreksi(data_artikel, cfg["max_chars"], field_kosong)
                        teks_koreksi = _panggil_model(provider, api_key, cfg["model_id"], prompt_koreksi, cfg, max_tokens=max_tokens_koreksi)
                        teks_koreksi_bersih = teks_koreksi.strip().replace('```json', '').replace('```', '').strip()
                        hasil_koreksi = json.loads(teks_koreksi_bersih)
                        if not isinstance(hasil_koreksi, dict):
                            raise ValueError(
                                f"AI (koreksi) mengembalikan JSON bertipe {type(hasil_koreksi).__name__}, seharusnya objek/dict"
                            )
                        for f in field_kosong:
                            nilai_baru = str(hasil_koreksi.get(f, "")).strip()
                            if nilai_baru and nilai_baru.lower() not in _NILAI_KOSONG:
                                hasil[f] = nilai_baru
                        sisa_kosong = _cek_field_kosong(hasil, teks_sumber)
                        if sisa_kosong:
                            logger.warning(f"[Koreksi Belum Tuntas] {cfg['nama']}: field {sisa_kosong} masih kosong walau sudah di-retry.")
                        else:
                            logger.info(f"[Koreksi Berhasil] {cfg['nama']}: semua field wajib terisi setelah retry.")
                    except Exception as e_koreksi:
                        logger.warning(f"[Koreksi Gagal] {cfg['nama']}: retry gagal ({str(e_koreksi)[:100]}), lanjut pakai hasil awal.")

                hasil["_model_digunakan"] = cfg["nama"]
                logger.info(f"[Sukses] {cfg['nama']} (Memakai kunci ke-{idx+1})")
                return {"status": "sukses", "data": hasil}

            except json.JSONDecodeError as e:
                logger.error(f"[Error JSON] {cfg['nama']}: {e}")
                break

            except Exception as e:
                err = str(e).lower()
                is_rate_limit = any(k in err for k in [
                    "429", "rate limit", "quota", "exhausted", "too many requests"
                ])
                is_not_found = "404" in err or "not found" in err
                is_payload_besar = "413" in err or "too large" in err
                if is_rate_limit:
                    logger.warning(f"[Limit] Kunci ke-{idx+1} habis untuk {cfg['nama']}! Coba Kunci Cadangan {provider}...")
                    time.sleep(1)
                    continue
                elif is_not_found:
                    logger.error(format_model_404_message(cfg["nama"], cfg["model_id"], "ekstraksi variabel"))
                    break
                elif is_payload_besar:
                    logger.warning(f"[Payload Terlalu Besar] {cfg['nama']}: artikel terlalu panjang untuk model ini, pindah ke model berikutnya...")
                    break
                else:
                    logger.error(f"[Error] {cfg['nama']}: {err[:120]}")
                    break

    logger.error("Seluruh model dan seluruh API Key error/limit saat ekstraksi. Tidak ada yang berhasil.")
    return {
        "status": "error",
        "pesan" : "Seluruh model dan seluruh 25 API Key error/limit. Coba lagi nanti!"
    }