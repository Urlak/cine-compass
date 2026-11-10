"""Обогащение записей через kinopoisk.dev (жанр, режиссёр, рейтинги и т.д.).

Прогресс кэшируется в data/enrich_cache.json, поэтому процесс можно
останавливать и продолжать (демо-тариф — 200 запросов в сутки).
"""
import json
import time

import requests

from cinecompass import config, library


# Обе базы kinopoisk.dev отдают одинаковые данные; домен фиксирован,
# чтобы API-ключ не уводился на произвольный хост через конфиг.
API_BASE = "https://api.poiskkino.dev"


def _load_cache() -> dict:
    if config.ENRICH_CACHE_FILE.exists():
        with open(config.ENRICH_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    config.ENRICH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.ENRICH_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def _extract(data: dict) -> dict:
    description = data.get("description") or ""
    persons = data.get("persons", [])
    directors = [
        p["name"] or p.get("alternativeName", "")
        for p in persons
        if p.get("enProfession") == "director"
    ]
    rating = data.get("rating") or {}
    return {
        "genres": [g["name"] for g in data.get("genres", []) if g.get("name")],
        "countries": [c["name"] for c in data.get("countries", []) if c.get("name")],
        "directors": [d for d in directors if d],
        "kpRating": rating.get("kp") or None,
        "imdbRating": rating.get("imdb") or None,
        "movieLength": data.get("movieLength"),
        "seriesLength": data.get("seriesLength"),
        "ageRating": data.get("ageRating"),
        "description": description[:config.DESCRIPTION_MAX_CHARS] if description else "",
    }


def enrich_library(limit: int | None = None) -> dict:
    """Дозаполняет library.json данными API. Возвращает сводку по количеству."""
    if not config.KINOPOISK_API_KEY:
        raise SystemExit("KINOPOISK_API_KEY не задан (см. .env.template)")
    if config.ENRICH_INTERVAL < 0:
        raise SystemExit("ENRICH_INTERVAL должен быть числом >= 0 (см. .env)")
    items = library.load_library()
    cache = _load_cache()
    todo = [
        it for it in items
        if library.missing_enrichment(it) and str(it["kinopoiskId"]) not in cache
    ]
    if limit:
        todo = todo[:limit]
    session = requests.Session()
    headers = {"X-API-KEY": config.KINOPOISK_API_KEY}
    fetched, failed = 0, 0
    quota_exceeded = False
    for i, item in enumerate(todo, 1):
        kp_id = item["kinopoiskId"]
        try:
            resp = session.get(
                f"{API_BASE}/v1.5/movie/{kp_id}",
                headers=headers,
                timeout=20,
            )
            if resp.status_code in (403, 429):
                # 403 — суточный лимит демо-тарифа, 429 — флуд-ограничение
                quota_exceeded = True
                print(f"Лимит API исчерпан на {i}-й записи из {len(todo)}. Прогресс сохранён.")
                break
            resp.raise_for_status()
            detail = _extract(resp.json())
            cache[str(kp_id)] = detail
            item.update(detail)
            fetched += 1
        except (requests.RequestException, ValueError) as exc:
            # ValueError сюда попадает из resp.json() на невалидном теле ответа
            failed += 1
            print(f"[WARN] {kp_id} {item['title']}: {exc}")
        if i % 25 == 0:
            _save_cache(cache)
            _apply_cache(items, cache)
            library.save_library(items)
            print(f"Готово {i}/{len(todo)} (успех: {fetched}, ошибки: {failed})")
        time.sleep(config.ENRICH_INTERVAL)
    _save_cache(cache)
    _apply_cache(items, cache)
    library.save_library(items)
    return {"fetched": fetched, "failed": failed, "quota_exceeded": quota_exceeded}


def _apply_cache(items: list[dict], cache: dict) -> None:
    for item in items:
        cached = cache.get(str(item["kinopoiskId"]))
        if cached and library.missing_enrichment(item):
            item.update(cached)
