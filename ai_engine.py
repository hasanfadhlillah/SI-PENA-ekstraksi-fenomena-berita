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
    format_model_404_message,
)
from radar.logger_config import get_logger

logger = get_logger(__name__)

# ─── Prompt ────────────────────────────────────────────────────────────────
def _buat_prompt(data_artikel: dict, max_chars: int, kategori_pdrb: str = "") -> str:
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
        JANGAN PERNAH menjawab "Tidak ada informasi" secara terburu-buru. Untuk SETIAP field, kamu WAJIB membaca ulang teks minimal 2 kali sebelum menyimpulkan sebuah data benar-benar tidak ada. Ikuti ATURAN di bagian bawah prompt ini soal kapan boleh dan tidak boleh menjawab "Tidak ada informasi".

        Data Artikel Sumber:
        Kategori PDRB (SUDAH DITENTUKAN — gunakan sebagai konteks fokus analisis, JANGAN membuat kategori baru): {kategori_pdrb or "Tidak diketahui"}
        URL: {url}
        Judul Web: {judul}
        Tanggal Web: {tanggal}

        Teks Artikel:
        {teks}

        EKSTRAK KE DALAM JSON DENGAN 11 KEY WAJIB BERIKUT:
        1. "judul_dan_tanggal": Kombinasi judul asli berita dan tanggal publish.
        2. "sumber_dan_link": Nama media massa dan URL berita lengkap.
        3. "ringkasan_fenomena": rangkuman/ringkasan/penjelasan 4-5 Kalimat tentang penyebab kejadian, perubahan data angka, persentase, angka-angka penting (misal jumlah lokasi/daerah yang terdampak, jumlah yang dioptimalkan, dan sejenisnya), dan lain-lainya + beserta alasannya (pastikan dalam ringkasan sudah termasuk ada pernyataan narasumber yang diubah ke kalimat tidak langsung).
        4. "data_angka": WAJIB sebutkan SEMUA nilai kuantitatif yang muncul di teks — harga, persentase %, ton/kuintal/kg, hektar, jumlah unit/orang/korban, tanggal pencatatan data, DURASI WAKTU (mis. "24 jam operasional", "3 bulan pemulihan"), JUMLAH PIHAK/PESERTA/NEGARA TERLIBAT (mis. "800 peserta dari 29 negara"), dsb — dalam bentuk poin-poin singkat yang jelas konteksnya. Contoh format: "5,3 juta ton (stok CBP per Juni 2026)"; "800 dolar AS per ton (harga lama paraksailin)". SISIR seluruh teks kalimat demi kalimat — jangan hanya ambil satu angka lalu berhenti.
        5. "kutipan_tokoh": WAJIB kutip ulang SETIAP kalimat kutipan langsung yang ada di teks — ditandai tanda kutip "...", atau didahului/diikuti kata kerja pelaporan seperti ujarnya, katanya, ucapnya, sambungnya, ungkapnya, jelasnya, tuturnya, menurutnya, dsb. Jika dalam satu teks ada lebih dari satu kutipan (umum terjadi), tuliskan SEMUANYA secara berurutan (pisahkan dengan " | "), bukan cuma salah satu. Sertakan nama dan jabatan narasumber jika disebutkan.
        6. "lokasi_spesifik": Fokus area kejadian paling spesifik yang disebut di teks — bisa nama kecamatan/pasar/desa di Magelang, ATAU jika artikel berskala provinsi/nasional dan tidak menyebut lokasi sespesifik itu, sebutkan lokasi paling spesifik yang memang ADA di teks (nama kota, provinsi, atau bahkan nama venue/gedung kegiatan seperti tempat pameran/kantor kementerian).
        7. "intervensi_pemerintah": Sebutkan SEMUA kebijakan, program, mekanisme, atau tindakan pemerintah/instansi yang disebutkan di teks untuk merespons ATAU mengelola fenomena tersebut — termasuk program yang SEDANG BERJALAN/rutin (CBP, operasi pasar, subsidi, bansos, dsb), RENCANA pembangunan fasilitas/infrastruktur, PENGAJUAN anggaran ke pusat, maupun WACANA/KEKHAWATIRAN narasumber soal rencana kebijakan tertentu (meski belum final/belum jadi kebijakan resmi) — tulis dengan jelas kalau itu masih berupa wacana/rencana, jangan disamakan dengan kebijakan yang sudah berjalan.
        8. "periode_kejadian": Sebutkan rentang waktu/tanggal yang relevan — termasuk tanggal pencatatan data (mis. "per 23 Juni 2026"), tanggal pelaksanaan kegiatan/acara yang dibahas (mis. "15-18 April 2026" untuk sebuah pameran), proyeksi ke depan, maupun perbandingan historis — bukan hanya jika ada frasa eksplisit "triwulan X". Jika benar-benar tidak ada rentang waktu spesifik di isi teks, gunakan tanggal publikasi artikel ("Tanggal Web" di atas) sebagai upaya terakhir sebelum menjawab "Tidak ada informasi".
        9. "kata_kunci": 3-5 hashtags untuk mempermudah pencarian (contoh: #Beras #GagalPanen).
        10. "sentimen_dampak": Pilih salah satu: Positif / Negatif / Netral.
        11. "kategori_perbandingan": Analisis narasi dan kutipan narasumber di dalam teks untuk menentukan satu perbandingan fenomena secara eksklusif, lalu pilih "y-on-y" (jika dibandingkan dengan tahun sebelumnya), "q-to-q" (kuartal/bulan sebelumnya), "harga" (fluktuasi harian/mingguan), atau "Tidak ada informasi" (jika tidak ada perbandingan waktu sama sekali).

        ATURAN WAJIB TENTANG KAPAN BOLEH MENJAWAB "Tidak ada informasi":
        a. Field yang TIDAK PERNAH boleh diisi "Tidak ada informasi" (karena logis PASTI bisa dianalisis dari artikel manapun): "judul_dan_tanggal", "sumber_dan_link", "ringkasan_fenomena", "kata_kunci", "sentimen_dampak". Kelima field ini WAJIB selalu terisi dengan analisis nyata dari teks.
        b. Field yang SANGAT JARANG boleh diisi "Tidak ada informasi" karena hampir selalu ada sesuatu yang bisa diekstrak meski implisit: "data_angka", "kutipan_tokoh", "lokasi_spesifik", "intervensi_pemerintah", "periode_kejadian". Untuk kelima field ini, SEBELUM menjawab "Tidak ada informasi": (1) baca ulang teks minimal 2x, (2) jika data EKSPLISIT benar-benar tidak ada, WAJIB cari dan tuliskan POTENSI/IMPLIKASI/WACANA/KEKHAWATIRAN yang tersirat di teks sebagai gantinya (harus tetap bersumber dari sesuatu yang disebut di teks, No Hallucination). Contoh: kalau tidak ada kebijakan pemerintah yang benar-benar berjalan tapi ada kekhawatiran narasumber soal rencana kebijakan tertentu, tulis itu di field 7 dengan jelas menyebutnya "potensi/wacana kebijakan", bukan kebijakan final. HANYA isi "Tidak ada informasi" jika setelah dicek ulang benar-benar nihil total, tanpa secuil pun petunjuk implisit.
        c. Field yang WAJAR/NORMAL diisi "Tidak ada informasi" jika memang tidak ada: HANYA "kategori_perbandingan" — banyak artikel murni tidak membahas perbandingan waktu sama sekali, dan itu valid apa adanya.
        d. Jangan pernah membuat-buat data (No Hallucination) — potensi/implikasi yang dituliskan pada poin b tetap HARUS bersumber dari sesuatu yang benar-benar disebut/tersirat di teks, bukan asumsi bebas dari luar teks.
        e. Balas HANYA dengan JSON murni tanpa penjelasan, tanpa markdown, tanpa backtick.
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
def ekstrak_fenomena_ai(keys: dict, data_artikel: dict, kategori_pdrb: str = "") -> dict:
    import random
    
    for cfg in MODEL_STACK:
        provider = cfg["provider"]
        api_key_raw = keys.get(provider, "")
        
        pool_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]

        if not pool_keys:
            logger.debug(f"[Skip] {cfg['nama']}: API key kosong.")
            continue

        logger.debug(f"[Mencoba] {cfg['nama']} (Ada {len(pool_keys)} Kunci Amunisi)...")
        prompt = _buat_prompt(data_artikel, cfg["max_chars"], kategori_pdrb)   # <-- kategori_pdrb dioper
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
                hasil["kategori_pdrb"]    = kategori_pdrb   # <-- BARU: dari input pasti, bukan tebakan AI
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