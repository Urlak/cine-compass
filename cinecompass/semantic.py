"""Пилот семантической классификации фильмов тегами taxonomy.json (Этап 2).

Модель получает только factual metadata одного фильма и словарь тегов; отвечает
строгим JSON {kinopoiskId, status, tags}. Личные поля пользователя в промпт
не передаются. Результаты пишутся в data/pilot/ как данные для ручной проверки.
"""
import json
import statistics
from datetime import datetime

from cinecompass import config, library, llm, taxonomy

STATUS_MEANING = {
    "complete": "the provided record contains enough information to classify the film",
    "partial": "some attributes can be determined, but the information is not enough for a full classification",
    "insufficient_data": "the information is not enough even for a reliable partial classification",
}
ALLOWED_STATUS = set(STATUS_MEANING)

# Стратифицированная выборка пилота: эпохи 1939–2021, страны США/СССР/Россия/
# Великобритания/Италия/Япония/Канада/Австралия, анимация, два фильма без
# описания и два сериала без обогащения.
PILOT_IDS = [
    456, 356, 349, 380, 325, 403, 326, 342, 301, 370, 298, 6034, 8062, 25108, 7653,
    42664, 3707, 1118138, 1227803,
]
# Повторная классификация тех же параметров для проверки воспроизводимости тегов.
REPEAT_IDS = [403, 342, 370, 326]


def film_payload(item: dict) -> dict:
    """Только factual metadata; личные поля не попадают в промпт."""
    description = (item.get("description") or "").strip() or None
    return {
        "kinopoiskId": item["kinopoiskId"],
        "title": item.get("title", ""),
        "originalTitle": item.get("originalTitle", ""),
        "year": item.get("year"),
        "type": item.get("type", ""),
        "officialGenres": item.get("genres") or [],
        "countries": item.get("countries") or [],
        "description": description,
    }


def _tags_block(tags: list[dict]) -> str:
    by_cat: dict[str, list[dict]] = {}
    for t in tags:
        by_cat.setdefault(t["category"], []).append(t)
    lines = []
    for cat in sorted(by_cat):
        lines.append(f"{cat}:")
        lines.extend(f"  {t['id']} — {t['definition']}" for t in by_cat[cat])
    return "\n".join(lines)


def classification_prompt(payload: dict, tax: dict) -> str:
    tags = "\n".join(f"  - {t['id']}: {t['definition']}" for t in tax["tags"])
    statuses = ", ".join(f'"{s}" ({meaning})' for s, meaning in STATUS_MEANING.items())
    return f"""You are a film classification system. Classify ONE film using English semantic tags
from the dictionary below.

Film record (JSON):
{json.dumps(payload, ensure_ascii=False)}

Tag dictionary (taxonomy_version {tax['version']}), format "id: definition":
{tags}

Rules:
- Base tags ONLY on evidence in the provided record (description, official genres,
  countries, type, year). Do NOT treat your own knowledge of the film as evidence,
  even when the title is familiar; do NOT reconstruct plot details from memory.
- You MAY use general word understanding to interpret what the record states
  (e.g. a described robbery plot supports "heist"), but any attribute that needs
  evidence beyond the record stays untagged.
- Evidence is abundant when the record has a substantial description plus official
  genres: status "complete" is normal there, and up to about 10 tags too.
- Sparse evidence (very short or missing description): status "partial"; assign only
  characteristics that the available information actually confirms.
- Virtually nothing beyond title, year and type: status "insufficient_data" with an
  empty tags array.
- type "series" alone does not prove "episodic": assign it only if an episodic
  narrative structure is supported by the record itself.
- Use ONLY tag ids that exist in the dictionary. Never invent tags. Anywhere from 0
  to about 10 tags is acceptable; return FEWER tags when evidence is thin, never guess.
- Official genres are context only: do not assign a tag whose meaning is already fully
  covered by one of them; assign tags that add information beyond them.
- Assign a tag only when the record clearly supports it; omit unconfirmed attributes.
- Do not aim for a fixed number of tags; anywhere from 0 to about 10 is acceptable.
- Choose status: {statuses}.
- Reply with ONLY a single JSON object, no markdown fences:
  {{"kinopoiskId": {payload['kinopoiskId']}, "status": "…", "tags": ["tag_id", …]}}"""


def parse_classification(text: str, expected_id: int, valid_tag_ids: set[str]) -> dict:
    """Достаёт и валидирует JSON-ответ; бросает ValueError с описанием ошибки."""
    raw = text.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("ответ не содержит JSON")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"ответ не распарсился как JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("ответ должен быть JSON-объектом")
    fields = set(data)
    expected_fields = {"kinopoiskId", "status", "tags"}
    missing = expected_fields - fields
    if missing:
        raise ValueError(f"отсутствуют ключи: {sorted(missing)}")
    unexpected = fields - expected_fields
    if unexpected:
        raise ValueError(f"лишние ключи: {sorted(unexpected)}")
    if data["kinopoiskId"] != expected_id:
        raise ValueError(f"kinopoiskId не совпадает ({data['kinopoiskId']!r} != {expected_id})")
    if data["status"] not in ALLOWED_STATUS:
        raise ValueError(f"неизвестный статус: {data['status']!r}")
    if not isinstance(data["tags"], list) or not all(isinstance(t, str) for t in data["tags"]):
        raise ValueError("tags должен быть списком строк")
    duplicates = {t for t in data["tags"] if data["tags"].count(t) > 1}
    if duplicates:
        raise ValueError(f"дубликаты тегов: {sorted(duplicates)}")
    unknown = [t for t in data["tags"] if t not in valid_tag_ids]
    if unknown:
        raise ValueError(f"неизвестные теги: {unknown}")
    return data


def _last_usage() -> dict:
    """Последняя строка usage.jsonl — токены/латентность фактического вызова."""
    if not config.USAGE_FILE.is_file():
        return {}
    lines = config.USAGE_FILE.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1]) if lines else {}


def classify_film(payload: dict, tax: dict, valid_ids: set[str]) -> dict:
    """Один вызов LLM с одним исправляющим ретраем при провале валидации."""
    prompt = classification_prompt(payload, tax)
    text = llm.generate(prompt, op="pilot")
    usage = _last_usage()
    retry = False
    try:
        data = parse_classification(text, payload["kinopoiskId"], valid_ids)
    except ValueError as exc:
        retry = True
        retry_prompt = (
            f"{prompt}\n\nYour previous reply failed schema validation: {exc}. "
            "Reply again with ONLY the JSON object."
        )
        text = llm.generate(retry_prompt, op="pilot")
        usage = _last_usage()
        try:
            data = parse_classification(text, payload["kinopoiskId"], valid_ids)
        except ValueError as exc2:
            return {
                "kinopoiskId": payload["kinopoiskId"],
                "title": payload["title"],
                "originalTitle": payload["originalTitle"],
                "year": payload["year"],
                "status": "",
                "tags": [],
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "duration_s": usage.get("duration_s"),
                "retry": True,
                "error": str(exc2),
            }
    return {
        "kinopoiskId": payload["kinopoiskId"],
        "title": payload["title"],
        "originalTitle": payload["originalTitle"],
        "year": payload["year"],
        "status": data["status"],
        "tags": data["tags"],
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "duration_s": usage.get("duration_s"),
        "retry": retry,
        "error": "",
    }


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return round(len(sa & sb) / len(sa | sb), 2)


def run(ids: list[int] | None = None, repeat_ids: list[int] | None = None) -> dict:
    """ids=None и repeat_ids=None — полный пилот; --ids запускает мини-пилот без повторов."""
    ids = ids or PILOT_IDS
    if repeat_ids is None:
        repeat_ids = REPEAT_IDS if ids == PILOT_IDS else []
    items = library.load_library()
    by_id = {i["kinopoiskId"]: i for i in items}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"Записей нет в library.json: {missing}")
    tax = taxonomy.load()
    valid_ids = {t["id"] for t in tax["tags"]}
    results = []
    total = len(ids) + len(repeat_ids)
    print(f"Пилот: {len(ids)} фильмов + {len(repeat_ids)} повторов, "
          f"taxonomy {tax['version']}...", flush=True)
    n = 0
    for kp_id in ids:
        n += 1
        payload = film_payload(by_id[kp_id])
        print(f"[{n}/{total}] Классификация: «{payload['title']}» ({payload['year']}, "
              f"id {kp_id}, type {payload['type']})...", flush=True)
        record = classify_film(payload, tax, valid_ids)
        results.append(record)
        print(f"        -> {record['status']}: {', '.join(record['tags']) or '—'} "
              f"(попытка {'с ретраем' if record['retry'] else 'одна'})", flush=True)
    repeats = []
    for kp_id in repeat_ids:
        n += 1
        payload = film_payload(by_id[kp_id])
        print(f"[{n}/{total}] Повторная классификация тем же промптом: "
              f"«{payload['title']}»...", flush=True)
        record = classify_film(payload, tax, valid_ids)
        results.append(record)
        first = next(r for r in results[:len(ids)] if r["kinopoiskId"] == kp_id)
        overlap = jaccard(first["tags"], record["tags"])
        record["jaccard_with_first"] = overlap
        repeats.append(record)
        print(f"        -> {record['status']}: {', '.join(record['tags']) or '—'} "
              f"| пересечение с первым прогоном: {overlap}", flush=True)
    summary = _summary(results, repeats, tax["version"])
    _write(results, summary)
    return summary


def _summary(results: list[dict], repeats: list[dict], version: str) -> dict:
    first_try = sum(1 for r in results if r["retry"] is False)
    with_retry = sum(1 for r in results if r["retry"] and not r["error"])
    statuses = {}
    for r in results:
        if not r["error"]:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    return {
        "taxonomy_version": version,
        "classified": len(results),
        "unique_films": len({r["kinopoiskId"] for r in results}),
        "repeats": len(repeats),
        "schema_first_try": first_try,
        "schema_with_retry": with_retry,
        "schema_failed": sum(1 for r in results if r["error"]),
        "statuses": statuses,
        "prompt_tokens": sum(r["prompt_tokens"] for r in results),
        "output_tokens": sum(r["output_tokens"] for r in results),
        "avg_duration_s": round(statistics.mean(
            r["duration_s"] for r in results if r["duration_s"] is not None), 1),
        "repeat_jaccard": [r["jaccard_with_first"] for r in repeats],
    }


def _write(results: list[dict], summary: dict) -> None:
    out_dir = config.DATA_DIR / "pilot"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"pilot_{stamp}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lines = [
        f"# Пилот классификации тегами taxonomy {summary['taxonomy_version']} ({stamp})",
        "",
        f"Целей: {summary['classified']} ({summary['unique_films']} фильмов + "
        f"{summary['repeats']} повторов).",
        f"Схема: с первого раза {summary['schema_first_try']}, со вторым {summary['schema_with_retry']}, "
        f"провал {summary['schema_failed']}.",
        f"Статусы: {summary['statuses']}.",
        f"Токены: prompt {summary['prompt_tokens']}, output {summary['output_tokens']}, "
        f"средняя латентность {summary['avg_duration_s']} с.",
        "Повторяемость (Jaccard повторов): " + str(summary['repeat_jaccard']),
        "",
        "| id | Название | Год | Статус | Теги |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        status_txt = f"ошибка: {r['error']}" if r["error"] else r["status"]
        lines.append(
            f"| {r['kinopoiskId']} | {r['title']} ({r['originalTitle']}) | {r['year']} "
            f"| {status_txt} | {', '.join(r['tags']) or '—'} |"
        )
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Отчёт: {out_dir / 'latest.md'}, данные: {path}", flush=True)
