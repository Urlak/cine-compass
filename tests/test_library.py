"""Тесты чистки/дедупликации библиотеки."""
from cinecompass.library import clean_items, compact_rows, missing_enrichment


def _raw(kp_id, title, rating="8", watched="2020-01-01", **extra):
    item = {
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
    item.update(extra)
    return item


def test_clean_dedups_and_keeps_latest_rating():
    items = clean_items([
        _raw(1, "Старая запись", rating="7", watched="2010-05-05"),
        _raw(1, "Старая запись", rating="9", watched="2015-06-06"),
    ])
    assert len(items) == 1
    assert items[0]["userRating"] == 9
    assert items[0]["watchedDate"] == "2015-06-06"
    assert items[0]["rewatchCount"] == 2


def test_clean_normalizes_fields():
    items = clean_items([_raw(2, "Фильм", rating="bad", year="xx")])
    it = items[0]
    assert it["userRating"] is None
    assert it["year"] is None
    assert missing_enrichment(it)


def test_compact_rows_skips_empty_fields():
    rows = compact_rows(clean_items([_raw(3, "Коро́ль")]))
    assert "Коро́ль" in rows
    assert "  " not in rows and "|" in rows
