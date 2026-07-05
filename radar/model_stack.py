# File: radar/model_stack.py
"""
Katalog model AI bersama untuk SI-PENA RADAR.

Modul ini jadi SATU-SATUNYA sumber kebenaran untuk katalog model & urutan
prioritas fallback, serta budget token per konteks pemakaian (ekstraksi vs
screening). Field "max_chars" dipakai khusus oleh ai_engine.py untuk memotong
panjang teks artikel sebelum masuk prompt ekstraksi (tidak relevan untuk
screener.py, yang sudah memotong teks ke 4000 karakter secara terpisah).
"""

AI_MODEL_CATALOG = [
    {
        "nama"      : "Groq — GPT-OSS 120B",
        "provider"  : "groq",
        "model_id"  : "openai/gpt-oss-120b",
        "max_chars" : 8000,
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