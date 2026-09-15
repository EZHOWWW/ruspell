"""Словарный слой: pymorphy3, доменная лексика и частотное ранжирование.

Слой находит слова, которых нет в языке, и предлагает замену. Незнакомое слово
считается опечаткой, если на расстоянии одной правки от него есть словарное
слово; варианты упорядочиваются по частоте употребления, потому что
``SpellChecker.correct`` применяет именно первый вариант.

Доменная лексика сверяется до перебора правок: слова пользователя не ошибки,
а обычные слова его текстов. В варианты замены она не идёт. Словарь обычно
содержит одну форму термина («энергоаудит»), и склонённая форма в одной правке
от неё («энергоаудита») подчёркивалась бы как опечатка, а ``correct`` писал бы
«о проведении энергоаудит».

Частотный словарь — внешний файл; без него слой работает на эвристике по форме
слова, теряя в ранжировании, но не в способности находить ошибки.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from pymorphy3 import MorphAnalyzer

from ruspell.issues import Detector, find_dictionary_issues
from ruspell.models import Issue

logger = logging.getLogger("ruspell")

MIN_FREQUENCY_ENTRIES = 1000
"""Ниже этого порога файл — не частотный словарь.

Оборванная закачка непуста и прекрасно читается, поэтому `exists()` её не
отличает: разбор даёт горстку строк, и ранжирование молча становится
алфавитным — хуже документированного отката на эвристику и, в отличие от него,
без единого следа. Настоящий словарь — полтора миллиона строк, так что порог
различает их с огромным запасом.
"""

RUSSIAN_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
"""Алфавит для порождения вариантов замены.

Кириллического аналога ``string.ascii_lowercase`` в стандартной библиотеке нет,
поэтому буквы перечислены явно. «ё» здесь обязательна: правки «ещо» → «ещё» без
неё не существует.
"""

Ranker = Callable[[str, set[str]], list[str]]
"""Способ упорядочить варианты замены для слова."""


@lru_cache(maxsize=1)
def get_morph_analyzer() -> MorphAnalyzer:
    """Возвращает кэшированный морфологический анализатор pymorphy3.

    Загрузка словаря дорога (около секунды и 40 МБ), поэтому анализатор
    создаётся один раз на процесс.
    """
    return MorphAnalyzer()


def edits1(word: str) -> set[str]:
    """Возвращает все слова на расстоянии редактирования 1 от *word*."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [left + right[1:] for left, right in splits if right]
    transposes = [
        left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1
    ]
    replaces = [left + c + right[1:] for left, right in splits if right for c in RUSSIAN_ALPHABET]
    inserts = [left + c + right for left, right in splits for c in RUSSIAN_ALPHABET]
    return set(deletes + transposes + replaces + inserts)


def rank_suggestions(word: str, candidates: set[str]) -> list[str]:
    """Ранжирует варианты по правдоподобию опечатки.

    Опечатки редко меняют длину слова, первую или последнюю букву, поэтому
    такие варианты идут выше. Это запасной вариант ранжирования — на случай,
    когда частотного словаря нет.
    """

    def sort_key(candidate: str) -> tuple[bool, bool, bool, str]:
        return (
            candidate[0] != word[0],
            candidate[-1] != word[-1],
            len(candidate) != len(word),
            candidate,
        )

    return sorted(candidates, key=sort_key)


@lru_cache(maxsize=2)
def frequency_ranker(path: Path) -> Ranker | None:
    """Возвращает частотное ранжирование вариантов, если словарь доступен.

    Словарь — текстовый файл «слово частота» на строку. Читается один раз на
    процесс: полтора миллиона строк и около 210 МБ в памяти.

    Редкие слова не отбрасываются, хотя порог «встречено трижды» сэкономил бы
    120 МБ. Словарь собран по субтитрам, и деловая лексика в нём редкая:
    «изложенного» встречено один раз, «коллизий» — два. С порогом они
    сравнивались с отсутствующими словами по алфавиту, и на внутреннем бенче
    писем «изооженного» исправлялось в «извоженного».

    Args:
        path: Путь к частотному словарю.

    Returns:
        Ранжирование или ``None``, если файла нет или он не похож на словарь —
        тогда вызывающий берёт ``rank_suggestions``.
    """
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Файл есть, но прочитать его нельзя: нет прав (образ собран под root, а
        # запущен под пользователем), каталог вместо файла, обрыв посреди
        # многобайтного символа. Словарь нужен только для ранжирования —
        # проверка не должна из-за него падать на сборке.
        logger.warning(
            "Частотный словарь %s не прочитан (%s); варианты ранжируются эвристикой по форме слова",
            path,
            exc,
        )
        return None
    frequencies: dict[str, int] = {}
    for line in content.splitlines():
        word, _, count = line.partition(" ")
        if word and count.isdigit():
            frequencies[word] = int(count)
    if len(frequencies) < MIN_FREQUENCY_ENTRIES:
        logger.warning(
            "Частотный словарь %s разобран в %d строк — похоже на оборванную закачку; "
            "варианты ранжируются эвристикой по форме слова",
            path,
            len(frequencies),
        )
        return None

    def rank(word: str, candidates: set[str]) -> list[str]:
        return sorted(candidates, key=lambda candidate: (-frequencies.get(candidate, 0), candidate))

    return rank


def build_layer(
    vocabulary: frozenset[str],
    analyzer: MorphAnalyzer,
    rank: Ranker,
) -> Detector:
    """Собирает словарный слой проверки.

    Args:
        vocabulary: Доменная лексика — слова, которые не считаются ошибкой.
        analyzer: Морфологический анализатор pymorphy3.
        rank: Как упорядочивать варианты замены.

    Returns:
        Слой проверки.
    """

    def is_known(word: str) -> bool:
        return word in vocabulary or analyzer.word_is_known(word)

    def suggest(word: str) -> list[str]:
        candidates = {candidate for candidate in edits1(word) if analyzer.word_is_known(candidate)}
        return rank(word, candidates)

    def detect(text: str) -> list[Issue]:
        return find_dictionary_issues(text, is_known, suggest)

    return detect
