"""Словарный слой: pymorphy3, доменная лексика и частотное ранжирование.

Слой находит слова, которых нет в языке, и предлагает замену. Незнакомое слово
считается опечаткой, если на расстоянии одной правки от него есть словарное
слово; варианты упорядочиваются по частоте употребления, потому что
``SpellChecker.correct`` применяет именно первый вариант.

Перед выдачей замечание сверяется с доменной лексикой: слова словаря
пользователя — не ошибки, а обычные слова его текстов.

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
from ruspell.vocabulary import drop_vocabulary_words

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
    процесс: полтора миллиона строк и около 150 МБ в памяти.

    Args:
        path: Путь к частотному словарю.

    Returns:
        Ранжирование или ``None``, если файла нет или он не похож на словарь —
        тогда вызывающий берёт ``rank_suggestions``.
    """
    if not path.exists():
        return None
    frequencies: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
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
    is_known: Callable[[str], bool] = analyzer.word_is_known

    def suggest(word: str) -> list[str]:
        return rank(word, {candidate for candidate in edits1(word) if is_known(candidate)})

    def detect(text: str) -> list[Issue]:
        return drop_vocabulary_words(find_dictionary_issues(text, is_known, suggest), vocabulary)

    return detect
