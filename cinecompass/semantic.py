"""Пилот семантической классификации фильмов тегами taxonomy.json (Этап 2).

Модель получает только factual metadata одного фильма и словарь тегов; отвечает
строгим JSON {kinopoiskId, status, tags}. Личные поля пользователя в промпт
не передаются. Результаты пишутся в data/pilot/ как данные для ручной проверки.
"""
import hashlib
import json
import statistics
from datetime import datetime

from cinecompass import config, library, llm, taxonomy

PROMPT_VERSION = "r4"

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


_RULES = """- Premise counts as evidence: reasonable inferences directly supported by the
  described setup are fine; a characteristic does not have to appear verbatim.
- Official genres are valid evidence for characterizing the film, but never
  duplicate them with semantic tags.
- Status is independent of tag count: "complete" does not require many tags or every
  category being populated, only enough information for a reliable, useful
  classification.
- External knowledge is allowed and encouraged when the record clearly identifies a
  work you know (title, year, director, originalTitle anchor it): you may use what
  you know about the film itself — its structure, style, tone and themes. Never
  contradict the record; for works you cannot confidently identify, judge by the
  description alone.
- A multi-sentence plot description combined with official genre metadata should
  normally qualify as "complete". Use "partial" only when the provided information
  is genuinely too limited to support a useful characterization, not merely because
  some categories cannot be populated.
- Virtually nothing beyond title, year and type: "insufficient_data" with an empty
  tags array.
- type "series" alone does not prove "episodic": assign it only if an episodic
  narrative structure is supported by the record itself.
- Use ONLY tag ids that exist in the dictionary. Never invent tags.
- Target density: for a feature film (type "film") with status "complete", aim for
  4–7 tags spanning different facets of the film; do not pad with weak guesses,
  and stay below that for series, "partial" and "insufficient_data" records.
- Official genres are context only: do not assign a tag whose meaning is already fully
  covered by one of them; assign tags that add information beyond them.
- Do not aim for a fixed number of tags; return fewer only when evidence is genuinely
  thin, never guess."""


def _dict_block(tags: list[dict]) -> str:
    return "\n".join(f"  - {t['id']}: {t['definition']}" for t in tags)


def _statuses() -> str:
    return ", ".join(f'"{s}" ({meaning})' for s, meaning in STATUS_MEANING.items())


def classification_prompt(payload: dict, tax: dict) -> str:
    return f"""You are a film classification system. Classify ONE film using English semantic tags
from the dictionary below.

Film record (JSON):
{json.dumps(payload, ensure_ascii=False)}

Tag dictionary (taxonomy_version {tax['version']}), format "id: definition":
{_dict_block(tax['tags'])}

Rules:
{_RULES}
- Choose status: {_statuses()}.
- Reply with ONLY a single JSON object, no markdown fences:
  {{"kinopoiskId": {payload['kinopoiskId']}, "status": "…", "tags": ["tag_id", …]}}"""


def batch_classification_prompt(payloads: list[dict], tax: dict) -> str:
    return f"""You are a film classification system. Classify EACH film below using English semantic
tags from the dictionary below. Apply the same rules to every film independently.

Films (JSON array):
{json.dumps(payloads, ensure_ascii=False)}

Tag dictionary (taxonomy_version {tax['version']}), format "id: definition":
{_dict_block(tax['tags'])}

Rules:
{_RULES}
- Choose status: {_statuses()} — separately for each film.
- Reply with ONLY a single JSON array, no markdown fences, one object per film, in
  this exact shape:
  [{{"kinopoiskId": …, "status": "…", "tags": ["tag_id", …]}}, …]
  Every input film must have exactly one result, with the same kinopoiskId."""


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


def classify_film(payload: dict, tax: dict, valid_ids: set[str], op: str = "pilot") -> dict:
    """Один вызов LLM с одним исправляющим ретраем при провале валидации."""
    prompt = classification_prompt(payload, tax)
    text = llm.generate(prompt, op=op)
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
        text = llm.generate(retry_prompt, op=op)
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


def parse_batch(text: str, expected_ids: list[int], valid_tag_ids: set[str]) -> dict[int, dict]:
    """Валидирует JSON-массив ответа партии; возвращает {kinopoiskId: data}."""
    raw = text.strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("ответ не содержит JSON-массив")
    try:
        entries = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"ответ не распарсился как JSON: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError("ответ должен быть JSON-массивом")
    by_id: dict[int, dict] = {}
    expected_fields = {"kinopoiskId", "status", "tags"}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("каждый элемент массива должен быть объектом")
        missing = expected_fields - set(entry)
        if missing:
            raise ValueError(f"у элемента отсутствуют ключи: {sorted(missing)}")
        unexpected = set(entry) - expected_fields
        if unexpected:
            raise ValueError(f"у элемента лишние ключи: {sorted(unexpected)}")
        kid = entry["kinopoiskId"]
        if kid not in expected_ids:
            raise ValueError(f"посторонний kinopoiskId: {kid!r}")
        if kid in by_id:
            raise ValueError(f"дубликат kinopoiskId: {kid}")
        if entry["status"] not in ALLOWED_STATUS:
            raise ValueError(f"у {kid} неизвестный статус: {entry['status']!r}")
        if not isinstance(entry["tags"], list) or not all(isinstance(t, str) for t in entry["tags"]):
            raise ValueError(f"у {kid} tags должен быть списком строк")
        unknown = [t for t in entry["tags"] if t not in valid_tag_ids]
        if unknown:
            raise ValueError(f"у {kid} неизвестные теги: {unknown}")
        by_id[kid] = entry
    missing = [i for i in expected_ids if i not in by_id]
    if missing:
        raise ValueError(f"в ответе нет фильмов: {missing}")
    return by_id


def fingerprint(payload: dict, taxonomy_version: str) -> str:
    """Хэш всех входных данных классификации: запись + версии + модель."""
    basis = {**payload, "taxonomy_version": taxonomy_version,
             "prompt_version": PROMPT_VERSION, "model": config.LLM_MODEL}
    digest = hashlib.sha256(
        json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:16]


def _cache_record(kid: int, payload: dict, tax_version: str, status: str, tags: list) -> dict:
    return {
        "kinopoiskId": kid,
        "tags": tags,
        "status": status,
        "taxonomy_version": tax_version,
        "prompt_version": PROMPT_VERSION,
        "model": config.LLM_MODEL,
        "fingerprint": fingerprint(payload, tax_version),
    }


def load_cache() -> dict[int, dict]:
    if not config.SEMANTIC_CACHE_FILE.is_file():
        return {}
    try:
        data = json.loads(config.SEMANTIC_CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"semantic_cache.json — некорректный JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("semantic_cache.json — верхний уровень должен быть объектом")
    return {int(k): v for k, v in data.items()}


def save_cache(cache: dict[int, dict]) -> None:
    config.SEMANTIC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.SEMANTIC_CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({str(k): v for k, v in cache.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    tmp.replace(config.SEMANTIC_CACHE_FILE)


def _is_bare_record(payload: dict) -> bool:
    """Только название/год/тип — классифицируется без LLM, по правилу r3."""
    return not payload["description"] and not payload["officialGenres"] and not payload["countries"]


def _spent_tokens() -> int:
    """Суммарный расход op=semantic_enrich: prompt+thoughts+output (cached уже внутри prompt)."""
    if not config.USAGE_FILE.is_file():
        return 0
    total = 0
    with open(config.USAGE_FILE, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("op") == "semantic_enrich":
                total += (row.get("prompt_tokens", 0) + row.get("thoughts_tokens", 0)
                          + row.get("output_tokens", 0))
    return total


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


def run_batch_enrich(limit: int | None = None) -> dict:
    """Пакетная классификация библиотеки в data/caches/semantic_cache.json (Этап 3).

    Голые записи (только название/год/тип) классифицируются Python-ом без LLM.
    Останов по лимиту токенов проверяется после каждой партии.
    """
    items = library.load_library()
    tax = taxonomy.load()
    valid_ids = {t["id"] for t in tax["tags"]}
    cache = load_cache()
    todo = []
    for item in items:
        payload = film_payload(item)
        if cache.get(item["kinopoiskId"], {}).get("fingerprint") == fingerprint(payload, tax["version"]):
            continue
        todo.append((item, payload))
    bare = [(i, p) for i, p in todo if _is_bare_record(p)]
    llm_todo = [(i, p) for i, p in todo if not _is_bare_record(p)]
    if limit is not None:
        llm_todo = llm_todo[:limit]
    print(f"Semantic enrichment: свежих {len(todo)} (голых {len(bare)}, через LLM {len(llm_todo)}), "
          f"в кэше актуальных {len(cache)}; партия {config.SEMANTIC_ENRICHMENT_BATCH_SIZE}, "
          f"лимит {config.SEMANTIC_ENRICHMENT_MAX_TOKENS or 'не задан'}...", flush=True)

    auto = 0
    for item, payload in bare:
        cache[item["kinopoiskId"]] = _cache_record(
            item["kinopoiskId"], payload, tax["version"], "insufficient_data", [])
        auto += 1
    if auto:
        save_cache(cache)
        print(f"Голые записи: {auto} шт. → insufficient_data без LLM.", flush=True)

    stats = {"llm_processed": 0, "invalid_after_retry": 0, "batches": 0, "stopped_by_limit": False}
    batch_size = config.SEMANTIC_ENRICHMENT_BATCH_SIZE
    total_batches = (len(llm_todo) + batch_size - 1) // batch_size
    for num, start in enumerate(range(0, len(llm_todo), batch_size), 1):
        spent = _spent_tokens()
        if config.SEMANTIC_ENRICHMENT_MAX_TOKENS and spent >= config.SEMANTIC_ENRICHMENT_MAX_TOKENS:
            stats["stopped_by_limit"] = True
            print(f"Лимит {config.SEMANTIC_ENRICHMENT_MAX_TOKENS} токенов достигнут "
                  f"({spent}); следующая партия не запускается.", flush=True)
            break
        chunk = llm_todo[start:start + batch_size]
        payloads = [p for _, p in chunk]
        ids = [p["kinopoiskId"] for p in payloads]
        print(f"[{num}/{total_batches}] Партия: {len(chunk)} фильмов "
              f"(id {min(ids)}…{max(ids)}), потрачено накопленно {_spent_tokens()}...", flush=True)
        prompt = batch_classification_prompt(payloads, tax)
        text = llm.generate(prompt, op="semantic_enrich")
        try:
            by_id = parse_batch(text, ids, valid_ids)
        except ValueError as exc:
            print(f"Партия отклонена целиком ({exc}); пересылаю записи по одной.", flush=True)
            for item, payload in chunk:
                record = classify_film(payload, tax, valid_ids, op="semantic_enrich")
                if record["error"]:
                    stats["invalid_after_retry"] += 1
                    print(f"  ✗ «{payload['title']}»: {record['error']}", flush=True)
                    continue
                cache[payload["kinopoiskId"]] = _cache_record(
                    payload["kinopoiskId"], payload, tax["version"],
                    record["status"], record["tags"])
                stats["llm_processed"] += 1
            save_cache(cache)
            stats["batches"] += 1
            continue
        for item, payload in chunk:
            answer = by_id[payload["kinopoiskId"]]
            cache[payload["kinopoiskId"]] = _cache_record(
                payload["kinopoiskId"], payload, tax["version"], answer["status"], answer["tags"])
            stats["llm_processed"] += 1
        save_cache(cache)
        stats["batches"] += 1
        print(f"        -> классифицировано {len(chunk)}, версия кэша сохранена "
              f"({_spent_tokens()} токенов накопленно).", flush=True)

    spent_total = _spent_tokens()
    summary = {
        **stats,
        "auto_insufficient": auto,
        "skipped_actual": len(items) - len(todo),
        "cache_total": len(cache),
        "spent_total": spent_total,
        "limit": config.SEMANTIC_ENRICHMENT_MAX_TOKENS or None,
    }
    print(f"Готово: кэш {summary['cache_total']} записей; LLM {summary['llm_processed']}, "
          f"голых {summary['auto_insufficient']}, невалидных после ретрая {summary['invalid_after_retry']}; "
          f"расход op=semantic_enrich накопленно: {spent_total} токенов.", flush=True)
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
