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


_SLICE_TITLES = [
    ("library", "Библиотека в целом (все фильмы с семантическими тегами)"),
    ("rated", "Только фильмы с личной оценкой"),
    ("high_rated", "Высоко оценённые (8–10)"),
    ("low_rated", "Низко оценённые (1–5)"),
]

_CAT_LABELS = {
    "genre": "Жанровые подвиды",
    "mood": "Настроение",
    "atmosphere": "Атмосфера",
    "setting": "Сеттинг",
    "themes": "Темы",
    "pacing": "Темп",
    "narrative": "Повествование",
    "style": "Визуальный стиль",
}


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "0%"


def taste_profile_markdown(profile: dict) -> str:
    """Человекочитаемый самодостаточный профиль из готового JSON (Этап 4)."""
    cov = profile["coverage"]
    sig = profile["rating_signal"]
    lines = [
        "# Taste Profile — профиль зрительских предпочтений",
        "",
        f"Составлен программно из кинобиблиотеки и English-семантических тегов "
        f"(taxonomy {profile['taxonomy_version']}), без участия LLM.",
        f"Названия фильмов приведены как «Русское название» (Original Title).",
        "",
        "## Покрытие данных",
        "",
        f"- Всего записей в библиотеке: **{cov['library_total']}**.",
        f"- Записей с семантическими тегами: **{cov['with_tags']}** "
        f"({_pct(cov['with_tags'], cov['library_total'])} библиотеки).",
        f"- Оценённых фильмов с тегами: **{cov['rated_with_tags']}**.",
        f"- Статусы классификации в кэше: {cov['cache_status_counts']}.",
        f"- {cov['note']}",
        "",
        f"⚠️ Покрытие данных частичное ({_pct(cov['with_tags'], cov['library_total'])} библиотеки): "
        "выводы ниже описывают только тегированную часть коллекции, а не полный вкус зрителя.",
        "",
    ]
    for key, title in _SLICE_TITLES:
        sl = profile["slices"][key]
        n = sl["films_with_tags"]
        lines += [f"## {title}", ""]
        if key != "library":
            share = _pct(n, profile["slices"]["library"]["films_with_tags"]) if n else "0%"
            lines.append(f"Фильмов с тегами в срезе: **{n}** ({share} от тегированной библиотеки).")
            lines.append("")
        if key == "library":
            # по категориям: подвиды, настроение, атмосфера, темы, стиль…
            for cat in sorted(sl["by_category"]):
                cat_counts = sorted(sl["by_category"][cat].items(), key=lambda kv: (-kv[1], kv[0]))
                lines += [f"### {_CAT_LABELS.get(cat, cat)} ({cat})", ""]
                for tag, cnt in cat_counts[:6]:
                    ex = "; ".join(sl["examples"].get(tag, [])[:2])
                    lines.append(f"- **{tag}** — {cnt} ({_pct(cnt, n)}){f', например: {ex}' if ex else ''}")
                if len(cat_counts) > 6:
                    lines.append(f"- …ещё {len(cat_counts) - 6} тегов категории в JSON.")
                lines.append("")
        else:
            lines += ["Самые частые теги (реальные количества):", ""]
            for tag, cnt in list(sl["tag_counts"].items())[:10]:
                ex = "; ".join(sl["examples"].get(tag, [])[:2])
                lines.append(f"- **{tag}** — {cnt} ({_pct(cnt, n)}){f', например: {ex}' if ex else ''}")
            if len(sl["tag_counts"]) > 10:
                lines.append(f"- …остальные {len(sl['tag_counts']) - 10} тегов приведены полным списком в JSON.")
            lines.append("")
    lines += [
        "## Связь тегов с оценками: высоко оценённые против низко оценённых",
        "",
        f"Срезы: {sig['high_rated_films']} фильмов с оценкой {sig['thresholds']['high']}, "
        f"{sig['low_rated_films']} с оценкой {sig['thresholds']['low']}.",
        "",
        f"{sig['note']}",
        "",
        "| Тег | high: n (доля) | low: n (доля) | Δ долей |",
        "| --- | --- | --- | --- |",
    ]
    for row in sig["share_table"][:24]:
        lines.append(
            f"| {row['tag']} | {row['high_count']} ({_pct(row['high_count'], sig['high_rated_films'])}) "
            f"| {row['low_count']} ({_pct(row['low_count'], sig['low_rated_films'])}) "
            f"| {row['share_diff']:+.2f} |"
        )
    if sig["share_table"][24:]:
        lines.append(f"| … | | | ещё {len(sig['share_table']) - 24} тегов в JSON |")
    lines += [
        "",
        "Теги, встречающиеся в обеих группах: "
        + (", ".join(sig["in_both_groups"]) if sig["in_both_groups"] else "—") + ".",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"
