"""Контракт проверки: замечание и его сериализация.

Замечание — обычный неизменяемый ``dataclass`` без внешних зависимостей:
библиотека не навязывает потребителю ни pydantic, ни своей модели данных. Кому
нужен JSON — есть ``Issue.as_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

IssueCategory = Literal["SPELL", "AGREEMENT"]
"""Тип замечания.

Разделение нужно не для отчётности, а для интерфейса: «орфография» и
«согласование» — разные действия пользователя, и смешивать их в одном списке
значит заставлять его сортировать вручную.

* ``SPELL`` — слова нет в языке (опечатка);
* ``AGREEMENT`` — слово есть, но не согласовано с соседним.
"""


class IssueDict(TypedDict):
    """Замечание в виде JSON-совместимого словаря."""

    word: str
    start: int
    end: int
    category: str
    suggestions: list[str]
    message: str


@dataclass(frozen=True, slots=True)
class Issue:
    """Подозрительное место в тексте вместе с вариантами исправления.

    Спан ``[start, end)`` — позиции в том тексте, который передали в проверку,
    поэтому ``text[issue.start : issue.end] == issue.word``.

    Attributes:
        word: Слово как оно написано в тексте.
        start: Позиция первого символа слова.
        end: Позиция за последним символом слова.
        category: Тип замечания.
        suggestions: Варианты замены, лучший первым. Может быть пустым:
            проверка нашла подозрительное место, но не знает, чем его заменить.
        message: Объяснение для пользователя; у орфографии пустое — там
            объяснять нечего.
    """

    word: str
    start: int
    end: int
    category: IssueCategory
    suggestions: tuple[str, ...] = ()
    message: str = ""

    def as_dict(self) -> IssueDict:
        """Возвращает замечание словарём — для JSON-ответа или лога."""
        return IssueDict(
            word=self.word,
            start=self.start,
            end=self.end,
            category=self.category,
            suggestions=list(self.suggestions),
            message=self.message,
        )
