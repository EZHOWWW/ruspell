"""Сборка слоёв и обход текста.

Слои перечисляются в порядке доверия — словарный, затем согласование. При
пересечении спанов выигрывает более ранний: на одном слове не должно быть двух
замечаний с разными объяснениями.

Слой согласования может не подняться — не установлена экстра, не скачаны веса,
обрезан архив. Это не повод ронять проверку: она деградирует до словарного
слоя, а причина уходит в лог ``ruspell``. Проверка без согласования хуже
полной, но несравнимо лучше исключения.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from pymorphy3 import MorphAnalyzer

from ruspell import agreement, dictionary
from ruspell.issues import Detector, merge_issues, shift
from ruspell.models import Issue
from ruspell.weights import FREQUENCY_FILE

logger = logging.getLogger("ruspell")


def check_text(text: str, layers: Mapping[str, Detector]) -> list[Issue]:
    """Собирает замечания по всему тексту.

    Текст разбирается построчно: слои работают над предложением, а перевод
    строки — единственная граница, которая есть в простом тексте. Спаны при
    этом пересчитываются в координаты всего текста, поэтому
    ``text[issue.start : issue.end] == issue.word``.

    Повторы не сворачиваются: этим занимается ``collapse_repeats`` на выдаче, а
    исправление текста должно видеть каждое вхождение.

    Args:
        text: Проверяемый текст.
        layers: Слои проверки в порядке доверия.

    Returns:
        Замечания по всему тексту, по возрастанию позиции.
    """
    issues: list[Issue] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        found = merge_issues([layer(line) for layer in layers.values()])
        issues.extend(shift(issue, offset) for issue in found)
        offset += len(line)
    return issues


def build_layers(
    vocabulary: frozenset[str],
    weights_dir: Path,
    analyzer: MorphAnalyzer,
) -> dict[str, Detector]:
    """Собирает слои проверки в порядке доверия.

    Args:
        vocabulary: Доменная лексика — слова, которые не считаются ошибкой.
        weights_dir: Каталог с весами slovnet и частотным словарём.
        analyzer: Морфологический анализатор pymorphy3.

    Returns:
        Слои по именам: ``dictionary`` всегда, ``agreement`` — если поднялся.
    """
    rank: dictionary.Ranker = (
        dictionary.frequency_ranker(weights_dir / FREQUENCY_FILE) or dictionary.rank_suggestions
    )
    layers: dict[str, Detector] = {
        "dictionary": dictionary.build_layer(vocabulary, analyzer, rank),
    }
    try:
        layers["agreement"] = agreement.build_layer(analyzer, weights_dir)
    except Exception as exc:
        # Ловится всё намеренно. Слой опциональный, и способов не подняться у
        # него больше, чем стоит перечислять: нет пакетов, нет файла, нет прав,
        # обрезанный при скачивании tar (``tarfile.ReadError`` — не
        # ``OSError``), несовместимая версия весов. Ни один из них не должен
        # превращать проверку текста в исключение: деградация до словаря
        # обещана в докстринге модуля и в README.
        logger.warning("Слой согласования не поднялся (%s) — работает только словарь", exc)
    return layers
