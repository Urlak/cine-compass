import json
from types import SimpleNamespace

from cinecompass import config, enrich, library


def test_kp_backfill_preserves_tmdb_and_applies_to_library(tmp_path, monkeypatch):
    lib_path = tmp_path / "library.json"
    cache_path = tmp_path / "enrich_cache.json"
    monkeypatch.setattr(config, "LIBRARY_FILE", lib_path)
    monkeypatch.setattr(config, "ENRICH_CACHE_FILE", cache_path)
    monkeypatch.setattr(config, "KINOPOISK_API_KEY", "test-kp-key")
    monkeypatch.setattr(config, "ENRICH_INTERVAL", 0.0)

    items = [
        {"kinopoiskId": 100, "title": "Фильм А", "tmdbId": "55", "type": "film",
         "genres": ["Драма"], "tmdbRating": 7.8, "tmdbVotes": 1200, "kpRating": None},
        {"kinopoiskId": 200, "title": "Фильм Б", "tmdbId": "66", "type": "film",
         "genres": ["Комедия"], "tmdbRating": 6.5, "tmdbVotes": 500, "kpRating": 7.1},
    ]
    library.save_library(items)
    cache_path.write_text(json.dumps({
        "100": {"genres": ["Драма"], "tmdbRating": 7.8, "tmdbVotes": 1200, "kpRating": None, "description": "TMDB desc"},
        "200": {"genres": ["Комедия"], "tmdbRating": 6.5, "tmdbVotes": 500, "kpRating": 7.1},
    }), encoding="utf-8")

    calls = []

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            calls.append(url)
            return SimpleNamespace(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {
                    "genres": [{"name": "драма"}, {"name": "триллер"}],
                    "countries": [{"name": "США"}],
                    "persons": [{"enProfession": "director", "name": "Режиссёр"}],
                    "rating": {"kp": 8.2, "imdb": 7.9},
                    "ageRating": 16,
                    "description": "KP desc",
                },
            )

    monkeypatch.setattr(enrich.requests, "Session", FakeSession)
    monkeypatch.setattr(enrich.tmdb, "detail", lambda _item: (_ for _ in ()).throw(AssertionError("TMDB не должен вызываться")))

    stats = enrich.enrich_library(kp=True)
    assert stats == {"fetched": 1, "failed": 0, "quota_exceeded": False}
    assert len(calls) == 1 and calls[0].endswith("/100")

    saved = library.load_library()
    by_id = {it["kinopoiskId"]: it for it in saved}
    assert by_id[100]["kpRating"] == 8.2
    assert by_id[100]["imdbRating"] == 7.9
    assert by_id[100]["tmdbRating"] == 7.8
    assert by_id[100]["tmdbVotes"] == 1200
    assert by_id[100]["genres"] == ["Драма", "драма", "триллер"]
    assert by_id[100]["description"] == "TMDB desc"


def test_apply_cache_fills_kp_and_tmdb_independently():
    items = [{"kinopoiskId": 1, "genres": ["драма"], "tmdbRating": None, "kpRating": None}]
    cache = {"1": {"genres": ["драма"], "tmdbRating": 7.4, "tmdbVotes": 300, "kpRating": 7.9, "imdbRating": 7.6}}
    enrich._apply_cache(items, cache)
    assert items[0]["tmdbRating"] == 7.4
    assert items[0]["tmdbVotes"] == 300
    assert items[0]["kpRating"] == 7.9
    assert items[0]["imdbRating"] == 7.6
