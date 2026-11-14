"""Клиент TMDB: метаданные фильмов/сериалов без суточной квоты (Read Access Token).

Используется для live-прогноза predict (метаданные фильма-запроса для отбора
соседей) и как источник обогащения в enrich.py вместо лимитированного kinopoisk.dev.
"""
import requests

from cinecompass import config

API_BASE = "https://api.themoviedb.org/3"


def _get(path: str, params: dict) -> dict | None:
    """GET к TMDB с Bearer-токеном; None при отсутствии ключа или ошибке сети."""
    if not config.TMDB_API_KEY:
        return None
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            params={**{"language": "ru-RU"}, **params},
            headers={"Authorization": f"Bearer {config.TMDB_API_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def detail(item: dict) -> dict | None:
    """Карточка TMDB по tmdbId из экспорта Кинопоиска; None при промахе или ошибке.

    Возвращает поля той же схемы, что enrich._extract (kinopoisk.dev), чтобы
    кэш обогащения оставался однородным: kpRating/imdbRating у TMDB нет — None.
    Русский overview при отсутствии заменяется английским.
    """
    if not item.get("tmdbId"):
        return None
    kind = "tv" if item.get("type") == "series" else "movie"
    data = _get(f"/{kind}/{item['tmdbId']}", {"append_to_response": "credits"})
    if not data:
        return None
    if kind == "movie":
        directors = [p["name"] for p in data.get("credits", {}).get("crew", [])
                     if p.get("job") == "Director"]
        length, series_length = data.get("runtime"), None
    else:
        directors = [p["name"] for p in data.get("created_by", [])]
        length, series_length = None, (data.get("episode_run_time") or [None])[0]
    description = (data.get("overview") or "").strip()
    if not description:
        en = _get(f"/{kind}/{item['tmdbId']}", {"language": "en-US"})
        description = (en.get("overview") or "").strip() if en else ""
    return {
        "genres": [g["name"] for g in data.get("genres", []) if g.get("name")],
        "countries": [c["name"] for c in data.get("production_countries", []) if c.get("name")],
        "directors": [d for d in directors if d],
        "kpRating": None,
        "imdbRating": None,
        "tmdbRating": round(data["vote_average"], 1) if data.get("vote_average") else None,
        "tmdbVotes": data.get("vote_count"),
        "movieLength": length,
        "seriesLength": series_length,
        "ageRating": None,
        "description": description[:config.DESCRIPTION_MAX_CHARS],
    }


def find(query: str) -> dict | None:
    """Поиск фильма/сериала по названию → фактологические поля для отбора соседей.

    Возвращает {tmdbId, title, originalTitle, year, type, genres, directors}
    или None, если ключ не задан, сеть недоступна и точного совпадения нет.
    """
    data = _get("/search/multi", {"query": query})
    if not data:
        return None
    results = [r for r in data.get("results", []) if r.get("media_type") in ("movie", "tv")]
    if not results:
        return None
    best = results[0]
    kind = "movie" if best["media_type"] == "movie" else "tv"
    details = _get(f"/{kind}/{best['id']}", {"append_to_response": "credits"})
    if not details:
        return None
    if kind == "movie":
        directors = [p["name"] for p in details.get("credits", {}).get("crew", [])
                     if p.get("job") == "Director"]
    else:
        directors = [p["name"] for p in details.get("credits", {}).get("crew", [])
                     if p.get("job") == "Series Director"] or \
                    [p["name"] for p in details.get("created_by", [])]
    return {
        "tmdbId": details["id"],
        "title": details.get("title") or details.get("name", ""),
        "originalTitle": details.get("original_title") or details.get("original_name", ""),
        "year": int((details.get("release_date") or details.get("first_air_date") or "")[:4]) or None,
        "type": kind,
        "genres": [g["name"] for g in details.get("genres", []) if g.get("name")],
        "directors": directors,
    }
