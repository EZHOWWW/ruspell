"""Сборка доменного словаря из своего корпуса текстов.

Словарь — это слова, которые встречаются в ваших текстах и отсутствуют в общем
словаре pymorphy3: названия организаций, отраслевые термины, аббревиатуры. Без
него проверка подчёркивает их все, и человек перестаёт ей доверять.

Правило отбора одно: слово должно встретиться минимум в ``MIN_DOCUMENTS``
*разных* документах. Повтор внутри одного документа ничего не доказывает —
повторяться может и сама опечатка.

ВНИМАНИЕ: в такой словарь попадают фамилии — подписант или адресат
повторяется из документа в документ и проходит любой частотный фильтр.
Персональным данным в словаре не место: словарь уезжает в репозиторий, в образ
и в чужие руки. Проверке фамилии не нужны: за них отвечает правило «слово рядом
с инициалами» (``near_initials`` в ``ruspell/issues.py``) — оно работает для
любого имени, а не только для встреченного в корпусе.

Автоматически имена не отсеиваются. pymorphy3 предсказывает разбор незнакомого
слова по аналогии и метит именами половину доменной лексики, а половину фамилий
пропускает; фильтр по этому признаку выбросил бы термины и оставил фамилии.
Поэтому кандидаты только *перечисляются*, а решение остаётся за человеком:
словарь в несколько десятков слов пересобирается редко, и подпись человека под
персданными дешевле неверного фильтра.

Аббревиатуры сюда добавлять не нужно, если они уже есть в вашем справочнике:
``SpellChecker(vocabulary=...)`` принимает и сокращение, и расшифровку одной
строкой, и справочник живее файла в репозитории.

Запуск:
    uv run python examples/build_vocabulary.py <каталог с .txt> [словарь.json]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from pymorphy3 import MorphAnalyzer

from ruspell.issues import WORD_RE

MIN_DOCUMENTS = 3
MIN_LENGTH = 3
PERSONAL_NAME_TAGS = frozenset({"Surn", "Name", "Patr"})


def document_words(path: Path) -> set[str]:
    """Возвращает множество слов одного документа в нижнем регистре."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return {match.group().lower() for match in WORD_RE.finditer(text)}


def build(corpus: Path, analyzer: MorphAnalyzer) -> list[str]:
    """Собирает словарь по каталогу с текстами.

    Args:
        corpus: Каталог с ``.txt`` (обходится рекурсивно).
        analyzer: Морфологический анализатор pymorphy3.

    Returns:
        Слова словаря по алфавиту.
    """
    counts: Counter[str] = Counter()
    for path in sorted(corpus.rglob("*.txt")):
        counts.update(document_words(path))
    return sorted(
        word
        for word, count in counts.items()
        if count >= MIN_DOCUMENTS and len(word) >= MIN_LENGTH and not analyzer.word_is_known(word)
    )


def name_candidates(words: list[str], analyzer: MorphAnalyzer) -> list[str]:
    """Возвращает слова, у которых есть разбор как фамилия, имя или отчество."""
    return [
        word
        for word in words
        if any(PERSONAL_NAME_TAGS & set(parse.tag.grammemes) for parse in analyzer.parse(word))
    ]


def main() -> int:
    """Точка входа сборки словаря."""
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    corpus = Path(sys.argv[1])
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("vocabulary.json")
    analyzer = MorphAnalyzer()

    words = build(corpus, analyzer)
    output.write_text(json.dumps(words, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(words)} слов -> {output}")

    candidates = name_candidates(words, analyzer)
    if candidates:
        print(
            "Проверьте вручную и удалите — похоже на ФИО, персданным в словаре не место: "
            + ", ".join(candidates),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
