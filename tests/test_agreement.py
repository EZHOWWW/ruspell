"""Тесты слоя согласования.

Правила проверяются на разобранных вручную предложениях: разбор — дело
slovnet, а сами правила и склонение вариантов от весов не зависят и должны
тестироваться без них.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import pytest

from ruspell import agreement
from ruspell.agreement import (
    Word,
    build_layer,
    find_disagreements,
    find_government_errors,
    inflect,
    match_case,
    parse_sentence,
)
from ruspell.dictionary import get_morph_analyzer

FEMININE_SINGULAR = {"Case": "Nom", "Number": "Sing", "Gender": "Fem"}
PLURAL = {"Case": "Nom", "Number": "Plur"}
MASCULINE_GENITIVE = {"Case": "Gen", "Number": "Sing", "Gender": "Masc"}

needs_razdel = pytest.mark.skipif(
    find_spec("razdel") is None,
    reason="нет экстры ruspell[agreement]: `uv sync --extra agreement`",
)


def analyzer():
    return get_morph_analyzer()


class TestMatchCase:
    def test_capitalised_word_keeps_capital(self):
        assert match_case("Указанная", "указанные") == "Указанные"

    def test_all_caps_word_stays_all_caps(self):
        assert match_case("ПЛАНА", "плану") == "ПЛАНУ"

    def test_lowercase_word_is_untouched(self):
        assert match_case("плана", "плану") == "плану"


class TestInflect:
    def test_word_is_put_into_the_required_case(self):
        assert "приказу" in inflect("приказа", {"Case": "Dat", "Number": "Sing"}, analyzer())

    def test_capitalisation_is_kept(self):
        assert "Указанные" in inflect("Указанная", PLURAL, analyzer())

    def test_the_word_itself_is_never_suggested(self):
        assert "приказа" not in inflect("приказа", MASCULINE_GENITIVE, analyzer())

    def test_without_features_there_is_nothing_to_do(self):
        assert inflect("приказа", {}, analyzer()) == []


class TestFindDisagreements:
    def test_number_mismatch_is_reported(self):
        words = [
            Word("Указанная", 0, 9, FEMININE_SINGULAR, 1, "amod"),
            Word("работы", 10, 16, PLURAL, 2, "nsubj"),
            Word("выполнены", 17, 26, {}, -1, "root"),
        ]
        issues = list(find_disagreements(words, analyzer()))
        assert [(issue.word, issue.category) for issue in issues] == [("Указанная", "AGREEMENT")]
        assert "Указанные" in issues[0].suggestions
        assert "работы" in issues[0].message

    def test_features_are_named_in_russian(self):
        # Сообщение читает человек: «по признакам: Number» — это нотация UD,
        # утёкшая в интерфейс.
        words = [
            Word("Указанная", 0, 9, FEMININE_SINGULAR, 1, "amod"),
            Word("работы", 10, 16, PLURAL, -1, "root"),
        ]
        message = next(find_disagreements(words, analyzer())).message
        assert "число" in message
        assert "Number" not in message

    def test_agreeing_definition_is_not_reported(self):
        words = [
            Word("указанные", 0, 9, PLURAL, 1, "amod"),
            Word("работы", 10, 16, PLURAL, -1, "root"),
        ]
        assert list(find_disagreements(words, analyzer())) == []

    def test_gender_of_plural_head_is_ignored(self):
        words = [
            Word("новые", 0, 5, {"Case": "Nom", "Number": "Plur", "Gender": "Masc"}, 1, "amod"),
            Word("работы", 6, 12, {"Case": "Nom", "Number": "Plur", "Gender": "Fem"}, -1, "root"),
        ]
        assert list(find_disagreements(words, analyzer())) == []

    def test_other_relations_are_not_checked(self):
        words = [
            Word("Указанная", 0, 9, FEMININE_SINGULAR, 1, "nsubj"),
            Word("работы", 10, 16, PLURAL, -1, "root"),
        ]
        assert list(find_disagreements(words, analyzer())) == []

    def test_head_outside_the_sentence_is_skipped(self):
        words = [Word("Указанная", 0, 9, FEMININE_SINGULAR, -1, "amod")]
        assert list(find_disagreements(words, analyzer())) == []


class TestFindGovernmentErrors:
    def test_wrong_case_after_single_case_preposition_is_reported(self):
        words = [
            Word("согласно", 0, 8, {}, 1, "case"),
            Word("приказа", 9, 16, MASCULINE_GENITIVE, -1, "root"),
        ]
        issues = list(find_government_errors(words, analyzer()))
        assert [issue.word for issue in issues] == ["приказа"]
        assert "приказу" in issues[0].suggestions
        assert "дательный" in issues[0].message

    def test_correct_case_is_not_reported(self):
        words = [
            Word("согласно", 0, 8, {}, 1, "case"),
            Word("приказу", 9, 16, {"Case": "Dat", "Number": "Sing", "Gender": "Masc"}, -1, "root"),
        ]
        assert list(find_government_errors(words, analyzer())) == []

    def test_multi_case_preposition_is_not_checked(self):
        words = [
            Word("в", 0, 1, {}, 1, "case"),
            Word("субъекта", 2, 10, MASCULINE_GENITIVE, -1, "root"),
        ]
        assert list(find_government_errors(words, analyzer())) == []


class TestParseSentence:
    def test_tokens_are_matched_with_their_parses(self):
        text = "новые работы"
        words = parse_sentence(text, fake_tokenize, FakeMorph(), FakeSyntax())
        assert [(word.text, word.start, word.end) for word in words] == [
            ("новые", 0, 5),
            ("работы", 6, 12),
        ]
        assert words[0].relation == "amod"
        assert words[0].head == 1
        assert words[0].feats == {"Number": "Plur"}

    def test_head_outside_the_sentence_becomes_minus_one(self):
        words = parse_sentence("новые работы", fake_tokenize, FakeMorph(), FakeSyntax(head="99"))
        assert words[0].head == -1

    def test_empty_text_gives_no_words(self):
        assert parse_sentence("", fake_tokenize, FakeMorph(), FakeSyntax()) == []


@needs_razdel
class TestBuildLayer:
    """Слой не имеет права ронять проверку — ни на сборке, ни на разборе.

    Сборка слоя — единственное здесь, что требует razdel: правила проверяются
    на разобранных вручную предложениях и от экстры не зависят.
    """

    def test_broken_parse_degrades_to_no_issues(self, monkeypatch, caplog):
        def explode(*args, **kwargs):
            raise ValueError("слои модели разъехались")

        monkeypatch.setattr(agreement, "load_models", lambda directory: (FakeMorph(), FakeSyntax()))
        monkeypatch.setattr(agreement, "parse_sentence", explode)
        detect = build_layer(analyzer(), Path("/nonexistent"))
        assert detect("Указанная работы выполнены") == []
        assert "Разбор строки не удался" in caplog.text

    def test_missing_weights_are_reported_on_build(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Не найдены веса"):
            build_layer(analyzer(), tmp_path)


@dataclass
class FakeSpan:
    """Токен с позицией — то же, что отдаёт razdel."""

    text: str
    start: int
    stop: int


def fake_tokenize(text: str) -> Iterator[FakeSpan]:
    """Токенизатор без razdel: делит по пробелам, считая позиции."""
    position = 0
    for chunk in text.split(" "):
        if chunk:
            yield FakeSpan(text=chunk, start=position, stop=position + len(chunk))
        position += len(chunk) + 1


class FakeMorph:
    """Морфология без весов: всем словам один и тот же разбор."""

    def map(self, sentences):
        for words in sentences:
            yield SimpleNamespace(
                tokens=[SimpleNamespace(feats={"Number": "Plur"}) for _ in words],
            )


class FakeSyntax:
    """Синтаксис без весов: первое слово — определение ко второму."""

    def __init__(self, head: str = "2"):
        self.head = head

    def map(self, sentences):
        for words in sentences:
            yield SimpleNamespace(
                tokens=[
                    SimpleNamespace(
                        id=str(position + 1),
                        head_id=self.head if position == 0 else "0",
                        rel="amod" if position == 0 else "root",
                    )
                    for position, _ in enumerate(words)
                ],
            )
