"""Загрузка и валидация словаря английских семантических тегов."""
import json

from cinecompass import config

TAG_FIELDS = {"id", "category", "label", "definition"}
VALID_CATEGORIES = {
    "genre", "mood", "atmosphere", "setting", "themes", "pacing", "narrative", "style",
}


def load(path=None) -> dict:
    """Читает taxonomy.json и валидирует структуру; возвращает {"version", "tags"}."""
    path = path or config.TAXONOMY_FILE
    if not path.is_file():
        raise ValueError(f"Файл таксономии не найден: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"taxonomy.json — некорректный JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("taxonomy.json — верхний уровень должен быть объектом")
    version = data.get("taxonomy_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("taxonomy.json — отсутствует или пуст taxonomy_version")
    tags = data.get("tags")
    if not isinstance(tags, list) or not tags:
        raise ValueError("taxonomy.json — tags должен быть непустым списком")
    seen_ids: set[str] = set()
    for tag in tags:
        if not isinstance(tag, dict):
            raise ValueError("taxonomy.json — каждый тег должен быть объектом")
        fields = set(tag)
        missing = TAG_FIELDS - fields
        if missing:
            raise ValueError(f"Тег без обязательных полей: {sorted(missing)}")
        unexpected = fields - TAG_FIELDS
        if unexpected:
            raise ValueError(
                f"Тег '{tag.get('id')}' с неожиданными полями: {sorted(unexpected)}"
            )
        for field in sorted(TAG_FIELDS):
            if not isinstance(tag[field], str) or not tag[field].strip():
                raise ValueError(f"Поле '{field}' тега должно быть непустой строкой")
        if tag["category"] not in VALID_CATEGORIES:
            raise ValueError(f"Тег '{tag['id']}' — неизвестная категория: {tag['category']}")
        if tag["id"] in seen_ids:
            raise ValueError(f"Дубликат id тега: {tag['id']}")
        seen_ids.add(tag["id"])
    return {"version": version, "tags": tags}
