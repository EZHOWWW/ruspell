"""Тесты обхода текста и сборки слоёв.

Слои подставные: обход текста — чистая логика, и проверять её на настоящих
моделях незачем.
"""

from __future__ import annotations

from ruspell.check import build_layers, check_text
from ruspell.dictionary import get_morph_analyzer
from ruspell.issues import WORD_RE, Detector
from ruspell.models import Issue, IssueCategory


def layer_for(word: str, replacement: str, category: IssueCategory = "SPELL") -> Detector:
    """Слой, флагующий каждое вхождение *word* в строке."""

    def detect(text: str) -> list[Issue]:
        return [
            Issue(
                word=match.group(),
                start=match.start(),
                end=match.end(),
                category=category,
                suggestions=(replacement,),
            )
            for match in WORD_RE.finditer(text)
            if match.group().lower() == word
        ]

    return detect


class TestCheckText:
    def test_spans_are_global(self):
        text = "первая строка\nвторая работв строка"
        issues = check_text(text, {"stub": layer_for("работв", "работа")})
        assert [(issue.start, issue.end) for issue in issues] == [(21, 27)]
        assert text[issues[0].start : issues[0].end] == "работв"

    def test_every_line_is_checked(self):
        text = "работв\nработв\nработв"
        assert len(check_text(text, {"stub": layer_for("работв", "работа")})) == 3

    def test_repeats_are_not_collapsed(self):
        text = "работв и работв"
        assert len(check_text(text, {"stub": layer_for("работв", "работа")})) == 2

    def test_windows_line_endings_do_not_shift_spans(self):
        text = "первая\r\nработв"
        issue = check_text(text, {"stub": layer_for("работв", "работа")})[0]
        assert text[issue.start : issue.end] == "работв"

    def test_layers_are_merged_in_order_of_trust(self):
        layers = {
            "first": layer_for("работв", "работа"),
            "second": layer_for("работв", "работы", category="AGREEMENT"),
        }
        issues = check_text("работв", layers)
        assert [issue.suggestions for issue in issues] == [("работа",)]

    def test_no_layers_give_no_issues(self):
        assert check_text("любой текст", {}) == []

    def test_empty_text_gives_no_issues(self):
        assert check_text("", {"stub": layer_for("работв", "работа")}) == []


class TestBuildLayers:
    def test_dictionary_layer_is_always_there(self, tmp_path):
        layers = build_layers(frozenset(), tmp_path, get_morph_analyzer())
        assert "dictionary" in layers

    def test_agreement_degrades_without_weights(self, tmp_path, caplog):
        layers = build_layers(frozenset(), tmp_path / "absent", get_morph_analyzer())
        assert tuple(layers) == ("dictionary",)
        assert "согласования" in caplog.text

    def test_dictionary_layer_works_without_weights(self, tmp_path):
        layers = build_layers(frozenset(), tmp_path / "absent", get_morph_analyzer())
        assert [issue.word for issue in check_text("Направляем предложния.", layers)] == [
            "предложния",
        ]
