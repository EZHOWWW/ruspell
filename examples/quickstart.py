"""Проверка текста с доменным словарём из файла.

Словарь рядом — ``examples/vocabulary.json``, термины в нём вымышленные:
это образец формата, а не готовая лексика. Свой словарь собирается из своего
корпуса, рецепт — в ``examples/build_vocabulary.py``.

Запуск:
    uv run python examples/quickstart.py
"""

from __future__ import annotations

from pathlib import Path

from ruspell import SpellChecker, load_vocabulary

TEXT = """Уведомлеие о проведении энергоаудита направлено в срок.
Указанная работы выполнены согласно приказа.
Выделено 120 машино-мест, ПСД передана заказчику."""


def main() -> None:
    """Печатает замечания к тексту и его исправленный вариант."""
    checker = SpellChecker(vocabulary=load_vocabulary(Path(__file__).parent / "vocabulary.json"))
    print("слои:", ", ".join(checker.layers))
    print("веса:", checker.weights_dir)
    print()

    for issue in checker.check(TEXT):
        variants = ", ".join(issue.suggestions) or "нет вариантов"
        print(f"[{issue.category}] {issue.word} ({issue.start}:{issue.end}) -> {variants}")
        if issue.message:
            print(f"          {issue.message}")

    print()
    print(checker.correct(TEXT))


if __name__ == "__main__":
    main()
