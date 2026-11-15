from cinecompass.markdown import _HEADER, item_row


def _item(**extra):
    item = {
        "title": "Т", "originalTitle": "Т", "type": "film", "year": 2000,
        "userRating": 8, "genres": ["драма"], "directors": ["А"],
        "kpRating": 7.5, "watchedDate": "2020-01-01",
    }
    item.update(extra)
    return item


def test_row_without_tmdb_shows_dashes():
    row = item_row(_item())
    cells = row.split(" | ")
    assert cells[5] == "8" and cells[6] == "7.5" and cells[7] == "—" and cells[8] == "—"


def test_popularity_tier_from_tmdb_votes():
    # Лог-шкала: ~2 голоса → 1, ~10 → 2, ~1 000 → 6, ~10 000 → 8, ~100 000+ → 10
    assert item_row(_item(tmdbRating=7.2, tmdbVotes=12539)).split(" | ")[7:9] == ["7.2", "8"]
    assert item_row(_item(tmdbVotes=2)).split(" | ")[8] == "1"
    assert item_row(_item(tmdbVotes=1000)).split(" | ")[8] == "6"
    assert item_row(_item(tmdbVotes=150000)).split(" | ")[8] == "10"


def test_header_matches_row_columns():
    header_cols, sep_cols = _HEADER.splitlines()
    assert header_cols.count("|") == sep_cols.count("|") == item_row(_item()).count("|")
