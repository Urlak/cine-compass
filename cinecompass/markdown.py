"""Генерация маркдаун-каталога библиотеки + локальная статистика."""
from collections import Counter
from pathlib import Path

from cinecompass import config, library

_RATING_TIERS = [
    ("Любимое", [9, 10]),
    ("Очень хорошо", [8]),
    ("Хорошо", [7]),
    ("Неплохо", [6]),
    ("Средне", [5]),
    ("Слабо", [3, 4]),
    ("Без оценки", [None]),
]


def _esc(text: str) -> str:
    """Экранирует символы, ломающие маркдаун-таблицы и ссылки."""
    return text.replace("|", "/").replace("[", "\\[").replace("]", "\\]")


def item_row(item: dict) -> str:
    title = _esc(item["title"])
    orig = _esc(item["originalTitle"]) if item["originalTitle"] != item["title"] else ""
    year = item.get("year") or "—"
    label = library.type_label(item)
    rating = str(item["userRating"]) if item.get("userRating") is not None else "—"
    genres = _esc(", ".join(item.get("genres", []))) or "—"
    kp = f"{item['kpRating']:.1f}" if item.get("kpRating") else "—"
    directors = _esc(", ".join(item.get("directors", []))) or "—"
    dur = library.duration(item) or "—"
    watched = item["watchedDate"]
    url = item.get("kinopoiskUrl", "")
    name = f"[{title}]({url})" if url else title
    orig_cell = f" *({orig})*" if orig else ""
    return f"| {name}{orig_cell} | {year} | {label} | {genres} | {directors} | {rating} | {kp} | {dur} | {watched} |"


_HEADER = (
    "| Название | Год | Тип | Жанры | Режиссёр | Моя оценка | Рейтинг КП | Длительность | Просмотрено |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
)


def build_catalog(items: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Кинобиблиотека\n")
    lines.append(_overview(items))
    groups = {name: [] for name, _ in _RATING_TIERS}
    by_rating = {r: [] for r in range(3, 11)}
    for it in items:
        r = it.get("userRating")
        if r is not None and r in by_rating:
            if r >= 9:
                groups["Любимое"].append(it)
            elif r == 8:
                groups["Очень хорошо"].append(it)
            elif r == 7:
                groups["Хорошо"].append(it)
            elif r == 6:
                groups["Неплохо"].append(it)
            else:
                groups["Средне" if r == 5 else "Слабо"].append(it)
        else:
            groups["Без оценки"].append(it)
    for name, _ in _RATING_TIERS:
        bucket = groups[name]
        if not bucket:
            continue
        bucket.sort(key=lambda x: (x["watchedDate"], x["title"]))
        lines.append(f"\n## {name} ({len(bucket)})\n")
        lines.append(_HEADER)
        lines.extend(item_row(it) for it in bucket)
    return "\n".join(lines) + "\n"


def _overview(items: list[dict]) -> str:
    films = [i for i in items if i["type"] == "film"]
    series = [i for i in items if i["type"] == "series"]
    rated = [i for i in items if i.get("userRating") is not None]
    decades = Counter(str((i["year"] // 10) * 10) + "е" for i in items if i.get("year"))
    genres = Counter(g for i in items for g in i.get("genres", []))
    genre_lines = "\n".join(
        f"- {name} — {count}" for name, count in genres.most_common(15)
    )
    decade_lines = "\n".join(
        f"- {dec} — {count}" for dec, count in sorted(decades.items())
    )
    avg = sum(i["userRating"] for i in rated) / len(rated) if rated else 0
    rewatched = [i for i in items if i.get("rewatchCount", 1) > 1]
    return (
        f"Всего записей: **{len(items)}** (фильмов: {len(films)}, сериалов: {len(series)}, "
        f"без оценки: {len(items) - len(rated)}, пересмотрено: {len(rewatched)}).\n\n"
        f"Средняя личная оценка: **{avg:.2f}** из 10.\n\n"
        "### Топ жанров\n\n" + genre_lines +
        "\n\n### По десятилетиям\n\n" + decade_lines + "\n"
    )


def write_catalog(items: list[dict]) -> Path:
    text = build_catalog(items)
    config.CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.CATALOG_FILE.write_text(text, encoding="utf-8")
    return config.CATALOG_FILE
