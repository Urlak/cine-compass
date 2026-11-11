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


def test_recommend_prompt_embeds_profile_and_cautions():
    title, p = prompts.recommend_prompt("строки кандидатов", "## Taste Profile", "new", 5)
    assert title == "Свежее и новенькое"
    assert "## Taste Profile" in p and "строки кандидатов" in p
    assert "полноценные участники" in p
    assert "Не путай распространённость тега" in p
    assert "массово отсеивать" in p


def test_stats_prompt_embeds_context_and_cautions():
    p = prompts.stats_prompt("## Общие данные\n\n- Всего записей: **1155**.")
    assert "## Общие данные" in p
    assert "Не пересчитывай статистику самостоятельно" in p
    assert "не выдумывай закономерности" in p.lower()
    assert "Полнота метаданных" in p
    assert "Taste Profile" in p
