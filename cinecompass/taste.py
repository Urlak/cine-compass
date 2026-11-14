"""Расчёт Taste Profile (Этап 4): только Python и факты, без LLM и весов.

Оценённые фильмы разбиты на 4 корзины (9–10, 8, 6–7, 1–5). Связь тегов с оценками
выражается через Approval Rate со сглаживанием Лапласа и Lift относительно базовых
долей библиотеки — частота тега не трактуется как предпочтение.
"""
import json
from collections import Counter
from datetime import datetime
from itertools import combinations

from cinecompass import config, semantic, taxonomy

# Корзины личных оценок и пороги отбора (обычные константы, не настройки .env).
BUCKETS = {"great": "9–10", "good": "8", "neutral": "6–7", "bad": "1–5"}
HIGH_RATING_MIN = 8      # используется library.mode_candidates: нижняя граница «любимого»
SUPPORT_MIN = 10         # минимальная поддержка тега в основной таблице
NICHE_MAX_N = 30         # ниша: тег реже этого количества
NICHE_MIN_APPROVAL = 0.9 # ниша: сырая доля 8–10 не ниже
NICHE_MIN_N = 5
PAIR_MIN_N = 8           # минимальная совместная частота пары тегов
SMOOTHING = 1            # сглаживание Лапласа: +1 успех, +2 наблюдения


def _rate(hits: int, n: int) -> float:
    """Доля со сглаживанием Лапласа; 0, если наблюдений нет."""
    return (hits + SMOOTHING) / (n + 2 * SMOOTHING) if n else 0.0


def film_label(item: dict) -> str:
    """«Название» (Original, YYYY) [оценка] — формат для LLM-контекстов и примеров."""
    ru, orig = item.get("title", ""), item.get("originalTitle", "")
    inner = ", ".join(p for p in (
        orig if orig and orig != ru else "",
        str(item["year"]) if item.get("year") else "",
    ) if p)
    name = f"{ru} ({inner})" if inner else ru
    rating = item.get("userRating")
    return f"{name} [{rating}]" if rating is not None else name


def _examples(tag: str, rows: list, descending: bool, k: int = 3) -> list[str]:
    """Примеры фильмов с тегом: по убыванию оценки для «любимого», по возрастанию для «провального»."""
    films = [(item, item.get("userRating")) for item, rec in rows if tag in rec["tags"]]
    if descending:
        films.sort(key=lambda x: (-x[1], x[0]["title"]))
    else:
        films.sort(key=lambda x: (x[1], x[0]["title"]))
    return [film_label(item) for item, _ in films[:k]]


def build_profile(items: list[dict], cache: dict[int, dict]) -> dict:
    """Все расчёты профиля; чистая функция — IO только на уровне вызова CLI."""
    tax = taxonomy.load()
    tag_category = {t["id"]: t["category"] for t in tax["tags"]}
    tagged = []
    for item in items:
        rec = cache.get(item["kinopoiskId"])
        if rec and rec["status"] in ("complete", "partial") and rec["tags"]:
            tagged.append((item, rec))

    rating = lambda i: i.get("userRating")
    rated = [(i, r) for i, r in tagged if rating(i) is not None]
    buckets = {
        "great": [(i, r) for i, r in rated if rating(i) >= 9],
        "good": [(i, r) for i, r in rated if rating(i) == 8],
        "neutral": [(i, r) for i, r in rated if 6 <= rating(i) <= 7],
        "bad": [(i, r) for i, r in rated if 1 <= rating(i) <= 5],
    }

    status_counts = Counter(rec["status"] for rec in cache.values())
    coverage = {
        "library_total": len(items),
        "cache_records": len(cache),
        "cache_status_counts": dict(status_counts),
        "with_tags": len(tagged),
        "coverage_share": round(len(tagged) / len(items), 2) if items else 0,
        "rated_total": sum(1 for i in items if rating(i) is not None),
        "rated_with_tags": len(rated),
        "note": "Теги записей со статусом complete и partial; insufficient_data исключены "
                "целиком. Теговая статистика считается по оценённым записям с тегами, "
                "фактологические срезы — по всем оценённым записям библиотеки.",
    }

    rated_total = len(rated)
    buckets_counts = {name: len(rows) for name, rows in buckets.items()}
    # Базовые доли для Lift: P(8–10), P(9–10), P(1–5) по всем оценённым с тегами.
    baseline = {
        "8_10": sum(1 for i, _ in rated if rating(i) >= 8) / rated_total,
        "9_10": sum(1 for i, _ in rated if rating(i) >= 9) / rated_total,
        "1_5": sum(1 for i, _ in rated if rating(i) <= 5) / rated_total,
    } if rated_total else {}

    # Approval Rate и Lift по тегам (в основной таблице — поддержка n >= SUPPORT_MIN).
    hits = {
        "8_10": Counter(t for i, rec in rated if rating(i) >= 8 for t in rec["tags"]),
        "9_10": Counter(t for i, rec in rated if rating(i) >= 9 for t in rec["tags"]),
        "1_5": Counter(t for i, rec in rated if rating(i) <= 5 for t in rec["tags"]),
    }
    total = Counter(t for _, rec in rated for t in rec["tags"])
    tag_stats = []
    for tag, n in total.items():
        row = {"tag": tag, "category": tag_category.get(tag, "?"), "n": n}
        for name in ("8_10", "9_10", "1_5"):
            appr = _rate(hits[name].get(tag, 0), n)
            row[f"approval_{name}"] = round(appr, 3)
            row[f"lift_{name}"] = round(appr / baseline[name], 2) if baseline.get(name) else 0
        row["examples"] = _examples(tag, rated, row["approval_8_10"] >= baseline.get("8_10", 0))
        tag_stats.append(row)
    tag_stats.sort(key=lambda r: (-r["lift_8_10"], -r["n"]))

    # Ниши: высокая сырая доля одобрения при малой выборке (сглаживание тут занижает).
    niche = [
        {**r, "approval_8_10_raw": round(hits["8_10"].get(r["tag"], 0) / r["n"], 2)}
        for r in tag_stats
        if NICHE_MIN_N <= r["n"] < NICHE_MAX_N
        and hits["8_10"].get(r["tag"], 0) / r["n"] >= NICHE_MIN_APPROVAL
    ]
    niche.sort(key=lambda r: (-r["approval_8_10_raw"], -r["n"]))

    # Пары тегов: совместная частота и approval 8–10.
    pair_total: Counter = Counter()
    pair_ok: Counter = Counter()
    pair_bad: Counter = Counter()
    for item, rec in rated:
        tags = sorted(set(rec["tags"]))
        if len(tags) < 2:
            continue
        r = rating(item)
        for pair in combinations(tags, 2):
            pair_total[pair] += 1
            if r >= 8:
                pair_ok[pair] += 1
            elif r <= 5:
                pair_bad[pair] += 1

    def _pair_rows(order: str, k: int = 10) -> list[dict]:
        rows = []
        for (a, b), n in pair_total.items():
            if n < PAIR_MIN_N:
                continue
            appr = _rate(pair_ok[(a, b)], n)
            rows.append({
                "tags": [a, b], "n": n,
                "approval_8_10": round(appr, 3),
                "lift_8_10": round(appr / baseline["8_10"], 2) if baseline.get("8_10") else 0,
                "examples": _examples_pair(a, b, rated, appr >= baseline.get("8_10", 0)),
            })
        if order == "best":
            rows.sort(key=lambda r: (-r["approval_8_10"], -r["n"]))
        else:
            rows.sort(key=lambda r: (r["approval_8_10"], -r["n"]))
        return rows[:k]

    def _examples_pair(a: str, b: str, rows: list, descending: bool, k: int = 3) -> list[str]:
        films = [(item, item.get("userRating")) for item, rec in rows
                 if a in rec["tags"] and b in rec["tags"]]
        if descending:
            films.sort(key=lambda x: (-x[1], x[0]["title"]))
        else:
            films.sort(key=lambda x: (x[1], x[0]["title"]))
        return [film_label(item) for item, _ in films[:k]]

    facts = _facts(items)
    pairs_best = _pair_rows("best")
    pairs_worst = [r for r in _pair_rows("worst") if r["tags"] not in [b["tags"] for b in pairs_best]]
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "taxonomy_version": tax["version"],
        "prompt_version": semantic.PROMPT_VERSION,
        "buckets": BUCKETS,
        "buckets_counts": buckets_counts,
        "coverage": coverage,
        "baseline": {name: round(share, 3) for name, share in baseline.items()},
        "tag_stats": tag_stats,
        "niche_tags": niche,
        "pairs": {"best": pairs_best, "worst": pairs_worst},
        "facts": facts,
    }


def _facts(items: list[dict]) -> dict:
    """Фактологические срезы по всем оценённым записям (без тегов и LLM)."""
    rated = [i for i in items if i.get("userRating") is not None]
    great = lambda i: i.get("userRating", 0) >= 9
    ok = lambda i: i.get("userRating", 0) >= 8

    decades = {}
    for i in rated:
        if i.get("year"):
            decades.setdefault(f"{(i['year'] // 10) * 10}-е", []).append(i)
    decade_rows = [{
        "decade": dec, "n": len(rows),
        "approval_8_10": round(sum(map(ok, rows)) / len(rows), 2),
        "approval_9_10": round(sum(map(great, rows)) / len(rows), 2),
        "example": film_label(max(rows, key=lambda i: (i["userRating"], i.get("year") or 0))),
    } for dec, rows in sorted(decades.items())]

    directors: dict[str, list[int]] = {}
    for i in rated:
        for d in i.get("directors", []):
            directors.setdefault(d, []).append(i["userRating"])
    director_rows = [{
        "director": name, "n": len(scores),
        "avg_rating": round(sum(scores) / len(scores), 2),
    } for name, scores in directors.items() if len(scores) >= 3]
    director_rows.sort(key=lambda r: (-r["avg_rating"], -r["n"]))

    deltas = []
    for i in rated:
        consensus = i.get("kpRating") or i.get("tmdbRating")
        if not consensus:
            continue
        deltas.append({
            "title": film_label(i), "user_rating": i["userRating"],
            "consensus_rating": round(consensus, 1),
            "consensus_source": "kp" if i.get("kpRating") else "tmdb",
            "delta": round(i["userRating"] - consensus, 1),
        })
    underrated = sorted(deltas, key=lambda r: -r["delta"])[:10]
    overrated = sorted(deltas, key=lambda r: r["delta"])[:10]

    def _bucket(rows: list) -> dict:
        return {
            "n": len(rows),
            "approval_8_10": round(sum(map(ok, rows)) / len(rows), 2) if rows else 0,
            "approval_9_10": round(sum(map(great, rows)) / len(rows), 2) if rows else 0,
        }

    films_rated = [i for i in rated if i["type"] == "film"]
    series_rated = [i for i in rated if i["type"] == "series"]
    length_rows = []
    for label, lo, hi in (("<100", 0, 100), ("100-140", 100, 141), (">140", 141, 10**9)):
        rows = [i for i in films_rated if i.get("movieLength") and lo <= i["movieLength"] < hi]
        length_rows.append({"bucket": label, **_bucket(rows)})

    votes_rated = sorted((i for i in rated if i.get("tmdbVotes")), key=lambda i: i["tmdbVotes"])
    vote_rows = []
    if votes_rated:
        n = len(votes_rated)
        for rows in (votes_rated[i * n // 4:(i + 1) * n // 4] for i in range(4)):
            if rows:
                vote_rows.append({
                    "votes_range": f"{rows[0]['tmdbVotes']}–{rows[-1]['tmdbVotes']}",
                    "n": len(rows), **_bucket(rows),
                })

    return {
        "decades": decade_rows,
        "directors": director_rows,
        "consensus_delta": {"underrated": underrated, "overrated": overrated},
        "format": {"films": _bucket(films_rated), "series": _bucket(series_rated),
                   "length": length_rows},
        "votes": vote_rows,
    }


def write_profile(profile: dict) -> dict:
    """Сохраняет taste_profile.json и markdown-профиль из JSON."""
    config.TASTE_PROFILE_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(config.TASTE_PROFILE_JSON, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=1)
    return {
        "json": config.TASTE_PROFILE_JSON,
        "md": config.TASTE_PROFILE_MD,
    }
