"""Тесты загрузчика taxonomy.json (Этап 1)."""
import json

import pytest

from cinecompass import taxonomy


def _tag(tag_id="heist", category="genre", **overrides):
    tag = {
        "id": tag_id,
        "category": category,
        "label": "Heist",
        "definition": "The plot centres on a robbery.",
    }
    tag.update(overrides)
    return tag


def _taxonomy(tmp_path, data):
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_ok(tmp_path):
    path = _taxonomy(tmp_path, {
        "taxonomy_version": "1.0",
        "tags": [_tag(), _tag("cozy", "mood")],
    })
    result = taxonomy.load(path)
    assert result["version"] == "1.0"
    assert [t["id"] for t in result["tags"]] == ["heist", "cozy"]


def test_missing_file(tmp_path):
    with pytest.raises(ValueError, match="не найден"):
        taxonomy.load(tmp_path / "no_such.json")


def test_invalid_json(tmp_path):
    path = tmp_path / "taxonomy.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        taxonomy.load(path)


def test_duplicate_ids(tmp_path):
    path = _taxonomy(tmp_path, {
        "taxonomy_version": "1.0",
        "tags": [_tag(), _tag()],
    })
    with pytest.raises(ValueError, match="Дубликат"):
        taxonomy.load(path)


def test_unknown_category(tmp_path):
    path = _taxonomy(tmp_path, {
        "taxonomy_version": "1.0",
        "tags": [_tag(category="flavor")],
    })
    with pytest.raises(ValueError, match="категория"):
        taxonomy.load(path)


def test_missing_and_unexpected_fields(tmp_path):
    no_label = {"id": "heist", "category": "genre", "definition": "x"}
    extra = _tag("cozy", "mood", examples=["a"])
    path = _taxonomy(tmp_path, {"taxonomy_version": "1.0", "tags": [no_label, extra]})
    with pytest.raises(ValueError, match="обязательных полей"):
        taxonomy.load(path)


def test_real_taxonomy_loads():
    result = taxonomy.load()
    counts = {}
    for t in result["tags"]:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    assert result["version"] == "1.0"
    assert len(result["tags"]) == 52
    assert set(counts) == set(taxonomy.VALID_CATEGORIES)
