"""Проверка орфографии и согласования русского текста.

Два слоя. Словарный ловит слова, которых нет в языке, и снимает с них доменный
шум. Слой согласования на slovnet ловит ошибки в *существующих* словах — падеж,
род, число, управление предлогов; словарь их не видит по определению.

Быстрый старт::

    from ruspell import SpellChecker

    checker = SpellChecker(vocabulary={"оквэд", "техрегламент"})
    for issue in checker.check("Направляем предложния согласно приказа."):
        print(issue.word, issue.category, issue.suggestions)

Слой согласования опционален: нет экстры ``ruspell[agreement]`` или не скачаны
веса — проверка молча работает одним словарным слоем, а какие слои поднялись,
видно в ``SpellChecker.layers``.

Чистая логика живёт отдельно и импортируется напрямую: ``ruspell.issues``
(слияние спанов, применение правок, свёртка повторов), ``ruspell.dictionary``
(``edits1``, ранжирование), ``ruspell.vocabulary`` (доменный словарь).
"""

from __future__ import annotations

from ruspell.checker import SpellChecker
from ruspell.models import Issue, IssueCategory, IssueDict
from ruspell.vocabulary import load_vocabulary, vocabulary_words
from ruspell.weights import default_weights_dir

__all__ = [
    "Issue",
    "IssueCategory",
    "IssueDict",
    "SpellChecker",
    "default_weights_dir",
    "load_vocabulary",
    "vocabulary_words",
]
