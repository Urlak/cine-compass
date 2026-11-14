"""Загрузка, нормализация, дедупликация и сохранение библиотеки."""
import json
from pathlib import Path

from cinecompass import config, taste

TYPE_LABELS = {"film": "фильм", "series": "сериал"}


def load_export(path: Path) -> list[dict]:
    """Читает JSON-экспорт Kinopoisk и возвращает список записей."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError(f"В файле {path} нет массива 'items'")
    return items


def clean_items(items: list[dict]) -> list[dict]:
    """Нормализует записи и дедуплицирует по kinopoiskId.

    При повторных просмотрах остаётся запись с самой свежей датой просмотра,
    количество просмотров считается в rewatchCount.
    """
    by_id: dict[int, dict] = {}
    for raw in items:
        kp_id = int(raw["kinopoiskId"])
        item = {
            "title": raw.get("title", "").strip(),
            "originalTitle": raw.get("originalTitle", "").strip(),
            "year": int(raw["year"]) if str(raw.get("year", "")).isdigit() else None,
            "type": raw.get("type", "film"),
            "kinopoiskId": kp_id,
            "kinopoiskUrl": raw.get("kinopoiskUrl", ""),
            "userRating": int(raw["userRating"]) if str(raw.get("userRating", "")).isdigit() else None,
            "watchedDate": raw.get("watchedDate", ""),
            "tmdbId": raw.get("tmdbId", ""),
            "imdbId": raw.get("imdbId", ""),
        }
        existing = by_id.get(kp_id)
        if existing is None:
            item["rewatchCount"] = 1
            by_id[kp_id] = item
        else:
            existing["rewatchCount"] += 1
            if item["watchedDate"] > existing.get("watchedDate", ""):
                # обновляем оценку, но сохраняем накопленные поля обогащения
                existing["userRating"] = item["userRating"]
                existing["watchedDate"] = item["watchedDate"]
    return [by_id[k] for k in sorted(by_id)]


def load_library(path: Path | None = None) -> list[dict]:
    with open(path or config.LIBRARY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_library(items: list[dict], path: Path | None = None) -> Path:
    path = path or config.LIBRARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return path


def missing_enrichment(item: dict) -> bool:
    """True, если базовые поля из API ещё не заполнены."""
    return not item.get("genres")


def type_label(item: dict) -> str:
    return TYPE_LABELS.get(item.get("type"), item.get("type"))


def title_label(item: dict) -> str:
    """«Русское название» (Original Title) для LLM-контекстов."""
    ru, orig = item.get("title", ""), item.get("originalTitle", "")
    return f"{ru} ({orig})" if orig and orig != ru else ru


def duration(item: dict) -> str:
    """Человекочитаемая длительность: минуты или сезоны."""
    minutes = item.get("movieLength")
    if minutes:
        hours, rest = divmod(int(minutes), 60)
        return f"{hours} ч {rest} мин" if rest else f"{hours} ч"
    # seriesLength в kinopoisk.dev — средняя длительность серии, не число сезонов
    episode = item.get("seriesLength")
    if episode:
        return f"сер. {int(episode)} мин"
    return ""


def compact_rows(items: list[dict]) -> str:
    """Компактное представление библиотеки для LLM-промптов (TSV-строки)."""
    lines = []
    for it in items:
        parts = [
            it["title"],
            it["originalTitle"] if it["originalTitle"] != it["title"] else "",
            str(it["year"]) if it.get("year") else "",
            type_label(it),
            str(it["userRating"]) if it.get("userRating") is not None else "—",
            ", ".join(it.get("genres", [])),
            ", ".join(it["directors"]) if it.get("directors") else "",
            os_rating(it),
            duration(it),
            it["watchedDate"],
        ]
        if it.get("rewatchCount", 1) > 1:
            parts.append(f"пересмотрено x{it['rewatchCount']}")
        ext = f"IMDb {it['imdbId']}" if it.get("imdbId") else ""
        row = " | ".join(p for p in parts if p and p != "—")
        if ext:
            row += f" | {ext}"
        lines.append(row)
    return "\n".join(lines)


NEW_YEAR_MIN = 2020        # режим new: только свежие релизы
CLASSICS_YEAR_MAX = 2000   # режим classics: только старые тайтлы


NEIGHBOUR_LIMIT = 30  # сколько ближайших по вкусу записей передаётся в predict


def query_label(query: str, target: dict) -> str:
    """Описание фильма-запроса для predict: название + фактология (библиотека или TMDB)."""
    inner = [p for p in (
        target.get("originalTitle", "") if target.get("originalTitle", "") != target.get("title", "") else "",
        str(target.get("year") or ""),
    ) if p]
    label = f"{query} ({', '.join(inner)})" if inner else query
    if target.get("genres"):
        label += " — жанры: " + ", ".join(target["genres"])
    if target.get("directors"):
        label += ", реж. " + ", ".join(target["directors"])
    return label


def neighbours(items: list[dict], cache: dict[int, dict], target: dict,
               limit: int = NEIGHBOUR_LIMIT) -> list[dict]:
    """Ближайшие по вкусу записи: совпадение режиссёра, семантических тегов и жанров.

    target — метаданные фильма-запроса (из библиотеки или TMDB); у live-запроса
    семантических тегов нет, оценка ведётся по режиссёру и жанрам.
    """
    t_dirs = set(target.get("directors", []))
    t_genres = set(target.get("genres", []))
    t_tags = set(cache.get(target.get("kinopoiskId"), {}).get("tags", [])) \
        if target.get("kinopoiskId") else set()
    scored = []
    for item in items:
        score = (
            3 * len(t_dirs & set(item.get("directors", [])))
            + 2 * len(t_tags & set(cache.get(item["kinopoiskId"], {}).get("tags", [])))
            + len(t_genres & set(item.get("genres", [])))
        )
        if score:
            scored.append((-score, -(item.get("userRating") or 0), item["title"], item))
    scored.sort(key=lambda x: x[:3])
    return [item for *_, item in scored[:limit]]


def mode_candidates(items: list[dict], mode: str) -> list[dict]:
    """Детерминированный Python-отбор кандидатов по режиму recommend.

    Фильтры только по годам и личным оценкам: фильмы без семантических тегов
    не исключаются — отсутствие тегов не означает несоответствие вкусу.
    """
    if mode == "old":
        cands = [i for i in items if (i.get("userRating") or 0) >= taste.HIGH_RATING_MIN]
        cands.sort(key=lambda i: (-i["userRating"], i.get("year") or 0))
    elif mode == "new":
        cands = [i for i in items if (i.get("year") or 0) >= NEW_YEAR_MIN]
        cands.sort(key=lambda i: i["year"], reverse=True)
    elif mode == "classics":
        cands = [i for i in items if (i.get("year") or 9999) < CLASSICS_YEAR_MAX
                 and (i.get("userRating") or 0) < taste.HIGH_RATING_MIN]
        cands.sort(key=lambda i: i["year"])
    else:
        raise ValueError(f"Неизвестный режим: {mode}")
    return cands


def tagged_rows(items: list[dict], tags_by_kid: dict[int, list[str]]) -> str:
    """Компактные строки кандидатов для recommend: ключевые поля + семантические теги."""
    lines = []
    for it in items:
        parts = [
            f"{it['title']} ({it['originalTitle']})" if it["originalTitle"] != it["title"] else it["title"],
            str(it["year"]) if it.get("year") else "",
            type_label(it),
            f"{it['userRating']}/10" if it.get("userRating") is not None else "",
            f"КП {it['kpRating']:.1f}" if it.get("kpRating") else "",
            ", ".join(it.get("genres", [])),
            "реж. " + ", ".join(it["directors"]) if it.get("directors") else "",
        ]
        tags = tags_by_kid.get(it["kinopoiskId"])
        if tags:
            parts.append("теги: " + ", ".join(tags))
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


def os_rating(item: dict) -> str:
    """Рейтинг Кинопоиска одной строкой, '' если нет."""
    kp = item.get("kpRating")
    return f"КП {float(kp):.1f}" if kp else ""


def normalize_title(text: str) -> str:
    """Нормализует название для нечувствительного к регистру и знакам поиска."""
    import re
    return re.sub(r"[^\w\s]", "", (text or "").lower()).strip()


def find_item_by_title(items: list[dict], query: str) -> dict | None:
    """Детерминированный поиск фильма/сериала в библиотеке по названию (RU или EN)."""
    norm_q = normalize_title(query)
    if not norm_q:
        return None
    for item in items:
        if normalize_title(item.get("title", "")) == norm_q:
            return item
        if normalize_title(item.get("originalTitle", "")) == norm_q:
            return item
    return None
