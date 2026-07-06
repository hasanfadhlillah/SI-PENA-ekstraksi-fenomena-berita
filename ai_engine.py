# File: ai_engine.py
import json
import time
import openai
from groq import Groq
from google import genai as google_genai
from google.genai import types as google_types

from radar.model_stack import (
    AI_MODEL_CATALOG as MODEL_STACK,
    MAX_TOKENS_EKSTRAKSI,
    format_model_404_message,   # FIX #17
)
from radar.logger_config import get_logger

logger = get_logger(__name__)

# ─── Buat Prompt ────────────────────────────────────────────────────────────────
def _buat_prompt(data_artikel: dict, max_chars: int) -> str:
    teks = data_artikel.get('teks', '')[:max_chars]
    url = data_artikel.get('url', data_artikel.get('url_asli', '-'))
    judul = data_artikel.get('judul', 'Judul Tidak Diketahui')
    tanggal = data_artikel.get('tanggal', 'Tanggal Tidak Diketahui')

    return f"""
        Anda adalah Analis Data Ahli yang Handal dan Professional di Badan Pusat Statistik (BPS) Kota Magelang.
        Tugas Anda adalah menganalisis teks artikel berita dan mengekstrak fenomena yang relevan untuk data statistik DENGAN SUPER LENGKAP, SUPER DETAIL, DAN SUPER TEPAT DAN BENAR TANPA ADA YANG TERTINGGAL.
        LANGKAH WAJIB SEBELUM MENJAWAB:
        Baca ULANG seluruh teks artikel di bawah dari kalimat pertama sampai kalimat terakhir, satu per satu.
        JANGAN hanya berdasar judul atau 1-2 paragraf pertama — banyak angka dan kutipan penting justru muncul di paragraf tengah/akhir.
        
        Data Artikel Sumber:
        URL: {url}
        Judul Web: {judul}
        Tanggal Web: {tanggal}
        
        Teks Artikel:
        {teks}
        
        EKSTRAK KE DALAM JSON DENGAN 12 KEY WAJIB BERIKUT:
        1. "tema_topik": Kategori utama (misal Inflasi, Pertanian, Bencana Alam, Pariwisata, Kemiskinan, Ketenagakerjaan, dsb).
        2. "judul_dan_tanggal": Kombinasi judul asli berita dan tanggal publish.
        3. "sumber_dan_link": Nama media massa dan URL berita lengkap.
        4. "ringkasan_fenomena": rangkuman/ringkasan/penjelasan 4-5 Kalimat tentang penyebab kejadian, perubahan data angka, persentase, angka-angka penting (misal jumlah lokasi/daerah yang terdampak, jumlah yang dioptimalkan, dan sejenisnya), dan lain-lainya + beserta alasannya (pastikan dalam ringkasan sudah termasuk ada pernyataan narasumber yang diubah ke kalimat tidak langsung).
        5. "data_angka": WAJIB sebutkan SEMUA nilai kuantitatif yang muncul di teks (harga, persentase %, ton/kuintal/kg, hektar, jumlah unit/orang/korban, tanggal pencatatan data, dsb) dalam bentuk poin-poin singkat yang jelas konteksnya. Contoh format: "5,3 juta ton (stok CBP per Juni 2026)"; "1,02 juta ton (realisasi penyaluran CBP 2026)"; "3,23 juta ton (pengadaan setara beras dalam negeri 2026)". SISIR seluruh teks kalimat demi kalimat — jangan hanya ambil satu angka lalu berhenti. Field ini HANYA boleh diisi "Tidak ada informasi" jika setelah dibaca ulang benar-benar TIDAK ADA satupun angka di seluruh teks.
        6. "kutipan_tokoh": WAJIB kutip ulang SETIAP kalimat kutipan langsung yang ada di teks — ditandai tanda kutip "...", atau didahului/diikuti kata kerja pelaporan seperti ujarnya, katanya, ucapnya, sambungnya, ungkapnya, jelasnya, tuturnya, dsb. Jika dalam satu teks ada lebih dari satu kutipan (umum terjadi), tuliskan SEMUANYA secara berurutan (pisahkan dengan " | "), bukan cuma salah satu. Sertakan nama dan jabatan narasumber jika disebutkan. Field ini HANYA boleh diisi "Tidak ada informasi" jika setelah dibaca ulang benar-benar TIDAK ADA kutipan langsung di teks.
        7. "lokasi_spesifik": Fokus area kejadian, misal nama kecamatan, pasar, atau desa, atau yang lainnya di Magelang.
        8. "intervensi_pemerintah": Sebutkan SEMUA kebijakan, program, mekanisme, atau tindakan pemerintah/instansi yang disebutkan di teks untuk merespons ATAU mengelola fenomena tersebut — termasuk program yang SEDANG BERJALAN/rutin (misal Cadangan Beras Pemerintah/CBP, operasi pasar, pengadaan Bulog, subsidi, bantuan sosial, pemantauan harga terhadap HET, dsb), bukan hanya tindakan baru yang diumumkan secara eksplisit.
        9. "periode_kejadian": Sebutkan rentang waktu/tanggal yang relevan dengan fenomena — termasuk tanggal pencatatan data yang disebut di teks (misal "per 23 Juni 2026"), proyeksi ke depan (misal "diperkirakan cukup sampai Mei 2027"), maupun perbandingan historis (misal "dibandingkan kondisi El Nino 2023") — bukan hanya jika ada frasa eksplisit "triwulan X".
        10. "kata_kunci": 3-5 hashtags untuk mempermudah pencarian (contoh: #Beras #GagalPanen).
        11. "sentimen_dampak": Pilih salah satu: Positif / Negatif / Netral.
        12. "kategori_perbandingan": Analisis narasi dan kutipan narasumber di dalam teks untuk menentukan satu perbandingan fenomena secara eksklusif, lalu pilih "y-on-y" (jika dibandingkan dengan tahun sebelumnya), "q-to-q" (kuartal/bulan sebelumnya), "harga" (fluktuasi harian/mingguan), atau "Tidak ada informasi" (jika tidak ada perbandingan waktu sama sekali).
        
        ATURAN:
        a. SEBELUM mengisi field manapun dengan "Tidak ada informasi", cek ULANG dua kali ke teks aslinya — jangan terburu-buru menyimpulkan tidak ada, terutama untuk field 5 (data_angka), 6 (kutipan_tokoh), 8 (intervensi_pemerintah), dan 9 (periode_kejadian) yang sering terlewat padahal datanya ada.
        b. Jika setelah dicek ulang data benar-benar tidak ada di teks, baru isi dengan "Tidak ada informasi".
        c. Jangan pernah membuat-buat data (No Hallucination).
        d. Balas HANYA dengan JSON murni tanpa penjelasan, tanpa markdown, tanpa backtick.
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
 
# ─── Fungsi Utama ───────────────────────────────────────────────────────────────
def ekstrak_fenomena_ai(keys: dict, data_artikel: dict) -> dict:
    import random
    
    for cfg in MODEL_STACK:
        provider = cfg["provider"]
        api_key_raw = keys.get(provider, "")
        
        pool_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]
 
        if not pool_keys:
            logger.debug(f"[Skip] {cfg['nama']}: API key kosong.")
            continue
 
        logger.debug(f"[Mencoba] {cfg['nama']} (Ada {len(pool_keys)} Kunci Amunisi)...")
        prompt = _buat_prompt(data_artikel, cfg["max_chars"])
        max_tokens = MAX_TOKENS_EKSTRAKSI.get(provider, 3000)
        
        random.shuffle(pool_keys)
 
        for idx, api_key in enumerate(pool_keys):
            try:
                if provider == "groq":
                    teks_json = _call_groq(api_key, cfg["model_id"], prompt, max_tokens=max_tokens)
                elif provider == "gemini":
                    teks_json = _call_gemini(api_key, cfg["model_id"], prompt, cfg.get("thinking", "level"), max_output_tokens=max_tokens)
                elif provider == "cerebras":
                    teks_json = _call_cerebras(api_key, cfg["model_id"], prompt, max_tokens=max_tokens)
                elif provider == "mistral":
                    teks_json = _call_mistral(api_key, cfg["model_id"], prompt, max_tokens=max_tokens)
                else:
                    break
     
                teks_bersih = teks_json.strip().replace('```json', '').replace('```', '').strip()
     
                hasil = json.loads(teks_bersih)
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
     
                if is_rate_limit:
                    logger.warning(f"[Limit] Kunci ke-{idx+1} habis untuk {cfg['nama']}! Coba Kunci Cadangan {provider}...")
                    time.sleep(1)
                    continue
                elif is_not_found:
                    # FIX #17: log level ERROR dengan pesan standar, supaya
                    # kegagalan model tidak lagi "senyap" — langsung menonjol
                    # di tab "Logs" Hugging Face Spaces.
                    logger.error(format_model_404_message(cfg["nama"], cfg["model_id"], "ekstraksi 12 variabel"))
                    break
                else:
                    logger.error(f"[Error] {cfg['nama']}: {err[:120]}")
                    break
 
    logger.error("Seluruh model dan seluruh API Key error/limit saat ekstraksi. Tidak ada yang berhasil.")
    return {
        "status": "error",
        "pesan" : "Seluruh model dan seluruh 25 API Key error/limit. Coba lagi nanti!"
    }