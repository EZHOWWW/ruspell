"""Слой согласования на slovnet — то, чего словарь не видит в принципе.

Большинство настоящих ошибок в деловом тексте — это согласование в
*существующих* словах: «Указанная работы выполнены», «согласно приказа»,
«направлены в 89 субъектов». Ни один словарь такую ошибку не находит: все слова
есть в языке.

slovnet даёт разбор морфологии и синтаксиса на numpy, без torch и без JVM:
около 30 МБ весов, порядка 140 МБ резидентной памяти, единицы миллисекунд на
предложение. Проверяются две вещи и обе — по дугам синтаксического дерева:

* **``amod``** — определение согласуется с вершиной по падежу, числу и роду;
* **``case``** — однопадежный предлог требует своего падежа.

Многопадежные предлоги и согласование сказуемого сознательно не проверяются: на
корпусе деловых писем расширенный набор правил снизил F₀.₅ с 0.118 до 0.063, а
ложные срабатывания поднял с 0.94 до 2.45 на 1000 токенов при отсекающем пороге
не больше 2. Синтаксический разбор делового текста ошибается слишком часто,
чтобы строить на нём широкие правила.

Импорты slovnet отложены внутрь функций: пакеты ставятся экстрой
``ruspell[agreement]``, и модуль обязан импортироваться без них — иначе
``build_layers`` не смог бы отличить «нет пакетов» от «нет весов».
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from pymorphy3 import MorphAnalyzer
from pymorphy3.tagset import OpencorporaTag

from ruspell.issues import MAX_SUGGESTIONS, Detector, shift
from ruspell.models import Issue
from ruspell.weights import MORPH_FILE, NAVEC_FILE, SYNTAX_FILE, missing_weights

logger = logging.getLogger("ruspell")

MAX_TOKENS = 300
"""Предложения длиннее не разбираются.

Синтаксис slovnet строит матрицу «токен × токен», и память растёт квадратично:
3200 токенов — +140 МБ, 6400 — +660 МБ, 20 000 — больше 3 ГБ и OOM-kill
процесса, которого не поймать ``except``. Длинная строка — обычный вход: текст
из PDF или HTML, поле формы без переводов строк. Поэтому строка режется на
предложения, а «предложение» длиннее порога — таблица, список или мусор: разбор
на нём всё равно негоден. До 1600 токенов пик памяти не растёт, так что у порога
пятикратный запас.
"""

MAX_ARC = 3
"""Дуги длиннее трёх слов или через знак препинания не проверяются.

На них ошибается разбор, а не автор: «крупный просветительский,
образовательный, туристический центр» slovnet привязал к «труду» в другом
конце фразы. Замер на реальных ошибках RLC, GERA и LORuGEC: на таких дугах 13
из 167 верных замечаний ``amod`` и 63 из 163 ложных. На чистых текстах
(kremlin.ru, SynTagRus, PUD, RuCoLA) ложных замечаний согласования стало 308
вместо 797, а полнота на синтетических ошибках ``amod`` упала с 0.80 до 0.77.
"""

QUOTES = frozenset("«»„“”\"'")
"""Кавычки дугу не рвут: «согласно «Положения»» — обычное управление."""

AGREEING_FEATURES = ("Case", "Number", "Gender")

FEATURE_NAMES = {"Case": "падеж", "Number": "число", "Gender": "род"}
"""Названия признаков для сообщения пользователю.

Сообщение читает человек, а не разработчик: «по признакам: Number» в русском
тексте — это утечка нотации UD наружу.
"""

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
PYMORPHY_ANIMACY = {"Anim": "anim", "Inan": "inan"}

BASE_CASES = {"gen1": "gent", "gen2": "gent", "acc2": "accs", "loc1": "loct", "loc2": "loct"}
"""Второй родительный («чаю») и второй предложный («в лесу») — те же падежи для
согласования и управления: pymorphy3 различает их, а UD и предлоги — нет."""


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

    Кэшируется: веса весят 30 МБ и разворачиваются в ~140 МБ, второй раз это
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
        text: Одно предложение.
        tokenize: Токенизатор, отдающий текст и позиции.
        morph: Морфологическая модель slovnet.
        syntax: Синтаксическая модель slovnet.

    Returns:
        Слова предложения с разбором; пустой список, если токенов нет или их
        больше ``MAX_TOKENS``.
    """
    spans = list(tokenize(text))
    if not spans or len(spans) > MAX_TOKENS:
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
        feats: Признаки в нотации UD — ``Case``, ``Number``, ``Gender``,
            ``Animacy``. Без ``Number`` число берётся у каждого разбора своё.
        analyzer: Морфологический анализатор pymorphy3.

    Returns:
        Варианты замены, не совпадающие с исходным словом.
    """
    # Род во множественном числе не берётся: его там нет, и разметка ставит его
    # как придётся. Одушевлённость различает формы только в винительном мужского
    # рода и множественного числа («новый дом», но «нового директора»); у прочих
    # форм pymorphy3 её не размечает, и склонение с ней не нашло бы ничего.
    number = feats.get("Number", "")
    gender = PYMORPHY_GENDERS.get(feats.get("Gender", "")) if number != "Plur" else None
    animacy = (
        PYMORPHY_ANIMACY.get(feats.get("Animacy", ""))
        if feats.get("Case") == "Acc" and (number == "Plur" or gender == "masc")
        else None
    )
    grammemes = {
        grammeme
        for grammeme in (
            PYMORPHY_CASES.get(feats.get("Case", "")),
            PYMORPHY_NUMBERS.get(number),
            gender,
            animacy,
        )
        if grammeme is not None
    }
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


def near(words: list[Word], first: int, second: int) -> bool:
    """Проверяет, что слова рядом: не дальше ``MAX_ARC`` и без знаков препинания между."""
    left, right = sorted((first, second))
    return right - left <= MAX_ARC and all(
        word.text in QUOTES or any(char.isalnum() for char in word.text)
        for word in words[left + 1 : right]
    )


def base_case(tag: OpencorporaTag) -> str | None:
    """Возвращает падеж разбора pymorphy3, склеив второй родительный и предложный с первыми."""
    case = str(tag.case) if tag.case else None
    return BASE_CASES.get(case, case) if case else None


def can_agree(dependent: str, head: str, analyzer: MorphAnalyzer) -> bool:
    """Проверяет, что формы согласуются хотя бы при одном разборе pymorphy3.

    slovnet выбирает один разбор и на омонимичных формах ошибается: «работы» —
    и родительный единственного, и именительный множественного, и в
    «выполнены строительно-монтажные работы» он выбирал первое. Если
    согласованная пара разборов есть, утверждать ошибку нельзя.
    """
    for left in analyzer.parse(dependent.lower()):
        for right in analyzer.parse(head.lower()):
            if (
                base_case(left.tag) != base_case(right.tag)
                or left.tag.number != right.tag.number
                or (
                    left.tag.animacy and right.tag.animacy and left.tag.animacy != right.tag.animacy
                )
            ):
                continue
            if (
                left.tag.number == "plur"
                or None in (left.tag.gender, right.tag.gender)
                or left.tag.gender == right.tag.gender
                or "ms-f" in right.tag
            ):
                return True
    return False


def can_take(word: str, case: str, analyzer: MorphAnalyzer) -> bool:
    """Проверяет, что у слова есть разбор в падеже ``case`` (нотация UD)."""
    return any(
        base_case(parsed.tag) == PYMORPHY_CASES[case] for parsed in analyzer.parse(word.lower())
    )


def find_disagreements(words: list[Word], analyzer: MorphAnalyzer) -> Iterator[Issue]:
    """Ищет рассогласование определения с вершиной.

    Род у множественного числа не проверяется: во множественном его нет, и
    разметка ставит его как придётся. Три конструкции пропускаются, потому что
    правильная фраза в них выглядит рассогласованной:

    * счётная группа: «два рабочих дня» — определение во множественном,
      вершина в родительном единственного;
    * однородные определения: «федерального и областного бюджетов» — каждое в
      единственном, вершина во множественном;
    * омонимия: формы согласуются хотя бы при одном разборе (``can_agree``).

    Дальние дуги не проверяются вовсе (``MAX_ARC``).
    """
    counted = {word.head for word in words if word.relation.startswith("nummod")}
    coordinated = {word.head for word in words if word.relation == "conj"}
    for index, word in enumerate(words):
        if word.relation != "amod" or not 0 <= word.head < len(words):
            continue
        if word.head in counted or index in coordinated or not near(words, index, word.head):
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
        if not mismatched or can_agree(word.text, head.text, analyzer):
            continue
        suggestions = inflect(word.text, head.feats, analyzer)
        if not suggestions:
            continue
        yield Issue(
            word=word.text,
            start=word.start,
            end=word.end,
            category="AGREEMENT",
            suggestions=tuple(suggestions),
            message=(
                f"Не согласовано с «{head.text}» по признакам: "
                + ", ".join(FEATURE_NAMES[feature] for feature in mismatched)
            ),
        )


def find_government_errors(words: list[Word], analyzer: MorphAnalyzer) -> Iterator[Issue]:
    """Ищет нарушение падежного управления однопадежных предлогов.

    Счётная группа пропускается: в «через 2 года» предлог управляет
    числительным, а «года» стоит в родительном по счёту. Форма, у которой есть
    разбор в требуемом падеже, тоже: ошибку в ней утверждать нельзя. Предлог
    проверяется, только если его слово справа и рядом (``MAX_ARC``): иначе дугу
    провёл ошибившийся разбор.

    Число вершины в склонение не передаётся: на ошибочной форме slovnet его
    путает («согласно распоряжения» размечено Plur), а pymorphy3 сохраняет число
    каждого разбора сам. Род передаётся — он отсекает омонимы: «графика» в
    «согласно графика» склоняется в «графику», а не в «графике».
    """
    counted = {word.head for word in words if word.relation.startswith("nummod")}
    for index, word in enumerate(words):
        if word.relation != "case" or not index < word.head < len(words) or word.head in counted:
            continue
        if not near(words, index, word.head):
            continue
        required = SINGLE_CASE_PREPOSITIONS.get(word.text.lower())
        head = words[word.head]
        actual = head.feats.get("Case")
        if required is None or actual is None or actual == required:
            continue
        if can_take(head.text, required, analyzer):
            continue
        feats = {"Case": required, "Gender": head.feats.get("Gender", "")}
        suggestions = inflect(head.text, feats, analyzer)
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
        RuntimeError: Если не установлена экстра ``ruspell[agreement]``.
    """
    try:
        from razdel import sentenize, tokenize
    except ImportError as exc:
        raise RuntimeError('Не установлена экстра agreement: uv add "ruspell[agreement]"') from exc

    morph, syntax = load_models(weights_dir)

    def detect(text: str) -> list[Issue]:
        issues: list[Issue] = []
        for sentence in sentenize(text):
            try:
                words = parse_sentence(sentence.text, tokenize, morph, syntax)
            except Exception as exc:
                # Ловится всё намеренно, ровно по той же причине, что и на сборке
                # слоя в ``check.build_layers``: разбор — это чужая модель на чужих
                # весах, и её отказ на одном предложении не должен превращать
                # проверку всего текста в исключение. Его разберёт словарный слой.
                logger.warning(
                    "Разбор предложения не удался (%s) — оно проверено только словарём", exc
                )
                continue
            found = [
                *find_disagreements(words, analyzer),
                *find_government_errors(words, analyzer),
            ]
            issues.extend(shift(issue, sentence.start) for issue in found)
        return sorted(issues, key=lambda issue: (issue.start, issue.end))

    return detect
