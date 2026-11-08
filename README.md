# cine-compass

Личная кинобиблиотека из экспорта Кинопоиска: чистка и дедупликация списка,
каталог в Markdown, статистика и профайл зрителя через LLM (Gemini),
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

```powershell
python main.py import "C:\Users\roman\Downloads\Temp\library_export_1794175310215.json"
python main.py enrich            # дотянуть жанр/режиссёра/рейтинг (возобновляемо, кэш в data/enrich_cache.json)
python main.py build             # маркдаун-каталог data/catalog.md
python main.py stats             # глубокая статистика → data/stats.md
python main.py profile           # портрет зрителя → data/profile.md
python main.py predict Сталкер   # прогноз личной оценки + почему (без спойлеров) → data/prediction.md

python main.py recommend --mode old      # любимое из старого
python main.py recommend --mode new      # свежее и новенькое
python main.py recommend --mode classics # хорошая классика
python main.py recommend --mode old --count 10
```

Обогащение на демо-тарифе: 1155 записей ≈ 6 запусков по 200 запросов. Прогресс
сохраняется после каждой записи, запуск `python main.py enrich` можно повторять день за днём.

## Структура

```
main.py                 CLI
cinecompass/
  config.py             пути, .env, лимиты
  library.py            загрузка/чистка/дедуп/компактное представление
  enrich.py             обогащение через api.poiskkino.dev (кинопоиск-прокси kinopoisk.dev) + кэш
  markdown.py           каталог и локальная статистика
  llm.py                Gemini (google.genai)
  prompts.py            промпты
data/                   библиотека, кэш, все outputs
tests/                  базовые тесты чистки
```

`data/` в git не попадает.

## Заметки

- **Приватность**: команды `stats`/`profile`/`recommend` отправляют полную историю
  просмотров и оценок в Google Gemini (prompt), ответ не содержит ID — только названия и имена.
- **Дедупликация**: при повторных просмотрах по `kinopoiskId` остаётся одна запись со свежей
  датой; при равных датах сохраняется первая встреченная оценка.
- **Семантика полей API**: `seriesLength` у kinopoisk.dev — средняя длительность серии
  (в минутах), а не число сезонов; в каталоге показывается как «сер. N мин».
- Названия с `|`, `[`, `]` экранируются, чтобы не ломать таблицы и ссылки каталога.
