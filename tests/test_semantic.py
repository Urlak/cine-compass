"""Тесты пилота классификации (Этап 2): payload, парсер, повторяемость-метрика."""
import pytest

from cinecompass.semantic import (batch_classification_prompt, classification_prompt,
                                  film_payload, fingerprint, _is_bare_record, jaccard,
                                  parse_batch, parse_classification)


def test_classification_prompt_requires_record_only_evidence():
    tax = {"version": "1.0", "tags": [
        {"id": "heist", "category": "genre", "label": "Heist", "definition": "x"},
    ]}
    payload = {"kinopoiskId": 1, "title": "x", "originalTitle": "", "year": 2000,
               "type": "series", "officialGenres": [], "countries": [], "description": None}
    prompt = classification_prompt(payload, tax)
    assert "External knowledge" in prompt
    assert "Never" in prompt and "contradict the record" in prompt
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


def test_fingerprint_sensitivity():
    base = {"kinopoiskId": 1, "title": "a", "originalTitle": "", "year": 2000, "type": "film",
            "officialGenres": ["драма"], "countries": [], "description": "x"}
    assert fingerprint(base, "1.0") == fingerprint(dict(base), "1.0")
    assert fingerprint(base, "1.0") != fingerprint({**base, "officialGenres": ["боевик"]}, "1.0")
    assert fingerprint(base, "1.0") != fingerprint(dict(base), "2.0")


def test_is_bare_record():
    base = {"description": None, "officialGenres": [], "countries": []}
    assert _is_bare_record(base)
    assert not _is_bare_record({**base, "description": "Есть."})
    assert not _is_bare_record({**base, "officialGenres": ["драма"]})
    assert not _is_bare_record({**base, "countries": ["США"]})


def test_parse_batch_ok():
    text = ('[{"kinopoiskId": 1, "status": "complete", "tags": ["heist"]},'
            ' {"kinopoiskId": 2, "status": "insufficient_data", "tags": []}]')
    data = parse_batch(text, [1, 2], {"heist"})
    assert data[1]["status"] == "complete"
    assert data[2]["tags"] == []


def test_parse_batch_rejects():
    ok1 = '{"kinopoiskId": 1, "status": "partial", "tags": []}'
    valid = {"heist"}
    with pytest.raises(ValueError, match="нет фильмов"):
        parse_batch(f"[{ok1}]", [1, 2], valid)
    dup = f"[{ok1}, {ok1}]"
    with pytest.raises(ValueError, match="дубликат"):
        parse_batch(dup, [1], valid)
    with pytest.raises(ValueError, match="посторонний"):
        parse_batch('[{"kinopoiskId": 9, "status": "partial", "tags": []}]', [1], valid)
    with pytest.raises(ValueError, match="неизвестный статус"):
        parse_batch('[{"kinopoiskId": 1, "status": "x", "tags": []}]', [1], valid)
    with pytest.raises(ValueError, match="лишние ключи"):
        parse_batch('[{"kinopoiskId": 1, "status": "partial", "tags": [], "note": "x"}]', [1], valid)


def test_batch_and_single_prompts_share_r4_rules():
    payload = {"kinopoiskId": 1, "title": "x", "originalTitle": "", "year": 2000, "type": "film",
               "officialGenres": [], "countries": [], "description": "Есть завязка."}
    tax = {"version": "1.0", "tags": [
        {"id": "heist", "category": "genre", "label": "Heist", "definition": "x"}]}
    single = classification_prompt(payload, tax)
    batch = batch_classification_prompt([payload], tax)
    assert "External knowledge" in single and "External knowledge" in batch
    assert "4–7 tags" in single and "4–7 tags" in batch  # ориентир плотности разметки
    assert "Premise counts as evidence" in single and "Premise counts as evidence" in batch
    assert "heist: x" in single and "heist: x" in batch
