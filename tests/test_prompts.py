"""Тесты промпта profile (Этап 5): интерпретация Taste Profile, обязательные оговорки."""
from cinecompass import prompts


def test_profile_prompt_embeds_taste_profile_and_cautions():
    md = "# Taste Profile\n\n## Покрытие данных\n\n- Всего записей: **1155**."
    p = prompts.profile_prompt(md)
    assert md in p
    assert "Не пересчитывай статистику самостоятельно" in p
    assert "частый тег не означает любовь" in p
    assert "Покрытие данных частичное" in p
    assert "Маленькие срезы" in p
    assert "Не придумывай психологические характеристики" in p
    assert "«Русское название» (Original Title)" in p
