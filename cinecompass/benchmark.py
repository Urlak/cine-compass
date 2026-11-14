"""Ретроспективный benchmark для predict: тот же контекст, что у live-команды.

Python строит профиль по записям, просмотренным строго ДО даты X, скрывает
запись, реальную оценку которой нужно угадать, и сравнивает прогноз с фактом.
Контекст — портрет зрителя + ближайшие соседи по вкусу (см. predict).
"""
import json
import random
import re
from datetime import datetime

from cinecompass import config, library, llm, markdown, prompts, semantic, taste

FIXED_SEED = 42


def build_sample(items: list[dict], per_rating: int = 3, seed: int = FIXED_SEED) -> list[dict]:
    """Стратифицированная выборка: до per_rating оценённых записей на каждый балл 4..10."""
    rng = random.Random(seed)
    chosen = []
    for rating in range(4, 11):
        pool = [i for i in items if i.get("userRating") == rating]
        if not pool:
            continue
        rng.shuffle(pool)
        chosen.extend(pool[:per_rating])
    return chosen


def profile_history(items: list[dict], target: dict) -> list[dict]:
    """История строго ДО даты просмотра цели, сама цель исключена."""
    return [
        i for i in items
        if i["watchedDate"] < target["watchedDate"]
        and i["kinopoiskId"] != target["kinopoiskId"]
    ]


def parse_score(text: str) -> int | None:
    """Достаёт прогноз из «Оценка: X/10» (или просто «X/10»); иначе None."""
    m = re.search(r"(\d{1,2})\s*/\s*10", text)
    if m:
        score = int(m.group(1))
    else:
        m = re.search(r"Оценка\D{0,10}(\d{1,2})", text)
        if m:
            score = int(m.group(1))
        else:
            return None
    return score if 1 <= score <= 10 else None


def _portrait(items: list[dict], cache: dict[int, dict]) -> str:
    """Портрет зрителя для predict: LLM-файл profile.md, без него — метрики из taste."""
    if config.PROFILE_FILE.is_file():
        return config.PROFILE_FILE.read_text(encoding="utf-8")
    return markdown.taste_profile_markdown(taste.build_profile(items, cache))


def run(per_rating: int = 3, min_history: int = 50) -> dict:
    items = library.load_library()
    cache = semantic.load_cache()
    targets = build_sample(items, per_rating=per_rating)
    results = []
    total = len(targets)
    usage_offset = _usage_row_count()
    print(f"Запуск бенчмарка: {total} целей (по {per_rating} на каждый балл от 4 до 10)...", flush=True)
    for idx, target in enumerate(targets, 1):
        history = profile_history(items, target)
        title_full = library.query_label(target["title"], target)
        record = {
            "title": title_full,
            "year": target["year"],
            "watched": target["watchedDate"],
            "truth": target["userRating"],
            "history_size": len(history),
            "pred": None,
            "abs_err": None,
            "hit1": False,
            "skipped": True,
            "reason": "",
        }
        if len(history) < min_history:
            record["reason"] = f"история короче {min_history}"
            results.append(record)
            print(f"[{idx}/{total}] Пропуск: «{title_full}» ({target.get('year')}) — история всего {len(history)} (< {min_history})", flush=True)
            continue
        print(f"[{idx}/{total}] Запрос к LLM: «{title_full}», факт: {target['userRating']}... (соседи из истории: {min(len(history), library.NEIGHBOUR_LIMIT)})", flush=True)
        profile_md = _portrait(items, cache)
        near = library.neighbours(history, cache, target)
        tags_by_kid = {kid: rec["tags"] for kid, rec in cache.items() if rec["tags"]}
        rows = library.tagged_rows(near, tags_by_kid) or "(записей-соседей не найдено)"
        prompt = prompts.predict_prompt(profile_md, rows, title_full)
        text = llm.generate(prompt, op="benchmark")
        score = parse_score(text)
        record.update(
            skipped=False, reason="",
            pred=score,
            abs_err=None if score is None else abs(score - target["userRating"]),
            hit1=score is not None and abs(score - target["userRating"]) <= 1,
        )
        print(f"        -> Прогноз: {score}/10 (факт: {target['userRating']}) | Ошибка: {record['abs_err']}", flush=True)
        results.append(record)
    usage = _run_usage(usage_offset)
    _write(results, usage)
    return _summary(results, usage)


def _usage_row_count() -> int:
    if not config.USAGE_FILE.is_file():
        return 0
    return len(config.USAGE_FILE.read_text(encoding="utf-8").strip().splitlines())


def _run_usage(offset: int) -> dict:
    """Суммарный расход токенов op=benchmark за этот прогон."""
    tokens = 0
    if config.USAGE_FILE.is_file():
        lines = config.USAGE_FILE.read_text(encoding="utf-8").strip().splitlines()[offset:]
        for line in lines:
            row = json.loads(line)
            if row.get("op") == "benchmark":
                tokens += (row.get("prompt_tokens", 0) + row.get("thoughts_tokens", 0)
                           + row.get("output_tokens", 0))
    return {"tokens": tokens}


def _summary(results: list[dict], usage: dict | None = None) -> dict:
    scored = [r for r in results if not r["skipped"]]
    valid = [r for r in scored if r["pred"] is not None]
    n = len(scored)
    return {
        "targets": len(results),
        "answered": n,
        "parsed": len(valid),
        "unparsed": n - len(valid),
        "mae": round(sum(r["abs_err"] for r in valid) / len(valid), 2) if valid else None,
        "hit1_share": round(sum(r["hit1"] for r in valid) / len(valid), 2) if valid else None,
        "tokens": usage.get("tokens", 0) if usage else 0,
    }


def _write(results: list[dict], usage: dict | None = None) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = config.DATA_DIR / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"benchmark_{stamp}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = _summary(results, usage)
    lines = [
        f"# Benchmark predict ({stamp})",
        "",
        f"Целей: {summary['targets']}, отвечено: {summary['answered']}, "
        f"распарсено: {summary['parsed']}, не распарсено: {summary['unparsed']}.",
        f"MAE: {summary['mae']}, доля попаданий ±1: {summary['hit1_share']}, "
        f"токенов за прогон: {summary['tokens']}.",
        "",
        "| Название | Год | Факт | Прогноз | Ошибка | Размер истории |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['title']} | {r['year']} | {r['truth']} | {r['pred'] if not r['skipped'] else '—'} "
            f"| {r['abs_err'] if not r['skipped'] else '—'} | {r['history_size']} |"
        )
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Отчёт: {out_dir / 'latest.md'}, данные: {path}")
