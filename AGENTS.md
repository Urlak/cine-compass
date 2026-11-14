# AGENTS.md

cine-compass: личная кинобиблиотека из экспорта Кинопоиска. CLI (`main.py`): `import`/`clean`,
`enrich` (основной источник — TMDB по `tmdbId` из экспорта, без суточной квоты; kinopoisk.dev —
фолбэк для записей без tmdbId; кэш `data/caches/enrich_cache.json`),
`build` (маркдаун-каталог), `semantic`/`taste` (семантические теги и Taste Profile, без LLM
в расчётах профиля), `stats`/`profile`/`recommend`/`predict` (Gemini через `google-genai`,
модель — `LLM_MODEL` из `.env`, сейчас `gemini-3.8-flash`).

Контексты LLM: `stats`/`profile`/`recommend` получают компактные программные сводки
(`stats_context`, `taste_profile.md`, Python-кандидаты по режиму), НЕ полную библиотеку;
`predict` и `benchmark` — портрет зрителя (`profile.md`-подобный вкус: Approval/Lift) +
до 30 ближайших по вкусу записей (режиссёр/теги/жанры; метаданные фильма-запроса —
через TMDB `/search/multi`). Словарь тегов `taxonomy.json` v1.1 заморожен;
промпт классификации (PROMPT_VERSION r4) заморожен — правки текста требуют согласования.

## Commands

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

pytest                                             # 36 тестов (таксономия, семантика, профиль, библиотека, промпты), без сети
.\.venv\Scripts\python.exe main.py [--user NAME] import <путь к library_export.json>
.\.venv\Scripts\python.exe main.py [--user NAME] enrich [--limit N]   # возобновляемо, кэш в data/caches/enrich_cache.json
.\.venv\Scripts\python.exe main.py [--user NAME] build
.\.venv\Scripts\python.exe main.py [--user NAME] semantic [--limit N] # пакетная классификация тегами → data/caches/semantic_cache.json
.\.venv\Scripts\python.exe main.py [--user NAME] taste                # Taste Profile → data/users/<NAME>/taste_profile.json/.md
.\.venv\Scripts\python.exe main.py [--user NAME] stats | profile | predict <название>
.\.venv\Scripts\python.exe main.py [--user NAME] recommend --mode old|new|classics [--count N]
.\.venv\Scripts\python.exe main.py [--user NAME] benchmark [--per-rating N]   # ретроспективный тест predict
```

`--user NAME` (по умолчанию `me`) выбирает зрителя: библиотека и все выводы —
в `data/users/<NAME>/`, кэши (`data/caches/`) общие для всех. Опция ставится
сразу после `main.py`, перед командой.

После каждого `enrich` (новые описания/жанры меняют fingerprint) запускается `semantic`
(бюджет `SEMANTIC_ENRICHMENT_MAX_TOKENS` в `.env`), затем `taste` пересчитывает профиль.

В git коммитятся только кэши (`data/caches/`) — факты о фильмах, без личных
данных; библиотеки пользователей (`data/users/*/`) и выводы не коммитятся
(история просмотров и оценки остаются локальными, бэкап — вручную).
Ключи — в `.env` (см. `.env.template`), в git не попадают.

## Code Change Principles

**Scope**
- Make the smallest change that solves the task. If the diff exceeds roughly the size of the logic you're modifying, stop and justify it.
- Prefer editing existing code over adding new code, functions, or files. Create a new file only when it is clearly the right home for the code.
- Do not touch code unrelated to the task: no opportunistic cleanup, reformatting, renaming, or "while I'm here" changes.
- Do not rewrite a function to add a line. Make targeted edits.
- Do not add new dependencies for a small task.
- Delete unused or replaced code immediately. Since there is no backward compatibility, do not leave deprecated functions, legacy files, or commented-out code.

**Match the codebase**
- Match the error-handling, validation, logging, comment density, and abstraction level of the surrounding code. If neighbors don't null-check, don't add null checks.
- Before writing a helper, search the codebase and stdlib for one that already exists.
- Validate at boundaries only: public APIs, user input, external data, deserialization. Internal callers are trusted; do not re-validate inside private methods.

**Simplicity**
- Inline one-off helpers. Do not introduce a function, class, interface, or abstraction with fewer than two concrete call sites.
- No speculative generality: no unused parameters, config flags, options, compatibility layers, or interfaces with one implementer.
- Handle errors that can actually occur, not hypothetical ones. Do not add try/catch that only logs, re-throws, or swallows.
- Prefer modifying existing logic over wrapping it.

**Tests**
- Test behavior, not implementation. Do not duplicate existing coverage. One test per behavior is usually enough.
- Avoid heavy mocking for internal logic. Test against real internal dependencies where possible to keep the architecture simple.

**Workflow**
- Before editing, state in one or two sentences which files and functions you will change and roughly how many lines. If that is more than a handful of files, confirm with me first.
- After editing, review your own diff: is every changed line necessary for the stated task? Remove anything that isn't. Do not re-emit unchanged code.
