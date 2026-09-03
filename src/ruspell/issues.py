"""Чистая логика проверки: поиск, слияние и применение замечаний.

Здесь нет ни словарей, ни моделей, ни файлов, ни сети — только работа над
текстом и списками замечаний. Всё, что требует ресурсов, передаётся
параметром, поэтому логика тестируется подставными функциями.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from ruspell.models import Issue

WORD_RE = re.compile(r"[А-Яа-яЁё]+", re.UNICODE)
"""Слово — это последовательность кириллических букв.

Латиница, цифры и знаки словами не считаются: проверять их нечем, а флагов на
них было бы больше, чем пользы.
"""

MIN_LENGTH = 4
"""Короткие слова не проверяются: на трёх буквах вариантов замены больше, чем
слов в языке, и почти все они мимо."""

MAX_SUGGESTIONS = 5
"""Больше пяти вариантов человек всё равно не читает."""

INITIALS_BEFORE = re.compile(r"(?:[А-ЯЁ]\.\s*){1,2}$")
INITIALS_AFTER = re.compile(r"^\s*(?:[А-ЯЁ]\.\s*){1,2}")
INITIALS_WINDOW = 8
"""Инициалы слева или справа от слова.

Фамилия несловарна по определению, а варианты замены на расстоянии одной правки
у неё находятся. Держать фамилии в доменном словаре — плохая идея: словарь
уезжает в репозиторий и в образ, а персональным данным там не место. Без них
проверка подчёркивает каждого адресата и каждого подписанта.

Инициалы рядом со словом решают это без словаря и для любого имени, а не только
для встреченных в корпусе. Оба порядка написания официальны и оба учитываются:
«Фамилия И.О.» и «И.О. Фамилии».
"""

Detector = Callable[[str], list[Issue]]
"""Слой проверки: из текста строки — список замечаний со спанами в ней."""


def near_initials(text: str, start: int, end: int) -> bool:
    """Проверяет, что слово стоит рядом с инициалами — то есть это ФИО."""
    return bool(
        INITIALS_BEFORE.search(text[max(0, start - INITIALS_WINDOW) : start])
        or INITIALS_AFTER.match(text[end : end + INITIALS_WINDOW]),
    )


def find_dictionary_issues(
    text: str,
    is_known: Callable[[str], bool],
    suggest: Callable[[str], list[str]],
) -> list[Issue]:
    """Находит несловарные слова с известными вариантами исправления.

    Сообщается каждое вхождение: спан — это место в тексте, и опечатка,
    повторённая трижды, должна быть исправлена трижды. Свёртка повторов в одну
    строку — дело выдачи, ею занимается ``collapse_repeats``.

    Args:
        text: Проверяемый текст.
        is_known: Предикат «слово есть в словаре».
        suggest: Генератор ранжированных вариантов замены.

    Returns:
        Замечания со спанами в пределах *text*.
    """
    issues: list[Issue] = []
    for match in WORD_RE.finditer(text):
        word = match.group()
        lowered = word.lower()
        if len(word) < MIN_LENGTH or word.isupper() or is_known(lowered):
            continue
        if near_initials(text, match.start(), match.end()):
            continue
        suggestions = suggest(lowered)[:MAX_SUGGESTIONS]
        if not suggestions:
            continue
        if word[0].isupper():
            suggestions = [item.capitalize() for item in suggestions]
        issues.append(
            Issue(
                word=word,
                start=match.start(),
                end=match.end(),
                category="SPELL",
                suggestions=tuple(suggestions),
            ),
        )
    return issues


def shift(issue: Issue, offset: int) -> Issue:
    """Переносит спан замечания из строки в координаты всего текста."""
    return replace(issue, start=issue.start + offset, end=issue.end + offset)


def merge_issues(layers: Iterable[Sequence[Issue]]) -> list[Issue]:
    """Сливает замечания нескольких слоёв, снимая пересечения по спану.

    Слои перечисляются в порядке доверия: при пересечении выигрывает более
    ранний. Иначе на одном слове оказались бы две карточки с разными
    объяснениями, а собрать исправленный текст было бы нельзя.
    """
    merged: list[Issue] = []
    for layer in layers:
        for issue in sorted(layer, key=span):
            if not any(issue.start < kept.end and kept.start < issue.end for kept in merged):
                merged.append(issue)
    return sorted(merged, key=span)


def span(issue: Issue) -> tuple[int, int]:
    """Возвращает спан замечания — ключ сортировки по месту в тексте."""
    return (issue.start, issue.end)


def collapse_repeats(issues: Sequence[Issue]) -> list[Issue]:
    """Оставляет по одному замечанию на каждую повторяющуюся опечатку.

    Список отвечает на вопрос «что исправить», а не «где»: одно и то же
    несуществующее слово, встреченное в тексте пять раз, — это одна строка, а
    не пять. Замечания согласования не сворачиваются: одно слово,
    рассогласованное с разными вершинами, — это разные ошибки.

    Свёрткой занимается только выдача. Исправленный текст строится по полному
    списку, иначе второе вхождение опечатки осталось бы в нём неисправленным.
    """
    seen: set[str] = set()
    kept: list[Issue] = []
    for issue in issues:
        if issue.category != "SPELL":
            kept.append(issue)
            continue
        word = issue.word.lower()
        if word in seen:
            continue
        seen.add(word)
        kept.append(issue)
    return kept


def apply_issues(text: str, issues: Iterable[Issue]) -> str:
    """Собирает исправленный текст, применяя первый вариант каждого замечания.

    Замечания без вариантов пропускаются: проверка нашла подозрительное место,
    но не знает, чем его заменить, и придумывать за неё нельзя. Пересекающиеся
    замечания тоже: первое выигрывает, второе теряется — склеить их всё равно
    нечем.
    """
    parts: list[str] = []
    cursor = 0
    for issue in sorted((issue for issue in issues if issue.suggestions), key=span):
        if issue.start < cursor:
            continue
        parts.append(text[cursor : issue.start])
        parts.append(issue.suggestions[0])
        cursor = issue.end
    parts.append(text[cursor:])
    return "".join(parts)
