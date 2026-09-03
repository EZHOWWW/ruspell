@AGENTS.md

# CLAUDE.md — карта репозитория и рецепты

Стиль кода — в [AGENTS.md](./AGENTS.md) (импортирован выше). Здесь: что где
лежит и как делать типовые задачи.

## Что это

`ruspell` — библиотека проверки орфографии и согласования русского текста.
Текст на входе, список замечаний на выходе. Ядро: `pymorphy3` +
`pymorphy3-dicts-ru`. Опциональный слой согласования (экстра `agreement`):
`slovnet` + `navec` + `razdel`, разбор на numpy.

## Карта

```
src/ruspell/
├── __init__.py     публичный API: SpellChecker, Issue, IssueCategory, IssueDict,
│                   vocabulary_words, load_vocabulary, default_weights_dir
├── checker.py      класс SpellChecker: check() и correct()
├── check.py        build_layers() — сборка слоёв; check_text() — обход текста по строкам
├── issues.py       ЧИСТАЯ логика: WORD_RE, find_dictionary_issues, near_initials,
│                   merge_issues, collapse_repeats, apply_issues, shift
├── vocabulary.py   ЧИСТАЯ логика словаря: vocabulary_words, load_vocabulary,
│                   in_vocabulary, drop_vocabulary_words
├── dictionary.py   словарный слой: get_morph_analyzer, edits1, rank_suggestions,
│                   frequency_ranker, build_layer
├── agreement.py    слой согласования: load_models, parse_sentence, inflect,
│                   find_disagreements, find_government_errors, build_layer
├── models.py       контракт: Issue (frozen dataclass), IssueDict, IssueCategory
├── weights.py      имена и адреса весов, default_weights_dir, missing_weights,
│                   download_weights, main() — CLI `ruspell-weights download`
└── __main__.py     то же CLI как `python -m ruspell download`

tests/              зеркалит модули: test_issues, test_vocabulary, test_dictionary,
                    test_agreement, test_check, test_checker, test_models, test_weights
examples/           vocabulary.json (вымышленный), quickstart.py, build_vocabulary.py
.github/workflows/  ci.yml: lint, тесты на 3.10–3.13, деградация без весов, сборка
```

Поток данных: `SpellChecker.check(text)` → `check_text` (построчно, спаны
сдвигаются в координаты текста) → на каждой строке все слои → `merge_issues`
(при пересечении выигрывает более ранний слой) → `collapse_repeats`.
`correct` — то же самое, но без свёртки и через `apply_issues`.

## Команды

```bash
uv sync --extra agreement          # окружение
uv run pytest -q                   # тесты (проверки согласования скипаются без весов)
uv run ruff check .                # линтер
uv run ruff format --check .       # форматтер
uv run ruspell-weights download    # веса, 58 МБ, один раз
uv build                           # сборка колеса и sdist
```

Веса для локальной работы: `ruspell-weights download` кладёт их в
`~/.cache/ruspell`. В репозиторий их не коммитить (`.gitignore` уже это
запрещает). В CI они не качаются.

---

# Рецепты

## Добавить доменные слова

Словарь **не хранится в библиотеке**. Ничего в `src/` для этого править не
нужно — лексика передаётся в конструктор:

```python
SpellChecker(vocabulary={"техрегламент", "теплоузел"})                # словами
SpellChecker(vocabulary=["ФТП — Фондтехпроект", "ПСД — документация"])# фразами
SpellChecker(vocabulary=load_vocabulary(Path("vocabulary.json")))     # из файла
```

1. Нашёл слово, которое подчёркивается зря → добавь его в словарь **проекта
   пользователя** (его JSON, его справочник в БД), а не в репозиторий ruspell.
2. Составные слова кладутся как есть: `"машино-мест"` разбирается на «машино» и
   «мест», и `in_vocabulary` признаёт слово по частям.
3. Аббревиатуру пиши вместе с расшифровкой одной строкой — из неё возьмутся все
   слова.
4. **ФИО в словарь не кладём никогда.** За фамилии отвечает `near_initials`:
   слово рядом с инициалами не подчёркивается.
5. Если PR добавляет слова в `src/` — это ошибка, отклоняй.

## Собрать словарь из корпуса пользователя

1. Приведи корпус к `.txt` (по файлу на документ) — своим способом, парсеры
   форматов в библиотеку не тащим.
2. `uv run python examples/build_vocabulary.py <каталог> vocabulary.json`
3. Скрипт оставит слова, встреченные минимум в трёх *разных* документах и
   неизвестные pymorphy3, и **отдельно перечислит кандидатов, похожих на ФИО**.
4. Пройдись по списку глазами и удали персональные данные. Автоматически это не
   фильтруется: pymorphy3 метит именами половину терминов и пропускает половину
   фамилий. Без этого шага словарь отдавать нельзя.
5. Проверь результат: `SpellChecker(vocabulary=load_vocabulary(path))` на паре
   документов — ложных срабатываний должно стать заметно меньше.

## Встроить библиотеку в чужой проект

1. `uv add "ruspell[agreement]"` (или без экстры, если согласование не нужно).
2. Один `SpellChecker` на процесс, собранный на старте: сборка ~2 с, проверка
   ~10 мс. Кэшируй фабрику (`@lru_cache(maxsize=1)`), не создавай экземпляр в
   обработчике запроса.
3. Веса: `ruspell-weights download` на этапе сборки образа (не при старте
   контейнера — прод может быть без сети) и `RUSPELL_WEIGHTS_DIR` в окружении.
4. Наружу отдавай `issue.as_dict()`, а не сам `Issue`.
5. Слои покажи в health-check: `checker.layers`. Если в проде там только
   `('dictionary',)` — веса не доехали.
6. Ничего из FastAPI/Django в ruspell не добавляй: обёртка живёт в проекте
   пользователя. Пример обёртки — в README, раздел «Встраивание».

## Добавить новое правило согласования

Планка высокая: правило добавляется, только если оно **не роняет точность**.
Расширенный набор правил уже пробовали — он ухудшал результат, потому что
синтаксический разбор делового текста часто ошибается.

1. Напиши генератор в `agreement.py` рядом с `find_disagreements` и
   `find_government_errors`. Сигнатура та же: `(words: list[Word], analyzer:
   MorphAnalyzer) -> Iterator[Issue]`. Никакого IO, никаких моделей внутри.
2. Опирайся на `word.relation` (дуга синтаксического дерева) и `word.feats`
   (признаки UD). Вершина — `words[word.head]`, но сначала проверь
   `0 <= word.head < len(words)`.
3. Варианты замены получай через `inflect(...)` — она же сохранит регистр. Если
   вариантов нет, замечание не выпускай: подчёркивание без предложения бесполезно.
4. Заполни `message` человеческим объяснением: «что не так и с чем не
   согласовано».
5. Подключи генератор в `build_layer` в списке `issues`.
6. Тесты — в `tests/test_agreement.py`, на **разобранных вручную** `Word`:
   правило проверяется без весов. Обязательно добавь и отрицательный тест —
   правильная фраза не должна флагаться.
7. Прогони на реальном тексте до и после. Выросло число ложных срабатываний —
   правило не проходит, откатывай.
8. Новая категория замечания (кроме `SPELL`/`AGREEMENT`) — это правка
   `IssueCategory` в `models.py` и строки в README про то, что находится.

## Веса не скачиваются

Симптом: `layers == ('dictionary',)`, в логе `ruspell` — warning «Слой
согласования не поднялся».

1. Что именно отсутствует:
   ```bash
   uv run python -c "from pathlib import Path; from ruspell.weights import missing_weights, default_weights_dir; print(default_weights_dir(), missing_weights(default_weights_dir()))"
   ```
2. Пустой список, но слой не поднялся → не установлена экстра:
   `uv sync --extra agreement`.
3. Файлы есть, но слой падает на `tarfile.ReadError` → архив оборван. Удали
   файл и скачай заново: `ruspell-weights download` докачивает недостающее.
4. Сети нет или прокси режет: скачай файлы вручную по адресам из
   `ruspell.weights.DOWNLOADS`, положи в каталог с теми же именами и укажи
   `RUSPELL_WEIGHTS_DIR`. Имена файлов менять нельзя — по ним идёт проверка.
5. Каталог не тот: `checker.weights_dir` покажет, где искали. Переменная
   окружения перекрывает всё, аргумент конструктора — переменную.
6. Всё равно не работает — **это допустимое состояние**. Словарный слой
   работает, `check` и `correct` не падают. Не превращай отсутствие весов в
   исключение и не отключай деградацию: на неё есть тесты и отдельная задача в
   CI.

## Отладить ложное срабатывание

1. Воспроизведи на одной строке: `checker.check("...")`.
2. `SPELL` → проверь `analyzer.word_is_known(word)` и `edits1`. Скорее всего
   слово доменное: место ему в словаре пользователя.
3. `AGREEMENT` → посмотри разбор:
   ```python
   from razdel import tokenize
   from ruspell.agreement import load_models, parse_sentence
   morph, syntax = load_models(default_weights_dir())
   for word in parse_sentence("ваша строка", tokenize, morph, syntax):
       print(word.text, word.relation, word.head, word.feats)
   ```
   Если дуга разобрана неверно — это ошибка модели, а не правила; правило
   чинить нельзя, можно только сузить условие (и доказать замером).
4. Ранжирование не то → нет `ru_full.txt`, работает эвристика
   `rank_suggestions`.

## Выпустить версию

1. Подними `version` в `pyproject.toml`.
2. `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`.
3. `uv build` и проверь установку колеса в чистое окружение.
4. Тег `vX.Y.Z`, публикация на PyPI — отдельное решение владельца репозитория,
   сам не публикуй.
