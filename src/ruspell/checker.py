"""Публичная точка входа: проверка текста и исправленный текст."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ruspell.check import build_layers, check_text
from ruspell.dictionary import get_morph_analyzer
from ruspell.issues import apply_issues, collapse_repeats
from ruspell.models import Issue
from ruspell.vocabulary import vocabulary_words
from ruspell.weights import default_weights_dir


class SpellChecker:
    """Проверка русского текста: орфография и согласование.

    Собирает слои один раз и держит их: морфологический словарь и веса slovnet
    грузятся секунды, а проверка текста — миллисекунды. Один экземпляр на
    процесс, дальше только ``check`` и ``correct``.

    Экземпляр неизменяем и не хранит состояния между вызовами, поэтому его
    можно звать из нескольких потоков.

    Example:
        >>> checker = SpellChecker(vocabulary={"оквэд", "техрегламент"})
        >>> [issue.word for issue in checker.check("Направляем предложния.")]
        ['предложния']
    """

    def __init__(
        self,
        vocabulary: Iterable[str] = (),
        *,
        weights_dir: Path | None = None,
    ) -> None:
        """Собирает проверку.

        Args:
            vocabulary: Доменная лексика: слова или фразы (аббревиатура и её
                расшифровка). Из фраз берутся все слова, регистр не важен. Эти
                слова не считаются ошибкой.
            weights_dir: Каталог с весами slovnet и частотным словарём. По
                умолчанию — ``$RUSPELL_WEIGHTS_DIR``, иначе ``~/.cache/ruspell``.
                Весов нет — работает один словарный слой.
        """
        self._weights_dir = weights_dir or default_weights_dir()
        self._layers = build_layers(
            vocabulary_words(vocabulary),
            self._weights_dir,
            get_morph_analyzer(),
        )

    @property
    def layers(self) -> tuple[str, ...]:
        """Имена поднявшихся слоёв: ``dictionary`` и, если есть веса, ``agreement``."""
        return tuple(self._layers)

    @property
    def weights_dir(self) -> Path:
        """Каталог, в котором проверка искала веса."""
        return self._weights_dir

    def check(self, text: str) -> list[Issue]:
        """Возвращает замечания к тексту.

        Повторы одной и той же опечатки сворачиваются в одно замечание: список
        отвечает на вопрос «что исправить», а не «сколько раз оно встретилось».

        Args:
            text: Проверяемый текст; переводы строк разделяют предложения.

        Returns:
            Замечания по возрастанию позиции в тексте.
        """
        return collapse_repeats(check_text(text, self._layers))

    def correct(self, text: str) -> str:
        """Возвращает текст с применённым первым вариантом каждого замечания.

        Повторы здесь не сворачиваются, в отличие от ``check``: опечатка,
        встреченная трижды, должна быть исправлена трижды. Замечания без
        вариантов замены текст не меняют.

        Args:
            text: Исправляемый текст.

        Returns:
            Исправленный текст.
        """
        return apply_issues(text, check_text(text, self._layers))
