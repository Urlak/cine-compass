"""Работа с Gemini (google.genai): статистика, профайл, рекомендации."""
from pathlib import Path

from google import genai
from google.genai import types

from cinecompass import config


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY не задан (см. .env.template)")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def generate(prompt: str) -> str:
    """Синхронный вызов Gemini, возвращает markdown-текст."""
    client = _client()
    resp = client.models.generate_content(model=config.LLM_MODEL, contents=prompt)
    if resp.text and resp.text.strip():
        return resp.text.strip()
    # Пустой текст бывает, когда весь лимит вывода ушла на внутренние
    # размышления (thinking) — повторяем с отключённым thinking.
    resp = client.models.generate_content(
        model=config.LLM_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        ),
    )
    text = (resp.text or "").strip()
    if not text:
        reason = resp.candidates[0].finish_reason if resp.candidates else None
        raise RuntimeError(f"Пустой ответ модели (finish_reason={reason})")
    return text


def write_markdown(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path
