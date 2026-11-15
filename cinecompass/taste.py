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
CORE_MIN_N = 20          # минимальная поддержка для Core Drivers
NICHE_MAX_N = 40         # ниша: тег реже этого количества
NICHE_MIN_APPROVAL = 0.85 # ниша: сырая доля 8–10 (для высоких баз)
NICHE_MIN_LIFT = 1.2     # Lift 8–10 ≥ 1.2 относительно базы зрителя
NICHE_MIN_LIFT_9_10 = 1.5 # или высокая конверсия в 9–10 (например, slow-reveal)
NICHE_MIN_N = 5
PAIR_MIN_N = 8           # минимальная совместная частота пары тегов
PAIR_RESCUE_DELTA = 0.25 # минимальный прирост одобрения для «спасающей» пары
CONSENSUS_MIN_VOTES = 50 # порог голосов TMDB для расчёта консенсуса без КП
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


def _examples(tag: str, rows: list, lift: float, k: int = 3) -> list[str]:
    """Примеры фильмов с тегом: по убыванию для высокого Lift, по возрастанию для низкого,
    и контрастная пара (лучший + худший) для пограничной зоны 0.9 < Lift < 1.1."""
    films = [(item, item.get("userRating")) for item, rec in rows if tag in rec["tags"]]
    if not films:
        return []
    asc = sorted(films, key=lambda x: (x[1], x[0]["title"]))
    desc = sorted(films, key=lambda x: (-x[1], x[0]["title"]))
    if 0.9 < lift < 1.1 and len(films) >= 2:
        best, worst = desc[0][0], asc[0][0]
        return [film_label(best)] if best is worst else [film_label(best), film_label(worst)]
    chosen = desc if lift >= 1.1 else asc
    return [film_label(item) for item, _ in chosen[:k]]


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

    status_counts = Counter(
        rec["status"] for item in items if (rec := cache.get(item["kinopoiskId"]))
    )
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
        row["examples"] = _examples(tag, rated, row["lift_8_10"])
        tag_stats.append(row)
    tag_stats.sort(key=lambda r: (-r["lift_8_10"], -r["n"]))

    # Ниши: высокий Lift относительно базы (или конверсия в 9–10) при малой выборке.
    niche = [
        {**r, "approval_8_10_raw": round(hits["8_10"].get(r["tag"], 0) / r["n"], 2)}
        for r in tag_stats
        if NICHE_MIN_N <= r["n"] < NICHE_MAX_N
        and (
            r["lift_8_10"] >= NICHE_MIN_LIFT
            or r["lift_9_10"] >= NICHE_MIN_LIFT_9_10
            or hits["8_10"].get(r["tag"], 0) / r["n"] >= NICHE_MIN_APPROVAL
        )
    ]
    niche.sort(key=lambda r: (-r["lift_8_10"], -r["n"]))

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

    def _examples_pair(a: str, b: str, rows: list, descending: bool, k: int = 3) -> list[str]:
        films = [(item, item.get("userRating")) for item, rec in rows
                 if a in rec["tags"] and b in rec["tags"]]
        if descending:
            films.sort(key=lambda x: (-x[1], x[0]["title"]))
        else:
            films.sort(key=lambda x: (x[1], x[0]["title"]))
        return [film_label(item) for item, _ in films[:k]]

    base_8_10 = baseline.get("8_10", 0)
    all_pairs = []
    for (a, b), n in pair_total.items():
        if n < PAIR_MIN_N:
            continue
        appr = _rate(pair_ok[(a, b)], n)
        all_pairs.append({
            "tags": [a, b], "n": n,
            "approval_8_10": round(appr, 3),
            "lift_8_10": round(appr / base_8_10, 2) if base_8_10 else 0,
            "examples": _examples_pair(a, b, rated, appr >= base_8_10),
        })

    pairs_best = sorted(
        (r for r in all_pairs if r["approval_8_10"] > base_8_10),
        key=lambda r: (-r["approval_8_10"], -r["n"]),
    )[:10]
    best_tags = {tuple(b["tags"]) for b in pairs_best}
    pairs_worst = [
        dict(r) for r in sorted(
            (r for r in all_pairs if r["approval_8_10"] < base_8_10),
            key=lambda r: (r["approval_8_10"], -r["n"]),
        )[:10]
        if tuple(r["tags"]) not in best_tags
    ]
    for row in pairs_worst:
        pair_set = set(row["tags"])
        candidates = [
            p for p in all_pairs
            if (pair_set & set(p["tags"])) and tuple(p["tags"]) != tuple(row["tags"])
            and p["approval_8_10"] >= max(base_8_10, 0.50)
            and p["approval_8_10"] - row["approval_8_10"] >= PAIR_RESCUE_DELTA
        ]
        if candidates:
            top = max(candidates, key=lambda p: (p["approval_8_10"], p["n"]))
            row["rescue"] = {
                "tags": top["tags"], "n": top["n"],
                "approval_8_10": top["approval_8_10"], "examples": top["examples"],
            }

    facts = _facts(items)
    lift_8 = {r["tag"]: r["lift_8_10"] for r in tag_stats}
    lift_9 = {r["tag"]: r["lift_9_10"] for r in tag_stats}
    lift_1 = {r["tag"]: r["lift_1_5"] for r in tag_stats}
    bucket_anchors = {
        name: _diverse_anchors(rows, name, lift_8, lift_9, lift_1)
        for name, rows in buckets.items()
    }
    tag_roles = _classify_tag_roles(tag_stats, hits["1_5"], baseline, niche)
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "taxonomy_version": tax["version"],
        "prompt_version": semantic.PROMPT_VERSION,
        "buckets": BUCKETS,
        "buckets_counts": buckets_counts,
        "bucket_anchors": bucket_anchors,
        "coverage": coverage,
        "baseline": {name: round(share, 3) for name, share in baseline.items()},
        "tag_stats": tag_stats,
        "niche_tags": niche,
        "tag_roles": tag_roles,
        "pairs": {"best": pairs_best, "worst": pairs_worst},
        "facts": facts,
    }


def _diverse_anchors(rows: list, bucket: str, lift_8: dict, lift_9: dict,
                     lift_1: dict, k: int = 5) -> list[str]:
    """Жадный отбор якорей корзины со штрафом за повтор тегов и жанров."""
    def _weight(t: str) -> float:
        l8, l9, l1 = lift_8.get(t, 1.0), lift_9.get(t, 1.0), lift_1.get(t, 1.0)
        if bucket == "great":
            return l9 - 1.0
        if bucket == "good":
            return (l8 - 1.0) - 0.5 * max(0.0, l1 - 1.2)
        if bucket == "neutral":
            return (1.0 - l8) - max(0.0, l1 - 1.3)
        return (l1 - 1.0) + 0.5 * max(0.0, 1.0 - l8)

    remaining = list(rows)
    seen_tags: Counter = Counter()
    seen_genres: Counter = Counter()
    picked = []
    while remaining and len(picked) < k:
        best_idx = max(
            range(len(remaining)),
            key=lambda idx: (
                sum(w / (1 + seen_tags[t]) if (w := _weight(t)) > 0 else w
                    for t in remaining[idx][1]["tags"])
                - 0.2 * sum(seen_genres[g] for g in remaining[idx][0].get("genres", [])),
                len(remaining[idx][1]["tags"]),
                # Детерминированный обратный порядок по названию при прочих равных.
                tuple(-ord(c) for c in remaining[idx][0]["title"]),
            ),
        )
        item, rec = remaining.pop(best_idx)
        picked.append(film_label(item))
        seen_tags.update(rec["tags"])
        seen_genres.update(item.get("genres", []))
    return picked


def _classify_tag_roles(tag_stats: list[dict], bad_hits: Counter,
                        baseline: dict, niche: list[dict]) -> dict:
    """Разделяет теги на 4 роли: Core, Exploration/Growth, Потолки (6–7) и Красные флаги (1–5)."""
    base_1_5 = baseline.get("1_5", 0)
    red_flags = [
        r for r in tag_stats
        if r["n"] >= SUPPORT_MIN and bad_hits.get(r["tag"], 0) >= 2
        and (
            (r["lift_8_10"] < 0.90 and r["approval_1_5"] >= base_1_5 + 0.04)
            or (r["lift_8_10"] < 1.0 and r["approval_1_5"] >= base_1_5 + 0.08)
        )
    ]
    red_flags.sort(key=lambda r: (-r["lift_1_5"], r["lift_8_10"], -r["n"]))
    red_set = {r["tag"] for r in red_flags}

    ceilings = [
        r for r in tag_stats
        if r["n"] >= SUPPORT_MIN and r["tag"] not in red_set
        and (r["lift_8_10"] <= 0.85 or (r["lift_9_10"] <= 0.55 and r["lift_8_10"] < 1.05))
    ]
    ceilings.sort(key=lambda r: (r["lift_8_10"], r["lift_9_10"], -r["n"]))
    ceil_set = {r["tag"] for r in ceilings}

    core = [
        r for r in tag_stats
        if r["n"] >= CORE_MIN_N and r["tag"] not in red_set and r["tag"] not in ceil_set
        and r["lift_8_10"] >= 1.15
        and (r["lift_9_10"] >= 1.15 or r["lift_8_10"] >= 1.30)
        and r["approval_1_5"] <= base_1_5 + 0.06
    ]
    core.sort(key=lambda r: (-r["lift_8_10"], -r["lift_9_10"], -r["n"]))
    core_set = {r["tag"] for r in core}

    niche_set = {r["tag"] for r in niche}
    growth = [
        r for r in tag_stats
        if r["n"] >= NICHE_MIN_N and r["tag"] not in core_set
        and r["tag"] not in red_set and r["tag"] not in ceil_set
        and (
            r["tag"] in niche_set
            or (r["lift_9_10"] >= NICHE_MIN_LIFT_9_10 and r["approval_1_5"] <= base_1_5 + 0.06)
        )
    ]
    growth.sort(key=lambda r: (-r["lift_9_10"], -r["lift_8_10"], -r["n"]))
    return {"core": core, "growth": growth, "ceilings": ceilings, "red_flags": red_flags}


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
        kp = i.get("kpRating")
        tm = i.get("tmdbRating") if (i.get("tmdbVotes") is None or i.get("tmdbVotes", 0) >= CONSENSUS_MIN_VOTES) else None
        consensus = (kp + tm) / 2 if kp and tm else (kp or tm)
        if not consensus:
            continue
        source = "kp" if kp and not tm else "tmdb" if tm and not kp else "both"
        deltas.append({
            "title": film_label(i), "user_rating": i["userRating"],
            "consensus_rating": round(consensus, 1),
            "consensus_source": source,
            "delta": round(i["userRating"] - consensus, 1),
        })
    underrated = sorted(deltas, key=lambda r: (-r["user_rating"], -r["delta"]))[:10]
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
