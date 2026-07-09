"""
Katalog model AI bersama untuk SI-PENA RADAR — satu sumber kebenaran
untuk urutan fallback model & budget token (ekstraksi vs screening).
Field "max_chars" dipakai ai_engine.py untuk memotong teks sebelum
masuk prompt.
"""
AI_MODEL_CATALOG = [
    {
    "nama"      : "Groq — GPT-OSS 120B",
    "provider"  : "groq",
    "model_id"  : "openai/gpt-oss-120b",
    "max_chars" : 6000,
    },
    {
        "nama"      : "Google — Gemini 3.1 Flash-Lite",
        "provider"  : "gemini",
        "model_id"  : "gemini-3.1-flash-lite",
        "max_chars" : 10000,
        "thinking"  : "level",
    },
    {
        "nama"      : "Google — Gemini 3.5 Flash",
        "provider"  : "gemini",
        "model_id"  : "gemini-3.5-flash",
        "max_chars" : 10000,
        "thinking"  : "level",
    },
    {
        "nama"      : "Google — Gemma 4 26B",
        "provider"  : "gemini",
        "model_id"  : "gemma-4-26b-a4b-it",
        "max_chars" : 10000,
        "thinking"  : "none",
    },
    {
        "nama"      : "Google — Gemma 4 31B",
        "provider"  : "gemini",
        "model_id"  : "gemma-4-31b-it",
        "max_chars" : 10000,
        "thinking"  : "none",
    },
    {
        "nama"      : "Cerebras — GPT-OSS 120B",
        "provider"  : "cerebras",
        "model_id"  : "gpt-oss-120b",
        "max_chars" : 8000,
    },
    {
        "nama"      : "Cerebras — Zai GLM 4.7",
        "provider"  : "cerebras",
        "model_id"  : "zai-glm-4.7",
        "max_chars" : 8000,
    },
    {
        "nama"      : "Cerebras — Gemma 4 31B",
        "provider"  : "cerebras",
        "model_id"  : "gemma-4-31b",
        "max_chars" : 8000,
    },
    {
        "nama"      : "Mistral — Mistral Small",
        "provider"  : "mistral",
        "model_id"  : "mistral-small-latest",
        "max_chars" : 8000,
    },
]

# Stack khusus Ekstraktor Fenomena: Gemini 3.5 Flash dipasang di urutan ke-2
# (sebelum 3.1 Flash-Lite) karena ekstraksi 11 variabel butuh pemahaman lebih dalam dibanding Screener. 
# Mitigasi Biaya: 3.5 Flash ~6x lebih mahal & kuota gratisnya (RPD) lebih ketat.
# Jika fallback ke Flash-Lite/Gemma terlalu sering di jam sibuk, urutkan ulang stack ini.
AI_MODEL_CATALOG_EKSTRAKSI = [
    AI_MODEL_CATALOG[0],   # Groq — GPT-OSS 120B
    AI_MODEL_CATALOG[2],   # Google — Gemini 3.5 Flash       (dipromosikan)
    AI_MODEL_CATALOG[1],   # Google — Gemini 3.1 Flash-Lite  (turun 1 posisi)
    *AI_MODEL_CATALOG[3:], # sisanya tetap sama
]

MAX_TOKENS_EKSTRAKSI = {
    "groq"    : 6000,
    "gemini"  : 5000,
    "cerebras": 6000,
    "mistral" : 3000,
}
MAX_TOKENS_SCREENING = {
    "groq"    : 2000,
    "gemini"  : 2000,
    "cerebras": 2000,
    "mistral" : 2000,
}
# Pesan standar untuk model 404/Not Found, dipakai bersama
def format_model_404_message(nama_model: str, model_id: str, konteks: str) -> str:
    """
    Pesan standar saat model mengembalikan 404 — dipakai bersama
    ai_engine.py & screener.py supaya konsisten dan mudah di-grep di log.
    """
    return (
        f"[MODEL TIDAK VALID] {nama_model} (model_id='{model_id}') mengembalikan "
        f"404/Not Found saat {konteks}. Kemungkinan model_id sudah deprecated "
        f"atau salah ketik — PERLU DIPERBARUI di radar/model_stack.py. Sistem "
        f"otomatis melanjutkan ke model berikutnya di stack, tapi mohon segera "
        f"cek & perbarui katalog model."
    )