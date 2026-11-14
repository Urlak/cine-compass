"""CLI cine-compass: импорт/чистка, обогащение, каталог, LLM-аналитика."""
import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cinecompass import benchmark, config, enrich, library, llm, markdown, prompts, semantic, taste, tmdb

def _rows_and_overview():
    items = library.load_library()
    if not items:
        raise SystemExit("Библиотека пуста. Сначала: python main.py import <файл>")
    rows = library.compact_rows(items)
    overview = markdown._overview(items)
    return rows, overview


def cmd_import(args) -> None:
    src = Path(args.file).expanduser().resolve()
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = config.RAW_DIR / f"library_export{src.suffix.lower() or '.json'}"
    if src.resolve() != raw.resolve():
        shutil.copy2(src, raw)
    items = _clean(raw)
    print(f"Импорт: {src} → {raw}")
    _print_clean_stats(items)


def cmd_clean(_args) -> None:
    raws = sorted(config.RAW_DIR.glob("library_export.*"))
    if not raws:
        raise SystemExit(f"В {config.RAW_DIR} нет файла library_export.* — сначала import")
    _print_clean_stats(_clean(raws[-1]))


def _clean(raw: Path) -> list[dict]:
    items = library.clean_items(library.load_export(raw))
    path = library.save_library(items)
    print(f"Чистая библиотека: {len(items)} записей → {path}")
    return items


def _print_clean_stats(items: list[dict]) -> None:
    films = sum(1 for i in items if i["type"] == "film")
    series = sum(1 for i in items if i["type"] == "series")
    unrated = sum(1 for i in items if i.get("userRating") is None)
    rew = sum(1 for i in items if i.get("rewatchCount", 1) > 1)
    print(f"  фильмов: {films}, сериалов: {series}, без оценки: {unrated}, пересмотрено: {rew}")


def cmd_enrich(args) -> None:
    stats = enrich.enrich_library(limit=args.limit)
    print(f"Обогащение завершено. Загружено: {stats['fetched']}, ошибок: {stats['failed']}")
    if stats["quota_exceeded"]:
        print("Суточный лимит kinopoisk.dev исчерпан — запустите ещё раз завтра.")
    elif stats["failed"] and not stats["fetched"]:
        print("Проблемы с подключением — применён только кэш; запустите ещё раз позже.")


def cmd_build(_args) -> None:
    path = markdown.write_catalog(library.load_library())
    print(f"Каталог: {path}")


def cmd_stats(_args) -> None:
    context = markdown.stats_context(library.load_library())
    text = llm.generate(prompts.stats_prompt(context), op="stats")
    out = llm.write_markdown(config.STATS_FILE, text)
    print(f"Статистика: {out}")


def cmd_profile(_args) -> None:
    profile = taste.build_profile(library.load_library(), semantic.load_cache())
    context = markdown.taste_profile_markdown(profile)
    text = llm.generate(prompts.profile_prompt(context), op="profile")
    out = llm.write_markdown(config.PROFILE_FILE, text)
    print(f"Профайл: {out}")


def cmd_recommend(args) -> None:
    items = library.load_library()
    cache = semantic.load_cache()
    tags_by_kid = {kid: rec["tags"] for kid, rec in cache.items() if rec["tags"]}
    candidates = library.tagged_rows(library.mode_candidates(items, args.mode), tags_by_kid)
    profile_md = markdown.taste_profile_markdown(taste.build_profile(items, cache))
    title, prompt = prompts.recommend_prompt(candidates, profile_md, args.mode, args.count)
    print(f"Генерация подборки ({title}) ...")
    text = llm.generate(prompt, op=f"recommend:{args.mode}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = config.RECOMMEND_DIR / f"recommend_{args.mode}_{stamp}.md"
    llm.write_markdown(out, f"# {title}\n\n{text}")
    llm.write_markdown(config.RECOMMEND_DIR / f"recommend_{args.mode}_latest.md", f"# {title}\n\n{text}")
    print(f"Рекомендация: {out}")


def cmd_predict(args) -> None:
    items = library.load_library()
    query = " ".join(args.title).strip()
    
    # A2: Детерминированный поиск перед обращением к LLM (0 токенов при совпадении)
    found = library.find_item_by_title(items, query)
    if found:
        title_ru = found.get("title", "")
        orig = found.get("originalTitle", "")
        title_disp = f"«{title_ru}» ({orig})" if orig and orig != title_ru else f"«{title_ru}»"
        year_str = f", {found['year']}" if found.get("year") else ""
        rating_str = f"{found['userRating']}/10" if found.get("userRating") is not None else "без оценки"
        watched = found.get("watchedDate", "не указана")
        
        doc = (
            f"# Прогноз: {query}\n\n"
            f"Этот фильм уже есть в вашей библиотеке:\n\n"
            f"* **{title_disp}{year_str}** — личная оценка: **{rating_str}**, дата просмотра: **{watched}**.\n\n"
            f"*(Ответ сформирован детерминированно из локальной базы, 0 токенов LLM)*"
        )
        llm.write_markdown(config.PREDICTION_FILE, doc)
        print(doc)
        print(f"\nСохранено: {config.PREDICTION_FILE}")
        return

    # Компактный контекст: портрет зрителя + ближайшие по вкусу записи.
    # Метаданные фильма-запроса берутся из TMDB (без квоты); при промахе
    # соседей нет — прогноз строится по портрету.
    cache = semantic.load_cache()
    profile_md = (config.PROFILE_FILE.read_text(encoding="utf-8")
                  if config.PROFILE_FILE.is_file()
                  else markdown.taste_profile_markdown(taste.build_profile(items, cache)))
    target = tmdb.find(query) or {"title": query, "originalTitle": "", "year": None,
                                  "genres": [], "directors": []}
    near = library.neighbours(items, cache, target)
    tags_by_kid = {kid: rec["tags"] for kid, rec in cache.items() if rec["tags"]}
    rows = library.tagged_rows(near, tags_by_kid) or "(записей-соседей не найдено)"
    target_desc = library.query_label(query, target)
    text = llm.generate(prompts.predict_prompt(profile_md, rows, target_desc), op="predict")
    doc = f"# Прогноз: {target_desc}\n\n{text}"
    llm.write_markdown(config.PREDICTION_FILE, doc)
    print(doc)
    print(f"\nСохранено: {config.PREDICTION_FILE}")


def cmd_benchmark(args) -> None:
    summary = benchmark.run(per_rating=args.per_rating, min_history=args.min_history)
    print(f"MAE: {summary['mae']}, попадания ±1: {summary['hit1_share']}, "
          f"токены: {summary['tokens']}, "
          f"распарсено: {summary['parsed']}/{summary['answered']} из {summary['targets']}")


def cmd_pilot(args) -> None:
    summary = semantic.run(ids=args.ids)
    print(f"Схема: {summary['schema_first_try']} с первого раза, "
          f"{summary['schema_with_retry']} с ретраем, {summary['schema_failed']} провал; "
          f"токены prompt {summary['prompt_tokens']}, output {summary['output_tokens']} "
          f"(латентность ~{summary['avg_duration_s']} с); "
          f"Jaccard повторов: {summary['repeat_jaccard']}")


def cmd_semantic(args) -> None:
    summary = semantic.run_batch_enrich(limit=args.limit)
    print(f"Итог: партий {summary['batches']}, LLM {summary['llm_processed']}, "
          f"голых {summary['auto_insufficient']}, пропущено актуальных {summary['skipped_actual']}, "
          f"кэш {summary['cache_total']} записей; расход накопленно {summary['spent_total']} "
          f"(лимит {summary['limit'] or 'не задан'})"
          + ("; останов по лимиту" if summary["stopped_by_limit"] else ""))


def cmd_taste(_args) -> None:
    profile = taste.build_profile(library.load_library(), semantic.load_cache())
    out = taste.write_profile(profile)
    llm.write_markdown(config.TASTE_PROFILE_MD, markdown.taste_profile_markdown(profile))
    print(f"Профиль: {out['json']}, {out['md']} "
          f"(покрытие {profile['coverage']['with_tags']}/{profile['coverage']['library_total']})")


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="cine-compass: кинобиблиотека, профайл и рекомендации")
    parser.add_argument("--user", default=config.DEFAULT_USER, metavar="NAME",
                        help=f"пользователь, чьи библиотека и выводы используются (по умолчанию {config.DEFAULT_USER!r})")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="импортировать JSON-экспорт (копия + чистка)")
    p.add_argument("file", help="путь к library_export.json")
    p.set_defaults(func=cmd_import)

    sub.add_parser("clean", help="перечистить data/users/<user>/raw/library_export.json").set_defaults(func=cmd_clean)

    p = sub.add_parser("enrich", help="дотянуть жанры/режиссёра/рейтинг через kinopoisk.dev")
    p.add_argument("--limit", type=int, default=None, help="сколько записей обработать за запуск")
    p.set_defaults(func=cmd_enrich)

    sub.add_parser("build", help="собрать маркдаун-каталог data/users/<user>/catalog.md").set_defaults(func=cmd_build)
    sub.add_parser("stats", help="статистика через LLM → data/users/<user>/stats.md").set_defaults(func=cmd_stats)
    sub.add_parser("profile", help="профайл зрителя через LLM → data/users/<user>/profile.md").set_defaults(func=cmd_profile)

    p = sub.add_parser("predict", help="прогноз личной оценки фильма по вашему вкусу (без спойлеров)")
    p.add_argument("title", nargs="+", help="название фильма или сериала")
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("benchmark", help="ретроспективный benchmark predict (Фаза 0)")
    p.add_argument("--per-rating", type=int, default=3, help="сколько целей на каждый балл 4..10")
    p.add_argument("--min-history", type=int, default=50, help="минимальный размер истории цели")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("pilot", help="пилот семантических тегов: выборка → LLM → отчёт (Этап 2)")
    p.add_argument("--ids", type=int, nargs="+", default=None,
                   help="запустить только эти kinopoiskId (мини-пилот, без повторов)")
    p.set_defaults(func=cmd_pilot)

    p = sub.add_parser("semantic", help="пакетная классификация тегами → data/caches/semantic_cache.json (Этап 3)")
    p.add_argument("--limit", type=int, default=None, help="максимум фильмов через LLM за запуск")
    p.set_defaults(func=cmd_semantic)

    sub.add_parser("taste", help="Taste Profile из тегов и оценок → data/users/<user>/taste_profile.md/.json (Этап 4)").set_defaults(func=cmd_taste)

    p = sub.add_parser("recommend", help="персональная подборка «что посмотреть сейчас»")
    p.add_argument("--mode", choices=list(prompts.RECOMMEND_MODES), default="old",
                   help="old — любимое старое, new — свежее, classics — хорошая классика")
    p.add_argument("--count", type=int, default=5, help="сколько тайтлов подобрать")
    p.set_defaults(func=cmd_recommend)

    args = parser.parse_args(argv)
    config.set_user(args.user)
    args.func(args)


if __name__ == "__main__":
    main()
