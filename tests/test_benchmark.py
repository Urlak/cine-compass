"""Тесты benchmark-конвейера (Фаза 0): выборка целей, отсечение утечек, парсер."""
from cinecompass.benchmark import parse_score, profile_history, build_sample


def _item(kp_id, title, rating="8", watched="2020-01-01"):
    return {
        "title": title,
        "originalTitle": title,
        "year": "2001",
        "type": "film",
        "kinopoiskId": str(kp_id),
        "kinopoiskUrl": f"https://www.kinopoisk.ru/film/{kp_id}/",
        "userRating": rating,
        "watchedDate": watched,
        "tmdbId": "",
        "imdbId": "",
    }


def test_profile_history_cutoff_and_target_excluded():
    items = [
        _item(1, "Рано", "8", watched="2010-06-01"),
        _item(2, "Позже", "7", watched="2015-06-01"),
        _item(3, "Цель", "9", watched="2015-06-01"),
        _item(4, "Ещё позже", "6", watched="2020-01-01"),
    ]
    hist = profile_history(items, items[2])
    ids = [i["kinopoiskId"] for i in hist]
    assert ids == ["1"], "в истории не должно быть ни цели, ни записей после её даты"


def test_parse_score():
    assert parse_score("Оценка: 8/10") == 8
    assert parse_score("…прогноз: **7/10**") == 7
    assert parse_score("Оценка: 10") == 10
    assert parse_score("Без оценки") is None
    assert parse_score("Оценка: 12/10") is None  # вне диапазона 1..10


def test_build_sample_stratifies_and_deterministic():
    items = []
    kp = 1
    for rating in (4, 6, 9):
        for n in range(5):
            items.append(_item(kp, f"t{kp}", rating, watched=f"20{10 + n}-01-0{n + 1}"))
            kp += 1
    a = build_sample(items, per_rating=2)
    b = build_sample(items, per_rating=2)
    counts = {}
    for i in a:
        counts[i["userRating"]] = counts.get(i["userRating"], 0) + 1
    assert counts == {4: 2, 6: 2, 9: 2}
    assert [i["kinopoiskId"] for i in a] == [i["kinopoiskId"] for i in b]
