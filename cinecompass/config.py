"""Пути, окружение и конфигурация cine-compass."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "caches"      # общие кэши: зависят только от фильма, не от пользователя
USERS_DIR = DATA_DIR / "users"
USAGE_FILE = DATA_DIR / "usage.jsonl"
TAXONOMY_FILE = BASE_DIR / "taxonomy.json"

# Кэши общие для всех пользователей (ключ — kinopoiskId).
ENRICH_CACHE_FILE = CACHE_DIR / "enrich_cache.json"
SEMANTIC_CACHE_FILE = CACHE_DIR / "semantic_cache.json"

DEFAULT_USER = "me"

# Пользовательские пути назначаются set_user(); CLI вызывает его до команд.
USER = DEFAULT_USER
USER_DIR = USERS_DIR / DEFAULT_USER
RAW_DIR = USER_DIR / "raw"
RECOMMEND_DIR = USER_DIR / "recommendations"

RAW_LIBRARY_FILE = RAW_DIR / "library_export.json"
LIBRARY_FILE = USER_DIR / "library.json"
CATALOG_FILE = USER_DIR / "catalog.md"
STATS_FILE = USER_DIR / "stats.md"
PROFILE_FILE = USER_DIR / "profile.md"
PREDICTION_FILE = USER_DIR / "prediction.md"
TASTE_PROFILE_JSON = USER_DIR / "taste_profile.json"
TASTE_PROFILE_MD = USER_DIR / "taste_profile.md"


def set_user(name: str) -> None:
    """Выбирает пользователя, чьи библиотека и выводы используются командами."""
    global USER, USER_DIR, RAW_DIR, RECOMMEND_DIR, RAW_LIBRARY_FILE, LIBRARY_FILE
    global CATALOG_FILE, STATS_FILE, PROFILE_FILE, PREDICTION_FILE
    global TASTE_PROFILE_JSON, TASTE_PROFILE_MD
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise SystemExit(f"Недопустимое имя пользователя: {name!r}")
    USER = name
    USER_DIR = USERS_DIR / name
    RAW_DIR = USER_DIR / "raw"
    RECOMMEND_DIR = USER_DIR / "recommendations"
    RAW_LIBRARY_FILE = RAW_DIR / "library_export.json"
    LIBRARY_FILE = USER_DIR / "library.json"
    CATALOG_FILE = USER_DIR / "catalog.md"
    STATS_FILE = USER_DIR / "stats.md"
    PROFILE_FILE = USER_DIR / "profile.md"
    PREDICTION_FILE = USER_DIR / "prediction.md"
    TASTE_PROFILE_JSON = USER_DIR / "taste_profile.json"
    TASTE_PROFILE_MD = USER_DIR / "taste_profile.md"

KINOPOISK_API_KEY = os.getenv("KINOPOISK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# Пауза между запросами к kinopoisk.dev (демо-тариф: 200 запросов/сутки).
ENRICH_INTERVAL = float(os.getenv("ENRICH_INTERVAL", "0.4"))
# Объём описания из API, попадающий в данные (остальное режется).
DESCRIPTION_MAX_CHARS = 300

# Пакетная семантическая классификация (Этап 3). Лимит 0 = не задан.
SEMANTIC_ENRICHMENT_BATCH_SIZE = int(os.getenv("SEMANTIC_ENRICHMENT_BATCH_SIZE", "15"))
SEMANTIC_ENRICHMENT_MAX_TOKENS = int(os.getenv("SEMANTIC_ENRICHMENT_MAX_TOKENS", "0"))
