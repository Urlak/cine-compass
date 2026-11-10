"""Тесты пилота классификации (Этап 2): payload, парсер, повторяемость-метрика."""
import pytest

from cinecompass.semantic import classification_prompt, film_payload, jaccard, parse_classification


def test_classification_prompt_requires_record_only_evidence():
    tax = {"version": "1.0", "tags": [
        {"id": "heist", "category": "genre", "label": "Heist", "definition": "x"},
    ]}
    payload = {"kinopoiskId": 1, "title": "x", "originalTitle": "", "year": 2000,
               "type": "series", "officialGenres": [], "countries": [], "description": None}
    prompt = classification_prompt(payload, tax)
    assert "external knowledge" in prompt
    assert "insufficient_data" in prompt  # правило для записи без описания/жанров
    assert "does not prove" in prompt     # type=series сам по себе не доказывает episodic
    assert "partial" in prompt            # правило для короткого описания


def _item(**overrides):
    item = {
        "kinopoiskId": 325,
        "title": "Крестный отец",
        "originalTitle": "The Godfather",
        "year": 1972,
        "type": "film",
        "genres": ["драма", "криминал"],
        "countries": ["США"],
        "description": "Да, сначала я хотел уйти в сторону. ",
        "userRating": 10,
        "watchedDate": "2008-09-09",
        "rewatchCount": 3,
        "kpRating": 8.7,
    }
    item.update(overrides)
    return item


def test_film_payload_excludes_personal_fields():
    payload = film_payload(_item())
    assert payload["kinopoiskId"] == 325
    expected_description = _item()["description"].strip()
    assert payload["description"] == expected_description  # strip у описания
    assert payload["officialGenres"] == ["драма", "криминал"]
    for forbidden in ("userRating", "watchedDate", "rewatchCount", "kpRating"):
        assert forbidden not in payload


def test_parse_classification_ok_and_fenced_json():
    valid = {"heist", "buddy"}
    text = '```json\n{"kinopoiskId": 325, "status": "complete", "tags": ["heist"]}\n```'
    data = parse_classification(text, expected_id=325, valid_tag_ids=valid)
    assert data == {"kinopoiskId": 325, "status": "complete", "tags": ["heist"]}


def test_parse_classification_rejects():
    valid = {"heist"}
    ok = '{"kinopoiskId": 325, "status": "complete", "tags": ["heist"]}'
    with pytest.raises(ValueError, match="kinopoiskId не совпадает"):
        parse_classification(ok, expected_id=999, valid_tag_ids=valid)
    with pytest.raises(ValueError, match="неизвестный статус"):
        parse_classification(
            ok.replace('"complete"', '"maybe"'), expected_id=325, valid_tag_ids=valid)
    with pytest.raises(ValueError, match="неизвестные теги"):
        parse_classification(
            ok.replace('"heist"', '"nonexistent"'), expected_id=325, valid_tag_ids=valid)
    with pytest.raises(ValueError, match="лишние ключи"):
        parse_classification(
            '{"kinopoiskId": 325, "status": "complete", "tags": ["heist"], "note": "x"}',
            expected_id=325, valid_tag_ids=valid)
    with pytest.raises(ValueError, match="отсутствуют ключи"):
        parse_classification('{"kinopoiskId": 325, "status": "complete"}',
                             expected_id=325, valid_tag_ids=valid)
    with pytest.raises(ValueError, match="JSON"):
        parse_classification("ничегоToJson", expected_id=325, valid_tag_ids=valid)


def test_jaccard_basic():
    assert jaccard(["a", "b", "c"], ["a", "b", "d"]) == 0.5
    assert jaccard(["a"], ["a"]) == 1.0
    assert jaccard([], []) == 1.0
