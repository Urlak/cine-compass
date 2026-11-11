"""Расчёт Taste Profile (Этап 4): только Python и факты, без LLM и весов.

Четыре среза — library / rated / high_rated / low_rated; частоты тегов сохраняются
реальными числами. Частота тега не трактуется как предпочтение: связь с оценками
показывается через сравнение долей с явной оговоркой.
"""
import json
from collections import Counter
from datetime import datetime

from cinecompass import config, taxonomy

# Пороги личных оценок для срезов (обычные константы, не настройки .env).
HIGH_RATING_MIN = 8
LOW_RATING_MAX = 5


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
    slices = {
        "library": tagged,
        "rated": [(i, r) for i, r in tagged if rating(i) is not None],
        "high_rated": [(i, r) for i, r in tagged if rating(i) is not None and rating(i) >= HIGH_RATING_MIN],
        "low_rated": [(i, r) for i, r in tagged if rating(i) is not None and 1 <= rating(i) <= LOW_RATING_MAX],
    }

    status_counts = Counter(rec["status"] for rec in cache.values())
    coverage = {
        "library_total": len(items),
        "cache_records": len(cache),
        "cache_status_counts": dict(status_counts),
        "with_tags": len(tagged),
        "coverage_share": round(len(tagged) / len(items), 2) if items else 0,
        "rated_with_tags": len(slices["rated"]),
        "note": "Использованы теги записей со статусом complete и partial; "
                "insufficient_data исключены целиком.",
    }

    slices_json = {}
    for name, rows in slices.items():
        counts = Counter(t for _, rec in rows for t in rec["tags"])
        by_cat: dict[str, dict[str, int]] = {}
        for tag, n in counts.items():
            by_cat.setdefault(tag_category.get(tag, "?"), {})[tag] = n
        examples = {}
        for tag in [t for t, _ in counts.most_common(8)]:
            titles = []
            for item, rec in rows:
                if tag in rec["tags"]:
                    ru, orig = item.get("title", ""), item.get("originalTitle", "")
                    titles.append(f"{ru} ({orig})" if orig and orig != ru else ru)
            examples[tag] = titles[:3]
        slices_json[name] = {
            "films_with_tags": len(rows),
            "tag_counts": {t: n for t, n in counts.most_common()},
            "by_category": by_cat,
            "examples": examples,
        }

    high_counts = Counter(t for _, r in slices["high_rated"] for t in r["tags"])
    low_counts = Counter(t for _, r in slices["low_rated"] for t in r["tags"])
    signal = []
    for tag in sorted(set(high_counts) | set(low_counts)):
        hn, ln = high_counts.get(tag, 0), low_counts.get(tag, 0)
        h_share = round(hn / len(slices["high_rated"]), 2) if slices["high_rated"] else 0
        l_share = round(ln / len(slices["low_rated"]), 2) if slices["low_rated"] else 0
        signal.append({
            "tag": tag, "high_count": hn, "high_share": h_share,
            "low_count": ln, "low_share": l_share,
            "share_diff": round(h_share - l_share, 2),
        })
    signal.sort(key=lambda r: (-r["share_diff"], -r["high_count"]))
    overlap = sorted(t for t in set(high_counts) & set(low_counts))
    rating_signal = {
        "thresholds": {"high": f"{HIGH_RATING_MIN}-10", "low": f"1-{LOW_RATING_MAX}"},
        "high_rated_films": len(slices["high_rated"]),
        "low_rated_films": len(slices["low_rated"]),
        "share_table": signal,
        "in_both_groups": overlap,
        "note": "Разница долей — наводка, а не вывод о предпочтении: частый тег "
                "может просто отражать состав библиотеки. Теги с единичными "
                "количествами сохранены в таблице без интерпретации.",
    }

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "taxonomy_version": tax["version"],
        "prompt_version": "r3",
        "title_label": "title «Русское» (Original)",
        "coverage": coverage,
        "slices": slices_json,
        "rating_signal": rating_signal,
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
