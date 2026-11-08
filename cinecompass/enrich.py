"""Обогащение записей через kinopoisk.dev (жанр, режиссёр, рейтинги и т.д.).

Прогресс кэшируется в data/enrich_cache.json, поэтому процесс можно
останавливать и продолжать (демо-тариф — 200 запросов в сутки).
"""
import json
import time

import requests

from cinecompass import config


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
    items = _load_items()
    cache = _load_cache()
    todo = [it for it in items if not it.get("genres") and str(it["kinopoiskId"]) not in cache]
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
                f"{config.KINOPOISK_API_BASE}/v1.5/movie/{kp_id}",
                headers=headers,
                timeout=20,
            )
            if resp.status_code == 403:
                # превышен суточный лимит или страница недоступна тарифу
                quota_exceeded = True
                print(f"Лимит API исчерпан на {i}-й записи из {len(todo)}. Прогресс сохранён.")
                break
            resp.raise_for_status()
            detail = _extract(resp.json())
            cache[str(kp_id)] = detail
            item.update(detail)
            fetched += 1
        except requests.RequestException as exc:
            failed += 1
            print(f"[WARN] {kp_id} {item['title']}: {exc}")
        if i % 25 == 0:
            _save_cache(cache)
            _apply_cache(items, cache)
            _write_library(items)
            print(f"Готово {i}/{len(todo)} (успех: {fetched}, ошибки: {failed})")
        time.sleep(config.ENRICH_INTERVAL)
    _save_cache(cache)
    _apply_cache(items, cache)
    _write_library(items)
    return {"fetched": fetched, "failed": failed, "quota_exceeded": quota_exceeded}


def _load_items() -> list[dict]:
    from cinecompass import library
    return library.load_library()


def _apply_cache(items: list[dict], cache: dict) -> None:
    for item in items:
        cached = cache.get(str(item["kinopoiskId"]))
        if cached and not item.get("genres"):
            item.update(cached)


def _write_library(items: list[dict]) -> None:
    from cinecompass import library
    library.save_library(items)
