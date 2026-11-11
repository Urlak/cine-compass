# cine-compass

Личная кинобиблиотека из экспорта Кинопоиска: чистка и дедупликация списка,
каталог в Markdown, семантические теги по контролируемому словарю, Taste Profile
вкусовых предпочтений, статистика и профайл зрителя через LLM (Gemini),
персональные подборки «что посмотреть сейчас» (любимое старое / свежее / хорошая классика)
и прогноз личной оценки любого фильма без спойлеров.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.template .env   # и заполнить ключи
```

Ключи: `GEMINI_API_KEY` (aistudio.google.com) и `KINOPOISK_API_KEY` (бот @kinopoiskdev_bot, демо — 200 запросов/сутки).
Модель задаётся `LLM_MODEL` (текущая — `gemini-3.8-flash`).

## Команды

`--user NAME` (по умолчанию `me`) выбирает, чья библиотека обрабатывается; кэши
обогащения и семантики общие для всех пользователей. Опция ставится сразу после
`main.py`, перед командой.

```powershell
python main.py import "C:\Users\roman\Downloads\Temp\library_export_1794175310215.json"
python main.py enrich            # дотянуть жанр/режиссёра/рейтинг (возобновляемо, кэш в data/caches/enrich_cache.json;
                                 # нет ключа или сети — работа продолжается на одном кэше)
python main.py build             # маркдаун-каталог data/users/me/catalog.md

# семантический слой (цикл после каждого enrich — fingerprint пересчитает изменившиеся записи)
python main.py semantic          # пакетная классификация тегами → data/caches/semantic_cache.json (бюджет SEMANTIC_ENRICHMENT_MAX_TOKENS)
python main.py taste             # Taste Profile из тегов и оценок → data/users/me/taste_profile.json/.md

# LLM-операции (получают компактные программные контексты, не всю библиотеку)
python main.py stats             # статистика просмотров → data/users/me/stats.md
python main.py profile           # портрет зрителя по Taste Profile → data/users/me/profile.md
python main.py predict Сталкер   # прогноз личной оценки + почему (без спойлеров) → data/users/me/prediction.md

python main.py recommend --mode old      # любимое из старого
python main.py recommend --mode new      # свежее и новенькое
python main.py recommend --mode classics # хорошая классика
python main.py recommend --mode old --count 10

python main.py benchmark         # ретроспективный benchmark predict (MAE, ±1, токены)
python main.py pilot --ids ...   # диагностический пилот классификации тегов
```

Пример для друга: положите его экспорт куда угодно и укажите другое имя пользователя —

```powershell
python main.py --user friend import "C:\Downloads\library_export_friend.json"
python main.py --user friend enrich    # пересекающиеся фильмы уже в кэше — запросов почти не будет
python main.py --user friend semantic
python main.py --user friend taste && python main.py --user friend profile
```

## Как это работает

1. **Factual слой** (kinopoisk.dev): жанры, режиссёры, страны, описания — `enrich`, кэш возобновляемый.
2. **Семантический слой** (Gemini): каждый фильм классифицируется английскими тегами из
   `taxonomy.json` (52 тега: жанровые подвиды, mood, atmosphere, themes, narrative, pacing,
   setting, style). Статусы: `complete`/`partial`/`insufficient_data`; bare-записи
   (только название/год/тип) помечаются без LLM. Fingerprint всех входов гарантирует,
   что повторный `semantic` обрабатывает только изменившиеся записи.
3. **Taste Profile**: частоты тегов по четырём срезам (библиотека / оценённые / 8–10 / 1–5),
   связь тегов с оценками через разницу долей — без LLM и весов. `taste_profile.md`
   самодостаточен и пригоден для передачи другой LLM.
4. **LLM-операции на компактных контекстах** (замеры 2026-11-11, ~47 % покрытия тегами):

| Операция | Контекст | Prompt-токены (было ~63 580) |
| --- | --- | --- |
| profile | `taste_profile.md` | 3 542 (−94 %) |
| recommend | Python-кандидаты по режиму + теги | 5 949 (−91 %) |
| stats | программная сводка (агрегаты + списки 10 и ≤5) | 4 001 (−94 %) |
| predict | полная библиотека (baseline; осознанно не сокращён) | 63 580 |

## Структура

```
main.py                 CLI
taxonomy.json           контролируемый словарь тегов (v1.0)
cinecompass/
  config.py             пути, .env, лимиты, выбор пользователя (set_user)
  library.py            загрузка/чистка/дедуп/компактное представление/кандидаты режимов
  enrich.py             обогащение через api.poiskkino.dev (кинопоиск-прокси kinopoisk.dev) + кэш
  taxonomy.py           загрузка и валидация словаря
  semantic.py           пакетная классификация тегами, fingerprint, кэш, бюджет токенов
  taste.py              расчёт Taste Profile (без LLM)
  markdown.py           каталог, сводка stats, формат Taste Profile
  benchmark.py          ретроспективный benchmark predict
  llm.py                Gemini (google.genai) + лог usage.jsonl
  prompts.py            промпты
data/
  caches/               общие кэши (зависят только от фильма, не от зрителя):
    enrich_cache.json     жанры/режиссёры/рейтинги — kinopoisk.dev
    semantic_cache.json   семантические теги — Gemini
  usage.jsonl           лог расхода LLM-токенов
  pilot/, benchmark/    диагностические отчёты
  users/<name>/         всё, что принадлежит конкретному зрителю:
    raw/                  исходные экспорты Кинопоиска
    library.json          чистая библиотека
    catalog.md            каталог
    taste_profile.json/.md, profile.md, stats.md, prediction.md
    recommendations/      подборки
tests/                  тесты таксономии, семантики, профиля, библиотеки, промптов
```

## Что попадает в git

Только `data/caches/`: в кэшах нет личных данных — это факты о фильмах (жанры,
режиссёры, рейтинги, теги), их можно переиспользовать многократно и для других
людей. Библиотеки (`data/users/*/`) и сгенерированные выводы в git не попадают —
там история просмотров и оценки; их бэкап делается вручную (облачная папка,
копия), а ключи живут в `.env` и в git не попадают.

## Заметки

- **Приватность**: полная история просмотров уходит в Gemini только в `predict`.
  `stats` отправляет программную сводку-агрегаты, `profile` — обезличенный Taste Profile,
  `recommend` — кандидатов текущего режима; ответы не содержат ID — только названия и имена.
- **Дедупликация**: при повторных просмотрах по `kinopoiskId` остаётся одна запись со свежей
  датой; при равных датах сохраняется первая встреченная оценка.
- **Семантика полей API**: `seriesLength` у kinopoisk.dev — средняя длительность серии
  (в минутах), а не число сезонов; в каталоге показывается как «сер. N мин».
- Названия с `|`, `[`, `]` экранируются, чтобы не ломать таблицы и ссылки каталога.
