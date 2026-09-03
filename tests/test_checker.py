"""Тесты публичного API.

Проверки, требующие весов и экстры ``agreement``, пропускаются, если весов нет:
без них поднимается только словарный слой, и это документированное поведение,
а не поломка.
"""

from __future__ import annotations

import pytest

from ruspell import Issue, SpellChecker, load_vocabulary
from ruspell.weights import default_weights_dir, missing_weights

WEIGHTS_DIR = default_weights_dir()
needs_weights = pytest.mark.skipif(
    bool(missing_weights(WEIGHTS_DIR)),
    reason=f"нет весов slovnet в {WEIGHTS_DIR}: `ruspell-weights download`",
)


@pytest.fixture(scope="module")
def checker() -> SpellChecker:
    return SpellChecker(vocabulary=["ФТП", "Фондтехпроект северного округа"])


class TestCheck:
    def test_typo_is_found(self, checker):
        issues = checker.check("Направляем предложния по существу вопроса.")
        assert [(issue.word, issue.category) for issue in issues] == [("предложния", "SPELL")]

    def test_span_points_at_the_word(self, checker):
        text = "Направляем предложния."
        issue = checker.check(text)[0]
        assert text[issue.start : issue.end] == issue.word

    def test_correct_text_gives_no_issues(self, checker):
        assert checker.check("Направляем предложения по существу вопроса.") == []

    def test_repeated_typo_is_reported_once(self, checker):
        issues = checker.check("Направляем предложния и ещё раз предложния.")
        assert len(issues) == 1

    def test_issues_are_sorted_by_position(self, checker):
        issues = checker.check("Первая строка с ошиибкой.\nВторая строка с опечткой.")
        assert [issue.start for issue in issues] == sorted(issue.start for issue in issues)

    def test_vocabulary_word_is_not_reported(self):
        text = "Выделено 120 машино-мест."
        assert SpellChecker().check(text)[0].word == "машино"
        assert SpellChecker(vocabulary=["машино-мест"]).check(text) == []

    def test_vocabulary_from_file(self, tmp_path):
        path = tmp_path / "vocabulary.json"
        path.write_text('["машино-мест"]', encoding="utf-8")
        assert SpellChecker(vocabulary=load_vocabulary(path)).check("120 машино-мест") == []

    def test_result_is_a_list_of_issues(self, checker):
        assert all(isinstance(issue, Issue) for issue in checker.check("Направляем предложния."))


class TestCorrect:
    def test_every_occurrence_is_fixed(self, checker):
        assert checker.correct("Уведомлеие и уведомлеие.") == "Уведомление и уведомление."

    def test_text_without_errors_is_unchanged(self, checker):
        text = "Направляем предложения по существу вопроса."
        assert checker.correct(text) == text

    def test_line_breaks_survive(self, checker):
        assert checker.correct("Первая строка.\nУведомлеие.") == "Первая строка.\nУведомление."


class TestLayers:
    def test_dictionary_layer_is_always_there(self, checker):
        assert "dictionary" in checker.layers

    def test_weights_dir_is_visible(self, tmp_path):
        assert SpellChecker(weights_dir=tmp_path).weights_dir == tmp_path

    def test_without_weights_only_the_dictionary_layer(self, tmp_path):
        assert SpellChecker(weights_dir=tmp_path / "absent").layers == ("dictionary",)

    def test_check_still_works_without_weights(self, tmp_path):
        checker = SpellChecker(weights_dir=tmp_path / "absent")
        assert [issue.word for issue in checker.check("Направляем предложния.")] == ["предложния"]


@needs_weights
class TestAgreement:
    def test_agreement_layer_is_up(self, checker):
        assert checker.layers == ("dictionary", "agreement")

    def test_disagreeing_definition_is_reported(self, checker):
        issues = checker.check("Указанная работы выполнены в срок.")
        assert [(issue.word, issue.category) for issue in issues] == [("Указанная", "AGREEMENT")]
        assert "Указанные" in issues[0].suggestions

    def test_preposition_government_is_reported(self, checker):
        issues = checker.check("Работы выполнены согласно приказа.")
        assert [(issue.word, issue.category) for issue in issues] == [("приказа", "AGREEMENT")]
        assert "приказу" in issues[0].suggestions

    def test_agreement_is_applied_to_the_corrected_text(self, checker):
        assert checker.correct("Указанная работы выполнены согласно приказа.") == (
            "Указанные работы выполнены согласно приказу."
        )

    def test_correct_sentence_is_left_alone(self, checker):
        assert checker.check("Указанные работы выполнены согласно приказу.") == []
