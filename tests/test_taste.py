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
        _item(1, rating=10, year=1994, type="film", directors=["Иванов"], kpRating=7.0, movieLength=90, tmdbVotes=1000),
        _item(2, rating=9, year=1994, type="film", directors=["Иванов"], kpRating=8.0, movieLength=120, tmdbVotes=100),
        _item(3, rating=4, year=2004, type="film", directors=["Иванов"], kpRating=8.5, movieLength=160, tmdbVotes=10),
        _item(4, rating=8, year=2004, type="series", directors=["Петров"], tmdbRating=7.0, tmdbVotes=1),
        _item(5, rating=7, year=2004, type="film", kpRating=6.0, tmdbRating=8.0),
        _item(6, rating=8, year=2004, type="film", tmdbRating=7.0, tmdbVotes=50),
    ]
    profile = taste.build_profile(items, {k: _rec(["t"]) for k in range(1, 7)})
    facts = profile["facts"]
    assert {r["decade"]: r["n"] for r in facts["decades"]} == {"1990-е": 2, "2000-е": 4}
    assert facts["directors"][0]["director"] == "Иванов" and facts["directors"][0]["avg_rating"] == 7.67
    # Петров: 1 фильм — в списке режиссёров отсутствует
    assert all(r["director"] != "Петров" for r in facts["directors"])
    # Запись 4 с tmdbVotes=1 отфильтрована как шум; запись 6 (tmdbVotes=50) попадает в consensus_delta
    # Приоритет в underrated у более высокой личной оценки (10 перед 8 и 7)
    assert facts["consensus_delta"]["underrated"][0]["delta"] == 3.0    # 10 − 7
    assert facts["consensus_delta"]["overrated"][0]["delta"] == -4.5    # 4 − 8.5
    tmdb_rows = [r for r in facts["consensus_delta"]["underrated"] if r["consensus_source"] == "tmdb"]
    assert len(tmdb_rows) == 1 and tmdb_rows[0]["delta"] == 1.0 and tmdb_rows[0]["consensus_rating"] == 7.0
    both_row = next(r for r in facts["consensus_delta"]["underrated"] if r["consensus_source"] == "both")
    assert both_row["consensus_rating"] == 7.0 and both_row["delta"] == 0.0   # 7 − (6+8)/2
    assert facts["format"]["films"]["n"] == 5 and facts["format"]["series"]["n"] == 1
    buckets = {r["bucket"]: r["n"] for r in facts["format"]["length"]}
    assert buckets == {"<100": 1, "100-140": 1, ">140": 1}
    # Квартили голосов: отсортированы по возрастанию, все 5 записей с tmdbVotes
    assert len(facts["votes"]) == 4 and sum(r["n"] for r in facts["votes"]) == 5


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
    assert "Мейнстримность" not in md


def test_markdown_tag_table_row():
    items = [_item(kid, rating=9) for kid in range(1, 13)]          # 12 фильмов, все 9
    items += [_item(kid, rating=3) for kid in range(13, 17)]        # 4 провала
    cache = {k: _rec(["tense"] if k <= 12 else ["x"]) for k in range(1, 17)}
    md = markdown.taste_profile_markdown(taste.build_profile(items, cache))
    # tense: 8–10 (13/14), 9–10 (13/14), 1–5 (1/14), lift = 0.93/0.75
    assert "| tense | 12 | 93% | 93% | 7% | 1.24 |" in md
    assert "Покрытие частичное" not in md
    assert "### Якоря по корзинам оценок" in md


def test_niche_by_lift_and_neutral_contrast_examples():
    # Строгий зритель: база 5/20 = 25%, но ниша "niche" имеет 4/6 (Lift > 2)
    items = [_item(k, title=f"N{k}", rating=9 if k <= 4 else 5) for k in range(1, 7)]
    items += [_item(k, title=f"M{k}", rating=9 if k == 7 else 6) for k in range(7, 21)]
    cache = {k: _rec(["niche"] if k <= 6 else ["mid"]) for k in range(1, 21)}
    # mid: (1+1)/(14+2) = 0.125; добавим тег "mix" с 1/6 (approval 0.25, Lift = 1.0)
    for k in (1, 8, 9, 10, 11, 12):
        cache[k]["tags"].append("mix")
    profile = taste.build_profile(items, cache)
    assert [r["tag"] for r in profile["niche_tags"]] == ["niche"]
    mix_row = next(r for r in profile["tag_stats"] if r["tag"] == "mix")
    assert mix_row["examples"] == ["N1 (Orig, 2000) [9]", "M10 (Orig, 2000) [6]"]


def test_tag_roles_rescue_and_anchor_diversity():
    items, cache = [], {}
    # 20 фильмов с core (9-10) и 20 проходных/провальных для реалистичной базы
    for k in range(1, 21):
        items.append(_item(k, f"Core{k}", rating=9))
        cache[k] = _rec(["core_tag"])
    for k in range(21, 31):
        items.append(_item(k, f"Fail{k}", rating=3))
        cache[k] = _rec(["bad_tag"])
    for k in range(31, 41):
        items.append(_item(k, f"Ceil{k}", rating=7))
        cache[k] = _rec(["ceil_tag"])
    # Конфликтная пара bad_tag + mid (8 провалов на 6) и спасающая mid + core_tag (8 успехов на 9)
    for k in range(41, 49):
        items.append(_item(k, f"Conf{k}", rating=6))
        cache[k] = _rec(["bad_tag", "mid"])
    for k in range(49, 57):
        items.append(_item(k, f"Resc{k}", rating=9))
        cache[k] = _rec(["mid", "core_tag"])
    # Два разножанровых фильма в корзине 8 с разными тегами: оба должны попасть в якоря раньше дублей
    for k in range(57, 63):
        items.append(_item(k, f"G_A{k}", rating=8, genres=["Драма"]))
        cache[k] = _rec(["core_tag"])
    items.append(_item(63, "G_SciFi", rating=8, genres=["Фантастика"]))
    cache[63] = _rec(["alt_tag"])
    for k in range(64, 68):
        items.append(_item(k, f"AltHit{k}", rating=9, genres=["Фантастика"]))
        cache[k] = _rec(["alt_tag"])

    profile = taste.build_profile(items, cache)
    roles = {k: {r["tag"] for r in v} for k, v in profile["tag_roles"].items()}
    assert "core_tag" in roles["core"]
    assert "bad_tag" in roles["red_flags"]
    assert "ceil_tag" in roles["ceilings"] and "ceil_tag" not in roles["red_flags"]
    assert "alt_tag" in roles["growth"]

    worst = profile["pairs"]["worst"]
    assert worst and worst[0].get("rescue")
    assert worst[0]["rescue"]["tags"] == ["core_tag", "mid"]

    anchors_8 = profile["bucket_anchors"]["good"]
    assert "G_SciFi (Orig, 2000) [8]" in anchors_8
    md = markdown.taste_profile_markdown(profile)
    assert "## Роли тегов" in md and "→ смягчается при" in md
