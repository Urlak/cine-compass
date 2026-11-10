"""Ретроспективный benchmark для predict (Фаза 0 плана оптимизации).

Python строит профиль по записям, просмотренным строго ДО даты X, скрывает
запись, реальную оценку которой нужно угадать, и сравнивает прогноз с фактом.
Цель — получить базовые MAE / доля попаданий ±1 / средние токены и латентность
текущей архитектуры, чтобы доказывать или опровергать пользу будущих изменений.
"""
import json
import random
import re
from datetime import datetime

from cinecompass import config, library, llm, markdown, prompts

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


def run(per_rating: int = 3, min_history: int = 50) -> dict:
    items = library.load_library()
    targets = build_sample(items, per_rating=per_rating)
    results = []
    total = len(targets)
    print(f"Запуск бенчмарка: {total} целей (по {per_rating} на каждый балл от 4 до 10)...", flush=True)
    for idx, target in enumerate(targets, 1):
        history = profile_history(items, target)
        title_full = target["title"] + (f" ({target['originalTitle']})" if target.get("originalTitle") else "")
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
        print(f"[{idx}/{total}] Запрос к LLM: «{title_full}» ({target.get('year')}), факт: {target['userRating']}... (история: {len(history)})", flush=True)
        rows = library.compact_rows(history)
        # A1: передаем полную программную сводку вместо обрезанной
        overview = markdown._overview(history)
        question = title_full
        prompt = prompts.predict_prompt(rows, overview, question)
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
    _write(results)
    return _summary(results)


def _summary(results: list[dict]) -> dict:
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
    }


def _write(results: list[dict]) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = config.DATA_DIR / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"benchmark_{stamp}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = _summary(results)
    lines = [
        f"# Benchmark predict ({stamp})",
        "",
        f"Целей: {summary['targets']}, отвечено: {summary['answered']}, "
        f"распарсено: {summary['parsed']}, не распарсено: {summary['unparsed']}.",
        f"MAE: {summary['mae']}, доля попаданий ±1: {summary['hit1_share']}.",
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
