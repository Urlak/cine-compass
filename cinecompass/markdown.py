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


def stats_context(items: list[dict]) -> str:
    """Программная сводка поведения зрителя для stats: агрегаты вместо 1155 строк."""
    rated = [i for i in items if i.get("userRating") is not None]
    dist = Counter(i["userRating"] for i in rated)
    avg = sum(i["userRating"] for i in rated) / len(rated) if rated else 0
    films = [i for i in rated if i["type"] == "film"]
    series = [i for i in rated if i["type"] == "series"]
    avg_of = lambda rows: sum(i["userRating"] for i in rows) / len(rows) if rows else 0.0

    tens = sorted((i for i in rated if i["userRating"] == 10), key=lambda i: i["title"])
    lows = sorted((i for i in rated if i["userRating"] <= 5), key=lambda i: (i["userRating"], i["title"]))

    directors: dict[str, list[int]] = {}
    for i in rated:
        for d in i.get("directors", []):
            directors.setdefault(d, []).append(i["userRating"])
    dr_lines = []
    for name, scores in sorted(
        ((d, s) for d, s in directors.items() if len(s) >= 3),
        key=lambda kv: (-len(kv[1]), kv[0]),
    ):
        dr_lines.append(f"- {name} — {len(scores)} оценённых, средняя {sum(scores) / len(scores):.2f}")

    decades: dict[str, list[int]] = {}
    for i in rated:
        if i.get("year"):
            decades.setdefault(f"{(i['year'] // 10) * 10}-е", []).append(i["userRating"])
    dec_lines = [
        f"- {dec} — {len(scores)} (средняя {sum(scores) / len(scores):.2f})"
        for dec, scores in sorted(decades.items())
    ]

    by_year: Counter = Counter((i.get("watchedDate") or "?")[:4] for i in rated)
    year_lines = [f"- {y} — {n}" for y, n in sorted(by_year.items()) if y != "?"]

    countries = Counter(c for i in items for c in i.get("countries", []))
    genres = Counter(g for i in items for g in i.get("genres", []))

    n_dir = sum(1 for i in items if i.get("directors"))
    n_cty = sum(1 for i in items if i.get("countries"))
    lines = [
        "# Сводка кинобиблиотеки для аналитика",
        "",
        "## Общие данные",
        f"- Всего записей: **{len(items)}** (фильмов: {sum(1 for i in items if i['type'] == 'film')}, "
        f"сериалов: {sum(1 for i in items if i['type'] == 'series')}); "
        f"оценено: {len(rated)}, без оценки: {len(items) - len(rated)}.",
        f"- Средняя личная оценка: **{avg:.2f}** из 10. Пересмотров: "
        f"{sum(1 for i in items if i.get('rewatchCount', 1) > 1)}.",
        f"- Полнота метаданных: режиссёры заполнены у **{n_dir}/{len(items)}**, страны у **{n_cty}/{len(items)}**, "
        f"дата просмотра у {sum(1 for i in items if (i.get('watchedDate') or '').strip())}/{len(items)}. "
        "Статистика по режиссёрам и странам описывает только заполненную часть библиотеки.",
        "",
        "## Распределение личных оценок",
        ", ".join(f"{r} — {dist[r]}" for r in range(1, 11) if dist[r]),
        "",
        f"### Фильмы с оценкой 10 ({len(tens)})",
        "; ".join(f"{library.title_label(i)}, {i['year']}" for i in tens),
        "",
        f"### Фильмы с оценкой 5 и ниже ({len(lows)})",
        "; ".join(f"{library.title_label(i)}, {i['year']} ({i['userRating']})" for i in lows),
        "",
        "## Режиссёры (не менее 3 оценённых фильмов)",
        *dr_lines,
        "",
        "## Десятилетия выпуска (оценённые фильмы)",
        *dec_lines,
        "",
        "## Активность по годам просмотра",
        *year_lines,
        "",
        "## Страны (топ-10, только заполненные записи)",
        ", ".join(f"{c} — {n}" for c, n in countries.most_common(10)),
        "",
        f"## Фильмы против сериалов (оценённые): фильмы {len(films)} "
        f"(средняя {avg_of(films):.2f}), "
        f"сериалы {len(series)} (средняя {avg_of(series):.2f})",
        "",
        "## Топ-15 жанров библиотеки",
        ", ".join(f"{g} — {n}" for g, n in genres.most_common(15)),
        "",
    ]
    return "\n".join(lines)


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
