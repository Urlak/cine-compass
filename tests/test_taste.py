"""Тесты Taste Profile (Этап 4): корзины, Approval/Lift, ниши, пары, факты, формат."""
from cinecompass import markdown, taste


def _item(kid, title="T", rating=None, **extra):
    item = {
        "kinopoiskId": kid, "title": title, "originalTitle": "Orig",
        "year": 2000, "type": "film", "userRating": rating,
    }
    item.update(extra)
    return item


def _rec(tags, status="complete"):
    return {"kinopoiskId": 0, "tags": tags, "status": status, "taxonomy_version": "1.0",
            "prompt_version": "r4", "model": "m", "fingerprint": "f"}


def _items():
    return [
        _item(1, "A", rating=10),
        _item(2, "B", rating=8),
        _item(3, "C", rating=4),
        _item(4, "D", rating=6),      # neutral: раньше не учитывался
        _item(5, "E", rating=5),
        _item(6, "F", rating=None),
        _item(7, "G", rating=2),
    ]


def _cache():
    return {
        1: _rec(["tense", "family"]),
        2: _rec(["tense", "urban"], status="partial"),
        3: _rec(["prison"], status="insufficient_data"),   # исключён целиком
        4: _rec(["epic"]),
        5: _rec(["prison", "tense"]),
        6: _rec(["family"]),
        7: _rec(["epic"]),
    }


def test_buckets_coverage_and_exclusion():
    profile = taste.build_profile(_items(), _cache())
    assert profile["buckets_counts"] == {"great": 1, "good": 1, "neutral": 1, "bad": 2}
    cov = profile["coverage"]
    assert cov["with_tags"] == 6 and cov["rated_with_tags"] == 5
    assert cov["cache_status_counts"]["insufficient_data"] == 1
    # тег prison — только через запись E (запись C insufficient_data)
    tags = {r["tag"]: r for r in profile["tag_stats"]}
    assert tags["prison"]["n"] == 1 and tags["tense"]["n"] == 3
    assert profile["prompt_version"] == "r4"


def test_approval_lift_and_examples():
    profile = taste.build_profile(_items(), _cache())
    tags = {r["tag"]: r for r in profile["tag_stats"]}
    # baseline 8–10 = 2/5 = 0.4; tense: (2+1)/(3+2) = 0.6 → lift 1.5
    assert profile["baseline"]["8_10"] == 0.4
    assert tags["tense"]["approval_8_10"] == 0.6 and tags["tense"]["lift_8_10"] == 1.5
    assert tags["tense"]["approval_9_10"] == 0.4 and tags["tense"]["approval_1_5"] == 0.4
    # epic: (0+1)/(2+2) = 0.25 → lift 0.62
    assert tags["epic"]["approval_8_10"] == 0.25 and tags["epic"]["lift_8_10"] == 0.62
    # сортировка по убыванию lift 8–10; порядок строк детерминирован
    lifts = [r["lift_8_10"] for r in profile["tag_stats"]]
    assert lifts == sorted(lifts, reverse=True)
    # одобренный тег: примеры по убыванию оценки; провальный — по возрастанию
    assert tags["tense"]["examples"][0] == "A (Orig, 2000) [10]"
    assert tags["epic"]["examples"][0] == "G (Orig, 2000) [2]"


def test_niche_and_pairs():
    items, cache = [], {}
    for kid in range(1, 9):                       # 8 фильмов с парой y+z, оценка 9
        items.append(_item(kid, rating=9))
        cache[kid] = _rec(["y", "z"])
    for kid in range(9, 14):                      # 5 фильмов с редким тегом x, оценка 10
        items.append(_item(kid, rating=10))
        cache[kid] = _rec(["x"])
    for kid in range(14, 18):                     # добор: пары ниже порога не считаются
        items.append(_item(kid, rating=3))
        cache[kid] = _rec(["w"])
    profile = taste.build_profile(items, cache)
    assert sorted(r["tag"] for r in profile["niche_tags"]) == ["x", "y", "z"]   # n∈[5,30), сырая доля 100%
    best = profile["pairs"]["best"]
    worst = profile["pairs"]["worst"]
    assert best and best[0]["tags"] == ["y", "z"] and best[0]["n"] == 8
    assert worst == []                            # пары w/w нет, прочие ниже n=8


def test_facts_aggregates():
    items = [
        _item(1, rating=10, year=1994, type="film", directors=["Иванов"], kpRating=7.0, movieLength=90),
        _item(2, rating=9, year=1994, type="film", directors=["Иванов"], kpRating=8.0, movieLength=120),
        _item(3, rating=4, year=2004, type="film", directors=["Иванов"], kpRating=8.5, movieLength=160),
        _item(4, rating=8, year=2004, type="series", directors=["Петров"]),
    ]
    profile = taste.build_profile(items, {k: _rec(["t"]) for k in range(1, 5)})
    facts = profile["facts"]
    assert {r["decade"]: r["n"] for r in facts["decades"]} == {"1990-е": 2, "2000-е": 2}
    assert facts["directors"][0]["director"] == "Иванов" and facts["directors"][0]["avg_rating"] == 7.67
    # Петров: 1 фильм — в списке режиссёров отсутствует
    assert all(r["director"] != "Петров" for r in facts["directors"])
    assert facts["kp_delta"]["underrated"][0]["delta"] == 3.0    # 10 − 7
    assert facts["kp_delta"]["overrated"][0]["delta"] == -4.5    # 4 − 8.5
    assert facts["format"]["films"]["n"] == 3 and facts["format"]["series"]["n"] == 1
    buckets = {r["bucket"]: r["n"] for r in facts["format"]["length"]}
    assert buckets == {"<100": 1, "100-140": 1, ">140": 1}


def test_markdown_self_contained():
    profile = taste.build_profile(_items(), _cache())
    md = markdown.taste_profile_markdown(profile)
    assert "# Taste Profile" in md
    assert "## Метаданные" in md and "tagged_count" in md and "generated_at" in md
    assert "Approval Rate и Lift" in md
    # в маленькой фикстуре ни один тег не дотягивает до поддержки n ≥ 10
    assert "ещё 5 тегов с n < 10 в JSON" in md
    assert "Пары тегов с минимальным одобрением" in md
    assert "нет пар с достаточной поддержкой" in md
    assert "### Десятилетия выпуска" in md
    assert "Недооценённые рынком" in md


def test_markdown_tag_table_row():
    items = [_item(kid, rating=9) for kid in range(1, 13)]          # 12 фильмов, все 9
    items += [_item(kid, rating=3) for kid in range(13, 17)]        # 4 провала
    cache = {k: _rec(["tense"] if k <= 12 else ["x"]) for k in range(1, 17)}
    md = markdown.taste_profile_markdown(taste.build_profile(items, cache))
    # tense: 8–10 (13/14), 9–10 (13/14), 1–5 (1/14), lift = 0.93/0.75
    assert "| tense | 12 | 93% | 93% | 7% | 1.24 |" in md
