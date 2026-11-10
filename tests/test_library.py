"""Тесты чистки/дедупликации библиотеки."""
import json
from types import SimpleNamespace

from cinecompass.library import clean_items, compact_rows, duration, missing_enrichment


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


def test_duration_is_minutes_not_seasons_for_series():
    assert duration({"movieLength": "116"}) == "1 ч 56 мин"
    assert duration({"seriesLength": 47}) == "сер. 47 мин"
    assert duration({}) == ""


def test_log_usage_appends_jsonl_row(tmp_path, monkeypatch):
    from cinecompass import config, llm
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.jsonl")
    usage = SimpleNamespace(
        prompt_token_count=57000,
        thoughts_token_count=5468,
        candidates_token_count=1230,
        cached_content_token_count=57322,
    )
    llm._log_usage(SimpleNamespace(usage_metadata=usage), op="predict", retry=False)
    row = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["op"] == "predict"
    assert row["prompt_tokens"] == 57000
    assert row["thoughts_tokens"] == 5468
    assert row["output_tokens"] == 1230
    assert row["retry"] is False
    assert row["ts"]
