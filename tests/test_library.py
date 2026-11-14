"""Тесты чистки/дедупликации библиотеки."""
import json
from types import SimpleNamespace

from cinecompass.library import _load_export_csv, clean_items, compact_rows, duration, find_item_by_title, missing_enrichment, normalize_title


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


def test_mode_candidates_filters_by_mode_not_by_tags():
    from cinecompass.library import mode_candidates

    items = [
        {"kinopoiskId": 1, "title": "A", "originalTitle": "A", "year": 1995, "type": "film", "userRating": 9},
        {"kinopoiskId": 2, "title": "B", "originalTitle": "B", "year": 2023, "type": "film", "userRating": 6},
        {"kinopoiskId": 3, "title": "C", "originalTitle": "C", "year": 1985, "type": "film", "userRating": 4},
        {"kinopoiskId": 4, "title": "D", "originalTitle": "D", "year": 1970, "type": "film", "userRating": None},
    ]
    assert [i["kinopoiskId"] for i in mode_candidates(items, "old")] == [1]
    assert [i["kinopoiskId"] for i in mode_candidates(items, "new")] == [2]
    # classics: старое без высокой оценки, включая фильмы без оценки — не исключены
    assert [i["kinopoiskId"] for i in mode_candidates(items, "classics")] == [4, 3]


def test_tagged_rows_appends_tags_only_when_present():
    from cinecompass.library import tagged_rows

    items = [{"kinopoiskId": 1, "title": "Т", "originalTitle": "O",
              "year": 2000, "type": "film", "userRating": 8}]
    row = tagged_rows(items, {1: ["tense", "urban"]})
    assert "Т (O) | 2000 | фильм | 8/10" in row and "теги: tense, urban" in row
    assert "теги" not in tagged_rows(items, {})


def test_duration_is_minutes_not_seasons_for_series():
    assert duration({"movieLength": "116"}) == "1 ч 56 мин"
    assert duration({"seriesLength": 47}) == "сер. 47 мин"
    assert duration({}) == ""


def test_stats_context_aggregates_and_coverage():
    from cinecompass.markdown import stats_context

    items = [
        {"kinopoiskId": 1, "title": "A", "originalTitle": "Orig", "year": 2001, "type": "film",
         "userRating": 10, "watchedDate": "2011-05-01", "directors": ["Нолан"], "genres": ["фантастика"]},
        {"kinopoiskId": 2, "title": "B", "originalTitle": "B", "year": 2001, "type": "film",
         "userRating": 4, "watchedDate": "2012-01-01", "directors": [], "genres": []},
        {"kinopoiskId": 3, "title": "C", "originalTitle": "O", "year": None, "type": "series",
         "userRating": None, "watchedDate": "", "directors": [], "genres": []},
    ]
    ctx = stats_context(items)
    assert "оценено: 2, без оценки: 1" in ctx
    assert "4 — 1, 10 — 1" in ctx                       # распределение по возрастанию
    assert "### Фильмы с оценкой 5 и ниже (1)" in ctx
    assert "B, 2001 (4)" in ctx
    assert "режиссёры заполнены у **1/3**" in ctx       # coverage, а не «у всех»
    assert "- Нолан — 1" not in ctx                     # меньше 3 оценённых — не в списке
    assert "2011 — 1" in ctx and "2012 — 1" in ctx      # активность по годам
    assert "A (Orig)" in ctx                            # «Русское» (Original)


def test_log_usage_appends_jsonl_row(tmp_path, monkeypatch):
    from cinecompass import config, llm
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.jsonl")
    usage = SimpleNamespace(
        prompt_token_count=57000,
        thoughts_token_count=5468,
        candidates_token_count=1230,
        cached_content_token_count=57322,
    )
    llm._log_usage(SimpleNamespace(usage_metadata=usage), op="predict", retry=False, started=0.0)
    row = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["op"] == "predict"
    assert row["prompt_tokens"] == 57000
    assert row["thoughts_tokens"] == 5468
    assert row["output_tokens"] == 1230
    assert row["retry"] is False
    assert row["ts"]
    assert row["duration_s"] >= 0


def test_find_item_by_title_matches_case_punctuation_and_original():
    items = [
        {"title": "Бойцовский клуб", "originalTitle": "Fight Club", "userRating": 10},
        {"title": "ВАЛЛ·И", "originalTitle": "WALL·E", "userRating": 9},
    ]
    # Поиск по точному названию
    assert find_item_by_title(items, "Бойцовский клуб")["userRating"] == 10
    # Поиск без учета регистра и пунктуации
    assert find_item_by_title(items, "бойцовский клуб!")["userRating"] == 10
    assert find_item_by_title(items, "валли")["userRating"] == 9
    # Поиск по оригинальному названию
    assert find_item_by_title(items, "Fight Club")["userRating"] == 10
    assert find_item_by_title(items, "wall-e")["userRating"] == 9
    # Несуществующий
    assert find_item_by_title(items, "Интерстеллар") is None


def test_load_export_csv_maps_columns(tmp_path):
    csv_file = tmp_path / "kinopoisk_export.csv"
    csv_file.write_text(
        "dateTime,url,isSeries,name,originalName,year,isWatched,userVote,tmdbId\n"
        "2026-11-07,https://www.kinopoisk.ru/series/9349321/,да,Штольня,The Cellar,2026,да,6,278178\n"
        "2026-11-04,https://www.kinopoisk.ru/film/14067013/,нет,Dustfall,,2026,да,,307176\n"
        "2026-11-01,https://www.kinopoisk.ru/film/1/,нет,Не смотрел,,2026,нет,5,\n",
        encoding="utf-8",
    )
    items = _load_export_csv(csv_file)
    assert len(items) == 2          # непросмотренное пропущено
    assert items[0]["kinopoiskId"] == 9349321 and items[0]["type"] == "series"
    assert items[0]["userRating"] == 6 and items[0]["tmdbId"] == "278178"
    assert items[0]["watchedDate"] == "2026-11-07"
    assert items[1]["userRating"] is None and items[1]["year"] == 2026
    assert clean_items(items)[0]["rewatchCount"] == 1
