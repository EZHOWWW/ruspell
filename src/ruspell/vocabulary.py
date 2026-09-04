"""Доменная лексика: сборка словаря и снятие объяснимых им замечаний.

Любой текст полон слов, которых нет в общих словарях и которые при этом
абсолютно корректны: названия организаций, отраслевые термины, аббревиатуры и
их расшифровки. Проверка подчёркивает их все, и именно эти подчёркивания
обесценивают её целиком: увидев одно нелепое замечание, человек перестаёт
доверять и остальным.

Своего словаря библиотека не везёт — доменная лексика у каждого своя, а чужая
только мешает. Пустой словарь — рабочее состояние: проверка находит то же
самое, просто шумит на доменных словах.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from ruspell.issues import WORD_RE
from ruspell.models import Issue


def vocabulary_words(phrases: Iterable[str]) -> frozenset[str]:
    """Разбирает фразы на слова доменного словаря.

    Аббревиатуру обычно заводят вместе с расшифровкой, и подчёркивать нельзя ни
    то, ни другое: слово из расшифровки — такое же доменное, как и сама
    аббревиатура. Поэтому на вход принимаются любые строки — и отдельные слова,
    и целые фразы, — а словарём становятся все слова из них.

    Args:
        phrases: Слова, сокращения и расшифровки как их ввёл пользователь.

    Returns:
        Слова этих фраз в нижнем регистре.

    Raises:
        TypeError: Если передана одна строка вместо коллекции строк.
    """
    if isinstance(phrases, str):
        # Строка — тоже Iterable[str], и без этой проверки она разбирается
        # посимвольно: словарь молча оказывается набором отдельных букв, все
        # короче MIN_LENGTH, то есть пустым. Молчаливо пустой словарь — худший
        # из возможных ответов: проверка шумит ровно на том, что ей передали.
        raise TypeError(
            f'Ожидалась коллекция строк, а не одна строка {phrases!r}: передайте ["{phrases}"]',
        )
    return frozenset(
        match.group().lower() for phrase in phrases for match in WORD_RE.finditer(phrase)
    )


def load_vocabulary(path: str | Path) -> frozenset[str]:
    """Читает доменный словарь из JSON-файла со списком строк.

    Строки — слова или фразы, разбираются так же, как в ``vocabulary_words``.

    Args:
        path: Путь к JSON-файлу со списком строк; строка или ``Path``.

    Returns:
        Слова словаря в нижнем регистре.

    Raises:
        ValueError: Если в файле не список строк.
    """
    content: object = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(content, list) or not all(isinstance(item, str) for item in content):
        raise ValueError(f"Ожидался список строк в {path}")
    return vocabulary_words(content)


def in_vocabulary(word: str, vocabulary: frozenset[str]) -> bool:
    """Проверяет, что слово знакомо домену.

    Составные термины отдельного разбора не требуют: и текст, и словарь режутся
    одним и тем же ``WORD_RE``, а он дефис словом не считает. «машино-мест» с
    обеих сторон распадается на «машино» и «мест», и слово из словаря совпадает
    со словом из текста само собой.

    Args:
        word: Проверяемое слово.
        vocabulary: Доменный словарь.

    Returns:
        ``True``, если слово следует считать корректным.
    """
    return word.strip().lower() in vocabulary


def drop_vocabulary_words(
    issues: Sequence[Issue],
    vocabulary: frozenset[str],
) -> list[Issue]:
    """Убирает замечания, объяснимые доменной лексикой, а не ошибкой."""
    return [issue for issue in issues if not in_vocabulary(issue.word, vocabulary)]
