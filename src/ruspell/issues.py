"""Чистая логика проверки: поиск, слияние и применение замечаний.

Здесь нет ни словарей, ни моделей, ни файлов, ни сети — только работа над
текстом и списками замечаний. Всё, что требует ресурсов, передаётся
параметром, поэтому логика тестируется подставными функциями.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from ruspell.models import Issue

WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[\u0300-\u036f\u00ad\u200b-\u200d\u2060])*")
"""Слово — буквы любого алфавита подряд вместе с невидимыми символами внутри.

Проверяются из них только кириллические (``CYRILLIC_WORD``): латиницу, цифры и
знаки проверять нечем, а флагов на них было бы больше, чем пользы. Но резать
текст на слова нужно по буквам любого алфавита и с невидимыми символами:
латинская «е» внутри кириллического слова, мягкий перенос U+00AD из HTML и
Word, «й» в разложенной форме (U+0306) из PDF иначе разрезали бы слово на
обрывки. Обрывок подчёркивался, а ``correct`` вставлял исправление в середину
слова: «пред\xadложение» → «пред\xadвложение».
"""

CYRILLIC_WORD = re.compile(r"[а-яё]+")

IGNORED_MARKS = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\u0300\u0301"))
"""Мягкий перенос, символы нулевой ширины и знаки ударения: в написании слова их нет."""

MIN_LENGTH = 4
"""Короткие слова не проверяются: на трёх буквах вариантов замены больше, чем
слов в языке, и почти все они мимо."""

MAX_LENGTH = 40
"""Длинные слова не проверяются: в языке таких нет, а перебор правок взрывается.

``edits1`` порождает около 66 вариантов на букву, каждый длиной в слово: на 1000
букв это +60 МБ и полсекунды, на 5000 — больше 3 ГБ и OOM-kill процесса. Такое
«слово» — склейка из PDF, base64 в кириллице или мусор, а самые длинные слова
словарей короче 40 букв."""

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

COMPOUND_HEAD = re.compile(r"[-\u2010\u2011][А-Яа-яЁё]")
"""Дефис и буква сразу за словом: это первая часть составного слова.

Её не проверяем. У первой части соединительная гласная — «технико-»,
«пуско-», «медико-», «северо-», — отдельным словом её нет в словаре по
построению, а в одной правке от неё всегда есть настоящее слово. Проверка
подчёркивала каждое такое слово, а ``correct`` писал «техника-экономическое».
Вторая часть — обычное слово и проверяется как обычно.
"""

Detector = Callable[[str], list[Issue]]
"""Слой проверки: из текста строки — список замечаний со спанами в ней."""


def normalize_word(word: str) -> str:
    """Приводит слово к виду словаря: без невидимых символов и ударений, в NFC, строчными.

    Для словаря «нови\u0306» и «новый» — разные слова, а для читателя одно.
    Знаки убираются до NFC: иначе «и» с ударением собралось бы в отдельную букву.
    """
    return unicodedata.normalize("NFC", word.translate(IGNORED_MARKS)).lower()


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
        lowered = normalize_word(word)
        if not CYRILLIC_WORD.fullmatch(lowered) or not MIN_LENGTH <= len(lowered) <= MAX_LENGTH:
            continue
        if word.isupper() or is_known(lowered):
            continue
        if near_initials(text, match.start(), match.end()):
            continue
        if COMPOUND_HEAD.match(text, match.end()):
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
