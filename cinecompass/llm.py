"""Работа с Gemini (google.genai): статистика, профайл, рекомендации."""
import json
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from cinecompass import config


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY не задан (см. .env.template)")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _log_usage(resp, op: str, retry: bool) -> None:
    """Записывает использование токенов запроса в data/usage.jsonl и в консоль."""
    u = resp.usage_metadata
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "op": op,
        "model": config.LLM_MODEL,
        "prompt_tokens": u.prompt_token_count or 0,
        "thoughts_tokens": u.thoughts_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "cached_tokens": u.cached_content_token_count or 0,
        "retry": retry,
    }
    config.USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    kind = "ретрай" if retry else "основной"
    print(f"Токены [{op}, {kind}]: prompt {row['prompt_tokens']}, "
          f"мысли {row['thoughts_tokens']}, output {row['output_tokens']}")


def generate(prompt: str, op: str = "llm") -> str:
    """Синхронный вызов Gemini, возвращает markdown-текст."""
    client = _client()
    resp = client.models.generate_content(model=config.LLM_MODEL, contents=prompt)
    _log_usage(resp, op, retry=False)
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
    _log_usage(resp, op, retry=True)
    text = (resp.text or "").strip()
    if not text:
        reason = resp.candidates[0].finish_reason if resp.candidates else None
        raise RuntimeError(f"Пустой ответ модели (finish_reason={reason})")
    return text


def write_markdown(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path
