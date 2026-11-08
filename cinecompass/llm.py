"""Работа с Gemini (google.genai): статистика, профайл, рекомендации."""
from pathlib import Path

from google import genai

from cinecompass import config


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY не задан (см. .env.template)")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def generate(prompt: str) -> str:
    """Синхронный вызов Gemini, возвращает markdown-текст."""
    client = _client()
    resp = client.models.generate_content(model=config.LLM_MODEL, contents=prompt)
    text = resp.text
    if not text or not text.strip():
        raise RuntimeError("Пустой ответ модели")
    return text.strip()


def write_markdown(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path
