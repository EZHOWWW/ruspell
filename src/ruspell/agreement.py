"""Слой согласования на slovnet — то, чего словарь не видит в принципе.

Большинство настоящих ошибок в деловом тексте — это согласование в
*существующих* словах: «Указанная работы выполнены», «согласно приказа»,
«направлены в 89 субъектов». Ни один словарь такую ошибку не находит: все слова
есть в языке.

slovnet даёт разбор морфологии и синтаксиса на numpy, без torch и без JVM:
около 30 МБ весов, порядка 200 МБ резидентной памяти, десятки миллисекунд на
предложение. Проверяются две вещи и обе — по дугам синтаксического дерева:

* **``amod``** — определение согласуется с вершиной по падежу, числу и роду;
* **``case``** — однопадежный предлог требует своего падежа.

Многопадежные предлоги и согласование сказуемого сознательно не проверяются: на
замере расширенный набор правил уронил точность и вывел ложные срабатывания за
приемлемый порог. Синтаксический разбор делового текста ошибается слишком
часто, чтобы строить на нём широкие правила.

Импорты slovnet отложены внутрь функций: пакеты ставятся экстрой
``ruspell[agreement]``, и модуль обязан импортироваться без них — иначе
``build_layers`` не смог бы отличить «нет пакетов» от «нет весов».
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from pymorphy3 import MorphAnalyzer

from ruspell.issues import MAX_SUGGESTIONS, Detector
from ruspell.models import Issue
from ruspell.weights import MORPH_FILE, NAVEC_FILE, SYNTAX_FILE, missing_weights

AGREEING_FEATURES = ("Case", "Number", "Gender")

PREPOSITIONS_BY_CASE: dict[str, str] = {
    "Gen": (
        "без близ вблизи ввиду вдоль вместо вне внутри возле вокруг впереди вследствие "
        "для до из из-за из-под касательно кроме около от относительно помимо после "
        "посреди против путём ради сверх среди у"
    ),
    "Dat": "благодаря вопреки к навстречу наперекор подобно согласно соответственно",
    "Acc": "включая несмотря про сквозь спустя через",
    "Ins": "над перед пред",
    "Loc": "при",
}
"""Предлоги, требующие ровно одного падежа.

Многопадежных здесь нет намеренно: «в», «на», «с», «по» и «за» управляют разными
падежами в зависимости от смысла, и правило на них даёт ложные срабатывания.
"""

SINGLE_CASE_PREPOSITIONS: dict[str, str] = {
    preposition: case
    for case, prepositions in PREPOSITIONS_BY_CASE.items()
    for preposition in prepositions.split()
}
"""Обратный индекс: предлог — требуемый им падеж."""

CASE_NAMES = {
    "Nom": "именительный",
    "Gen": "родительный",
    "Dat": "дательный",
    "Acc": "винительный",
    "Ins": "творительный",
    "Loc": "предложный",
}

PYMORPHY_CASES = {
    "Nom": "nomn",
    "Gen": "gent",
    "Dat": "datv",
    "Acc": "accs",
    "Ins": "ablt",
    "Loc": "loct",
}
PYMORPHY_NUMBERS = {"Sing": "sing", "Plur": "plur"}
PYMORPHY_GENDERS = {"Masc": "masc", "Fem": "femn", "Neut": "neut"}


class Span(Protocol):
    """Токен с позицией — то, что отдаёт ``razdel.tokenize``."""

    text: str
    start: int
    stop: int


Tokenizer = Callable[[str], Iterable[Span]]
"""Разбиение текста на токены с их позициями."""


class Word(NamedTuple):
    """Слово с разбором и позицией в тексте."""

    text: str
    start: int
    end: int
    feats: dict[str, str]
    head: int
    relation: str


@lru_cache(maxsize=2)
def load_models(weights_dir: Path) -> tuple[Any, Any]:
    """Загружает морфологию и синтаксис slovnet.

    Кэшируется: веса весят 30 МБ и разворачиваются в ~200 МБ, второй раз это
    платить незачем.

    Args:
        weights_dir: Каталог с распакованными архивами весов.

    Returns:
        Пара «морфология, синтаксис». Тип — ``Any``: у slovnet нет ни
        аннотаций, ни ``py.typed``, и описывать его внутренности здесь значило
        бы врать о чужом контракте.

    Raises:
        FileNotFoundError: Если весов нет в каталоге.
    """
    missing = missing_weights(weights_dir)
    if missing:
        raise FileNotFoundError(
            f"Не найдены веса slovnet в {weights_dir}: {', '.join(missing)}. "
            "Скачайте их командой `ruspell-weights download`",
        )
    from navec import Navec
    from slovnet import Morph, Syntax

    navec = Navec.load(str(weights_dir / NAVEC_FILE))
    morph = Morph.load(str(weights_dir / MORPH_FILE)).navec(navec)
    syntax = Syntax.load(str(weights_dir / SYNTAX_FILE)).navec(navec)
    return morph, syntax


def parse_sentence(text: str, tokenize: Tokenizer, morph: Any, syntax: Any) -> list[Word]:
    """Размечает предложение морфологией и синтаксисом.

    Args:
        text: Одно предложение или абзац.
        tokenize: Токенизатор, отдающий текст и позиции.
        morph: Морфологическая модель slovnet.
        syntax: Синтаксическая модель slovnet.

    Returns:
        Слова предложения с разбором; пустой список, если токенов нет.
    """
    spans = list(tokenize(text))
    if not spans:
        return []
    words = [span.text for span in spans]
    tagged = next(morph.map([words]))
    parsed = next(syntax.map([words]))
    index = {token.id: position for position, token in enumerate(parsed.tokens)}
    return [
        Word(
            text=span.text,
            start=span.start,
            end=span.stop,
            feats=dict(tag.feats),
            head=index.get(arc.head_id, -1),
            relation=arc.rel,
        )
        for span, tag, arc in zip(spans, tagged.tokens, parsed.tokens, strict=True)
    ]


def match_case(original: str, replacement: str) -> str:
    """Переносит регистр исходного слова на вариант замены.

    pymorphy3 работает со строчными формами, а слово могло стоять в начале
    предложения. Без переноса регистра исправленный текст получал бы строчную
    букву там, где была прописная.
    """
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def inflect(word: str, feats: dict[str, str], analyzer: MorphAnalyzer) -> list[str]:
    """Приводит слово к требуемым грамматическим признакам, сохраняя регистр.

    Args:
        word: Слово как оно написано в тексте.
        feats: Признаки в нотации UD — ``Case``, ``Number``, ``Gender``.
        analyzer: Морфологический анализатор pymorphy3.

    Returns:
        Варианты замены, не совпадающие с исходным словом.
    """
    grammemes = {
        PYMORPHY_CASES.get(feats.get("Case", "")),
        PYMORPHY_NUMBERS.get(feats.get("Number", "")),
    }
    if feats.get("Number") == "Sing":
        grammemes.add(PYMORPHY_GENDERS.get(feats.get("Gender", "")))
    grammemes.discard(None)
    if not grammemes:
        return []
    original = word.lower()
    variants: list[str] = []
    for parsed in analyzer.parse(original):
        inflected = parsed.inflect(grammemes)
        if inflected and inflected.word != original:
            variant = match_case(word, inflected.word)
            if variant not in variants:
                variants.append(variant)
    return variants[:MAX_SUGGESTIONS]


def find_disagreements(words: list[Word], analyzer: MorphAnalyzer) -> Iterator[Issue]:
    """Ищет рассогласование определения с вершиной.

    Род у множественного числа не проверяется: во множественном его нет, и
    разметка ставит его как придётся.
    """
    for word in words:
        if word.relation != "amod" or not 0 <= word.head < len(words):
            continue
        head = words[word.head]
        mismatched = [
            feature
            for feature in AGREEING_FEATURES
            if feature in word.feats
            and feature in head.feats
            and word.feats[feature] != head.feats[feature]
            and not (feature == "Gender" and head.feats.get("Number") == "Plur")
        ]
        suggestions = inflect(word.text, head.feats, analyzer) if mismatched else []
        if not suggestions:
            continue
        yield Issue(
            word=word.text,
            start=word.start,
            end=word.end,
            category="AGREEMENT",
            suggestions=tuple(suggestions),
            message=f"Не согласовано с «{head.text}» по признакам: {', '.join(mismatched)}",
        )


def find_government_errors(words: list[Word], analyzer: MorphAnalyzer) -> Iterator[Issue]:
    """Ищет нарушение падежного управления однопадежных предлогов."""
    for word in words:
        if word.relation != "case" or not 0 <= word.head < len(words):
            continue
        required = SINGLE_CASE_PREPOSITIONS.get(word.text.lower())
        head = words[word.head]
        actual = head.feats.get("Case")
        if required is None or actual is None or actual == required:
            continue
        suggestions = inflect(head.text, {**head.feats, "Case": required}, analyzer)
        if not suggestions:
            continue
        yield Issue(
            word=head.text,
            start=head.start,
            end=head.end,
            category="AGREEMENT",
            suggestions=tuple(suggestions),
            message=(
                f"Предлог «{word.text}» требует {CASE_NAMES[required]} падеж, "
                f"а не {CASE_NAMES.get(actual, actual)}"
            ),
        )


def build_layer(analyzer: MorphAnalyzer, weights_dir: Path) -> Detector:
    """Собирает слой проверки согласования.

    Args:
        analyzer: Морфологический анализатор pymorphy3 — им склоняются варианты.
        weights_dir: Каталог с весами slovnet.

    Returns:
        Слой проверки.

    Raises:
        FileNotFoundError: Если весов нет в каталоге.
        ImportError: Если не установлена экстра ``ruspell[agreement]``.
    """
    from razdel import tokenize

    morph, syntax = load_models(weights_dir)

    def detect(text: str) -> list[Issue]:
        words = parse_sentence(text, tokenize, morph, syntax)
        issues = [
            *find_disagreements(words, analyzer),
            *find_government_errors(words, analyzer),
        ]
        return sorted(issues, key=lambda issue: (issue.start, issue.end))

    return detect
