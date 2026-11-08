"""Пути, окружение и конфигурация cine-compass."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RECOMMEND_DIR = DATA_DIR / "recommendations"

RAW_LIBRARY_FILE = RAW_DIR / "library_export.json"
LIBRARY_FILE = DATA_DIR / "library.json"
ENRICH_CACHE_FILE = DATA_DIR / "enrich_cache.json"
CATALOG_FILE = DATA_DIR / "catalog.md"
STATS_FILE = DATA_DIR / "stats.md"
PROFILE_FILE = DATA_DIR / "profile.md"
PREDICTION_FILE = DATA_DIR / "prediction.md"

KINOPOISK_API_KEY = os.getenv("KINOPOISK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# Пауза между запросами к kinopoisk.dev (демо-тариф: 200 запросов/сутки).
ENRICH_INTERVAL = float(os.getenv("ENRICH_INTERVAL", "0.4"))
# Объём описания из API, попадающий в данные (остальное режется).
DESCRIPTION_MAX_CHARS = 300
