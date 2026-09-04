"""Тесты словарного слоя: правки, ранжирование, сборка слоя."""

from __future__ import annotations

from pathlib import Path

from ruspell.dictionary import (
    MIN_FREQUENCY_ENTRIES,
    build_layer,
    edits1,
    frequency_ranker,
    get_morph_analyzer,
    rank_suggestions,
)
from ruspell.vocabulary import vocabulary_words


class TestEdits1:
    def test_contains_the_intended_correction(self):
        assert "плана" in edits1("плона")

    def test_contains_insertion_deletion_and_transposition(self):
        variants = edits1("код")
        assert {"кода", "од", "окд"} <= variants

    def test_yo_is_reachable(self):
        assert "ещё" in edits1("ещо")

    def test_word_itself_is_among_variants(self):
        assert "план" in edits1("план")


class TestRankSuggestions:
    def test_prefers_same_first_and_last_letter(self):
        assert rank_suggestions("плона", {"плана", "клона", "плоно"})[0] == "плана"

    def test_prefers_same_length(self):
        ranked = rank_suggestions("работв", {"работа", "работ"})
        assert ranked[0] == "работа"

    def test_empty_candidates_give_empty_result(self):
        assert rank_suggestions("плона", set()) == []


def write_dictionary(path: Path, *lines: str) -> Path:
    """Пишет частотный словарь: значимые строки плюс наполнитель до порога.

    Ранжирование отказывается работать по неправдоподобно короткому файлу, так
    что фикстура обязана выглядеть как словарь, а не как обрывок.
    """
    filler = [f"слово{number} 1" for number in range(MIN_FREQUENCY_ENTRIES)]
    path.write_text("\n".join([*lines, *filler]) + "\n", encoding="utf-8")
    return path


class TestFrequencyRanker:
    def test_prefers_the_common_word(self, tmp_path):
        path = write_dictionary(tmp_path / "ru_full.txt", "предложения 5000", "предложная 3")
        rank = frequency_ranker(path)
        assert rank is not None
        assert rank("предложния", {"предложная", "предложения"}) == ["предложения", "предложная"]

    def test_missing_file_gives_no_ranker(self, tmp_path):
        assert frequency_ranker(tmp_path / "absent.txt") is None

    def test_implausibly_short_file_gives_no_ranker(self, tmp_path, caplog):
        # Оборванная закачка непуста и читается: без порога ранжирование стало
        # бы алфавитным — молча и хуже документированного отката.
        path = tmp_path / "ru_full.txt"
        path.write_text("предложения 5000\n", encoding="utf-8")
        assert frequency_ranker(path) is None
        assert "оборванную закачку" in caplog.text

    def test_broken_lines_are_skipped(self, tmp_path):
        path = write_dictionary(
            tmp_path / "ru_full.txt",
            "предложения 5000",
            "мусор",
            "",
            "план x",
        )
        rank = frequency_ranker(path)
        assert rank is not None
        assert rank("плана", {"план", "предложения"}) == ["предложения", "план"]


class TestBuildLayer:
    def test_typo_is_found_and_ranked(self):
        detect = build_layer(frozenset(), get_morph_analyzer(), rank_suggestions)
        issues = detect("Направляем предложния.")
        assert [issue.word for issue in issues] == ["предложния"]
        assert "предложения" in issues[0].suggestions

    def test_correct_text_gives_no_issues(self):
        detect = build_layer(frozenset(), get_morph_analyzer(), rank_suggestions)
        assert detect("Направляем предложения по существу вопроса.") == []

    def test_vocabulary_word_is_not_reported(self):
        analyzer = get_morph_analyzer()
        text = "Выделено 120 машино-мест."
        assert detect_words(text, analyzer) == ["машино"]
        detect = build_layer(vocabulary_words(["машино-мест"]), analyzer, rank_suggestions)
        assert detect(text) == []


def detect_words(text: str, analyzer) -> list[str]:
    detect = build_layer(frozenset(), analyzer, rank_suggestions)
    return [issue.word for issue in detect(text)]
