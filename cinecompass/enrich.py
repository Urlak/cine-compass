"""Обогащение записей через kinopoisk.dev (жанр, режиссёр, рейтинги и т.д.).

Прогресс кэшируется в data/caches/enrich_cache.json, поэтому процесс можно
останавливать и продолжать (демо-тариф — 200 запросов в сутки).
"""
import json
import time

import requests

from cinecompass import config, library, tmdb


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


def _merge_cache(existing: dict | None, incoming: dict) -> dict:
    """Объединяет кэш с новыми данными без потери рейтингов, жанров и заполненных полей."""
    if not existing:
        return incoming
    merged = dict(existing)
    for key, val in incoming.items():
        if key == "genres":
            merged["genres"] = list(dict.fromkeys(existing.get("genres", []) + val))
        elif val not in (None, "", []) and merged.get(key) in (None, "", []):
            merged[key] = val
    return merged


def enrich_library(limit: int | None = None, kp: bool = False) -> dict:
    """Дозаполняет library.json данными API. Возвращает сводку по количеству.

    Основной источник — TMDB (tmdbId уже есть в экспорте, суточной квоты нет);
    kinopoisk.dev остаётся фолбэком для записей без tmdbId или при промахе TMDB,
    а с флагом kp=True также дотягивает kpRating для записей, где его ещё нет.
    """
    if config.ENRICH_INTERVAL < 0:
        raise SystemExit("ENRICH_INTERVAL должен быть числом >= 0 (см. .env)")
    if kp and not config.KINOPOISK_API_KEY:
        raise SystemExit("KINOPOISK_API_KEY не задан (см. .env.template)")
    items = library.load_library()
    cache = _load_cache()
    todo = []
    for it in items:
        cached = cache.get(str(it["kinopoiskId"]), {})
        need_tmdb = (library.missing_enrichment(it) and str(it["kinopoiskId"]) not in cache) or (
            bool(it.get("tmdbId")) and "tmdbRating" not in cached
        )
        need_kp = kp and cached.get("kpRating") is None
        if need_tmdb or need_kp:
            todo.append((it, need_tmdb, need_kp))
    if limit:
        todo = todo[:limit]
    session = requests.Session()
    headers = {"X-API-KEY": config.KINOPOISK_API_KEY}
    fetched, failed = 0, 0
    quota_exceeded = False
    for i, (item, need_tmdb, need_kp) in enumerate(todo, 1):
        kp_id = item["kinopoiskId"]
        kid_str = str(kp_id)
        item_fetched = False
        detail = tmdb.detail(item) if need_tmdb else None
        if detail is not None:
            merged = _merge_cache(cache.get(kid_str), detail)
            cache[kid_str] = merged
            item.update(merged)
            item_fetched = True
            print(f"TMDB [{i}/{len(todo)}] {kp_id} {item['title']}")
        if (need_tmdb and detail is None) or (need_kp and cache.get(kid_str, {}).get("kpRating") is None):
            if not config.KINOPOISK_API_KEY:
                print(f"[WARN] {kp_id} {item['title']}: нет ни карточки TMDB, ни KINOPOISK_API_KEY")
                failed += 1
                continue
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
                merged = _merge_cache(cache.get(kid_str), _extract(resp.json()))
                cache[kid_str] = merged
                item.update(merged)
                item_fetched = True
                print(f"КП [{i}/{len(todo)}] {kp_id} {item['title']}")
            except requests.ConnectionError as exc:
                # Сеть недоступна целиком — бессмысленно перебирать остальные записи
                failed += 1
                print(f"Нет подключения к API ({exc.__class__.__name__}) — "
                      f"продолжаю только с кэшем; прогресс сохранён.")
                break
            except (requests.RequestException, ValueError) as exc:
                # ValueError сюда попадает из resp.json() на невалидном теле ответа
                failed += 1
                print(f"[WARN] {kp_id} {item['title']}: {exc}")
            time.sleep(config.ENRICH_INTERVAL)
        if item_fetched:
            fetched += 1
        if i % 25 == 0:
            _save_cache(cache)
            _apply_cache(items, cache)
            library.save_library(items)
            print(f"Готово {i}/{len(todo)} (успех: {fetched}, ошибки: {failed})")
    _save_cache(cache)
    _apply_cache(items, cache)
    library.save_library(items)
    return {"fetched": fetched, "failed": failed, "quota_exceeded": quota_exceeded}


def _apply_cache(items: list[dict], cache: dict) -> None:
    for item in items:
        cached = cache.get(str(item["kinopoiskId"]))
        if not cached:
            continue
        if library.missing_enrichment(item):
            item.update(cached)
            continue
        if item.get("tmdbRating") is None and "tmdbRating" in cached:
            item["tmdbRating"] = cached["tmdbRating"]
            item["tmdbVotes"] = cached["tmdbVotes"]
        if item.get("kpRating") is None and cached.get("kpRating") is not None:
            item["kpRating"] = cached["kpRating"]
            item["imdbRating"] = cached.get("imdbRating")
