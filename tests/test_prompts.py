"""Тесты промпта profile (Этап 5): 6-секционная схема, негативные ограничения."""
from cinecompass import prompts


def test_profile_prompt_embeds_taste_profile_and_schema():
    md = "# Taste Profile\n\n## Метаданные\n\n- tagged_count: **853**."
    p = prompts.profile_prompt(md)
    assert md in p
    for section in ("## 0. Snapshot", "## 1. Core Drivers", "## 2. Conditional Rules (IF / THEN)",
                    "## 3. Hard Red Flags", "## 4. Rating Calibration", "## 5. Exploration Vectors"):
        assert section in p
    assert "1200–1600 токенов" in p
    assert "фильма-якоря" in p


def test_profile_prompt_negative_constraints():
    p = prompts.profile_prompt("x")
    assert "никаких вводных и заключительных абзацев" in p
    assert "«вероятно»" in p and "указывает на то, что" in p
    assert "не рассуждай о размере" in p
    assert "с годом и оценкой [N]" in p
    assert "Не пересчитывай статистику" in p
    assert "смотри на Lift, а не на n" in p


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
