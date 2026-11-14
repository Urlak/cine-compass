"""Генерация маркдаун-каталога библиотеки + локальная статистика."""
from collections import Counter
from pathlib import Path

from cinecompass import config, library, taste

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


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f}%" if total else "0%"


def _apct(rate: float) -> str:
    """Approval Rate в процентах для маркдаун-таблиц."""
    return f"{100 * rate:.0f}%"


def taste_profile_markdown(profile: dict) -> str:
    """Человекочитаемый самодостаточный профиль из готового JSON (Этап 4)."""
    cov = profile["coverage"]
    base = profile["baseline"]
    lines = [
        "# Taste Profile — профиль зрительских предпочтений",
        "",
        f"Составлен программно из кинобиблиотеки и English-семантических тегов "
        f"(taxonomy {profile['taxonomy_version']}, prompt {profile['prompt_version']}), без участия LLM. "
        f"Фильмы упоминаются в формате «Название» (Original, YYYY) [оценка].",
        "",
        "## Метаданные",
        "",
        f"- tagged_count: **{cov['with_tags']}** из {cov['library_total']} записей "
        f"({_pct(cov['with_tags'], cov['library_total'])}); rated_count: **{cov['rated_with_tags']}** "
        f"из {cov['rated_total']} оценённых.",
        f"- generated_at: **{profile['generated']}**. Статусы классификации: {cov['cache_status_counts']}.",
        f"- Корзины оценок (все оценённые с тегами): "
        + ", ".join(
            f"{label} — {profile['buckets_counts'].get(name, 0)} "
            f"({_apct(profile['buckets_counts'].get(name, 0) / cov['rated_with_tags']) if cov['rated_with_tags'] else '0%'})"
            for name, label in profile["buckets"].items()
        ) + ".",
        f"- {cov['note']}",
        "",
        f"⚠️ Покрытие частичное ({_pct(cov['with_tags'], cov['library_total'])}): выводы описывают "
        "тегированную часть коллекции, а не весь вкус зрителя.",
        "",
    ]
    supported = [r for r in profile["tag_stats"] if r["n"] >= taste.SUPPORT_MIN]
    lines += [
        "## Связь тегов с оценками: Approval Rate и Lift",
        "",
        f"Approval — доля фильмов с тегом в корзине (сглаживание Лапласа +1/+2); "
        f"Lift — отношение к базовой доле по всей тегированной библиотеке "
        f"(8–10: {_apct(base.get('8_10', 0))}, 9–10: {_apct(base.get('9_10', 0))}, "
        f"1–5: {_apct(base.get('1_5', 0))}). "
        f"В таблице теги с поддержкой n ≥ {taste.SUPPORT_MIN}, сортировка по Lift 8–10.",
        "",
        "| Тег | n | 8–10 % | 9–10 % | 1–5 % | Lift 8–10 | Примеры |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in supported:
        lines.append(
            f"| {r['tag']} | {r['n']} | {_apct(r['approval_8_10'])} | {_apct(r['approval_9_10'])} "
            f"| {_apct(r['approval_1_5'])} | {r['lift_8_10']:.2f} | {_esc('; '.join(r['examples'][:2]))} |"
        )
    if len(profile["tag_stats"]) > len(supported):
        lines.append(f"| … | | | | | | ещё {len(profile['tag_stats']) - len(supported)} тегов с n < "
                     f"{taste.SUPPORT_MIN} в JSON |")
    lines += ["", "Approval/Lift — наводка, а не вывод о предпочтении: тег может просто "
              "отражать состав библиотеки.", ""]
    if profile["niche_tags"]:
        lines += ["## Нишевые теги: мало просмотров, высокий одобрение", ""]
        for r in profile["niche_tags"]:
            lines.append(f"- **{r['tag']}** — n={r['n']}, 8–10: {_apct(r['approval_8_10_raw'])} (сырая доля), "
                         f"Lift {r['lift_8_10']:.2f}; примеры: {'; '.join(r['examples'][:2])}")
        lines.append("")
    for key, title in (("best", "Пары тегов с максимальным одобрением"), ("worst", "Пары тегов с минимальным одобрением")):
        lines += [f"## {title}", ""]
        rows = profile["pairs"][key]
        if rows:
            lines += ["| Пара | n | 8–10 % | Примеры |", "| --- | --- | --- | --- |"]
            for r in rows:
                lines.append(f"| {r['tags'][0]} + {r['tags'][1]} | {r['n']} | {_apct(r['approval_8_10'])} "
                             f"| {_esc('; '.join(r['examples'][:2]))} |")
        else:
            lines.append("— (нет пар с достаточной поддержкой).")
        lines.append("")
    facts = profile["facts"]
    lines += [
        "## Фактологические срезы (по всем оценённым записям)",
        "",
        "### Десятилетия выпуска",
        "",
        "| Десятилетие | n | 8–10 | 9–10 | Пример |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in facts["decades"]:
        lines.append(f"| {r['decade']} | {r['n']} | {_apct(r['approval_8_10'])} | {_apct(r['approval_9_10'])} "
                     f"| {_esc(r['example'])} |")
    lines += ["", "### Режиссёры (не менее 3 оценённых фильмов, по средней оценке)", ""]
    lines += [f"- {r['director']} — {r['n']} фильм(ов), средняя {r['avg_rating']:.2f}" for r in facts["directors"][:15]]
    kd = facts["kp_delta"]
    lines += [
        "",
        "### Расхождение с рейтингом Кинопоиска (личная − КП)",
        "",
        "Недооценённые рынком (+Δ): " + "; ".join(f"{r['title']} (КП {r['kp_rating']})" for r in kd["underrated"][:8]),
        "",
        "Переоценённые лично (−Δ): " + "; ".join(f"{r['title']} (КП {r['kp_rating']})" for r in kd["overrated"][:8]),
        "",
        "### Формат и хронометраж",
        "",
        f"- Фильмы: n={facts['format']['films']['n']}, 8–10: {_apct(facts['format']['films']['approval_8_10'])}; "
        f"сериалы: n={facts['format']['series']['n']}, 8–10: {_apct(facts['format']['series']['approval_8_10'])}.",
    ]
    lines += [f"- {r['bucket']} мин: n={r['n']}, 8–10: {_apct(r['approval_8_10'])}, "
              f"9–10: {_apct(r['approval_9_10'])}" for r in facts["format"]["length"]]
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"

