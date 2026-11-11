"""Тесты Taste Profile (Этап 4): срезы, пороги, честность сигнала, формат."""
from cinecompass import markdown, taste


def _item(kid, title="T", rating=None):
    return {
        "kinopoiskId": kid, "title": title, "originalTitle": "Orig",
        "year": 2000, "type": "film", "userRating": rating,
    }


def _rec(tags, status="complete"):
    return {"kinopoiskId": 0, "tags": tags, "status": status, "taxonomy_version": "1.0",
            "prompt_version": "r3", "model": "m", "fingerprint": "f"}


def _cache():
    return {
        1: _rec(["tense", "family"]),
        2: _rec(["tense", "urban"], status="partial"),
        3: _rec(["prison"], status="insufficient_data"),
        4: _rec(["epic"]),
        5: _rec(["prison", "tense"]),
        6: _rec(["family"]),
        7: _rec(["epic"]),
    }


def _items():
    return [
        _item(1, "A", rating=10),
        _item(2, "B", rating=8),
        _item(3, "C", rating=4),
        _item(4, "D", rating=6),      # вне high/low, но rated
        _item(5, "E", rating=5),
        _item(6, "F", rating=None),
        _item(7, "G", rating=2),
    ]


def test_slices_and_thresholds():
    profile = taste.build_profile(_items(), _cache())
    sl = profile["slices"]
    assert sl["library"]["films_with_tags"] == 6          # insufficient_data исключён
    assert sl["rated"]["films_with_tags"] == 5            # без оценки нет в rated
    assert sl["high_rated"]["films_with_tags"] == 2       # 10 и 8
    assert sl["low_rated"]["films_with_tags"] == 2        # 4 и 5 (2 остался вне кэша... нет: запись 7 есть)
    # запись 7 (рейтинг 2) с тегом epic попадает в low_rated → 3? Проверяем фактическую арифметику ниже
    counts = sl["low_rated"]["tag_counts"]
    assert counts["prison"] == 1 and counts["tense"] == 1 and counts["epic"] == 1


def test_coverage_counts():
    profile = taste.build_profile(_items(), _cache())
    cov = profile["coverage"]
    assert cov["library_total"] == 7
    assert cov["with_tags"] == 6
    assert cov["coverage_share"] == 0.86
    assert cov["rated_with_tags"] == 5
    assert cov["cache_status_counts"]["insufficient_data"] == 1


def test_rating_signal_shares_and_overlap():
    profile = taste.build_profile(_items(), _cache())
    sig = profile["rating_signal"]
    table = {r["tag"]: r for r in sig["share_table"]}
    assert table["tense"]["high_count"] == 2 and table["tense"]["low_count"] == 1
    assert table["tense"]["high_share"] == 1.0 and table["tense"]["low_share"] == 0.5
    assert table["epic"]["low_share"] == 0.5 and table["epic"]["high_count"] == 0
    assert sig["in_both_groups"] == ["tense"]  # prison — только в low (запись 3 исключена)
    # сортировка по убыванию разницы долей
    diffs = [r["share_diff"] for r in sig["share_table"]]
    assert diffs == sorted(diffs, reverse=True)
    assert sig["thresholds"] == {"high": "8-10", "low": "1-5"}


def test_markdown_self_contained():
    profile = taste.build_profile(_items(), _cache())
    md = markdown.taste_profile_markdown(profile)
    assert "# Taste Profile" in md
    assert "Покрытие данных" in md
    assert "6" in md and "86%" in md or "выводы ниже" in md
    assert "| tense | 2 (100%) | 1 (50%) | +0.50 |" in md
    assert "не вывод о предпочтении" in md
    assert "insufficient_data" in md
