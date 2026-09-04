"""Тесты доменного словаря: сборка из фраз, чтение из файла, фильтрация."""

from __future__ import annotations

import json

import pytest

from ruspell.models import Issue
from ruspell.vocabulary import (
    drop_vocabulary_words,
    in_vocabulary,
    load_vocabulary,
    vocabulary_words,
)


def issue(word: str) -> Issue:
    return Issue(word=word, start=0, end=len(word), category="SPELL", suggestions=("другое",))


class TestVocabularyWords:
    def test_abbreviation_and_its_expansion_become_vocabulary(self):
        words = vocabulary_words(["ФТП", "Фондтехпроект северного округа"])
        assert words == frozenset({"фтп", "фондтехпроект", "северного", "округа"})

    def test_plain_word_list_works_as_well(self):
        assert vocabulary_words(["Техрегламент", "ОКВЭД"]) == frozenset({"техрегламент", "оквэд"})

    def test_punctuation_and_digits_are_not_words(self):
        assert vocabulary_words(["ГОСТ 34.003-90 (изм. 1)"]) == frozenset({"гост", "изм"})

    def test_empty_input_gives_empty_vocabulary(self):
        assert vocabulary_words([]) == frozenset()

    def test_hyphenated_term_becomes_its_parts(self):
        # Так же режется и текст, поэтому «машино-мест» в письме совпадёт со
        # словарём по обеим половинам — отдельного разбора дефиса не нужно.
        assert vocabulary_words(["машино-мест"]) == frozenset({"машино", "мест"})

    def test_a_bare_string_is_rejected(self):
        # Строка — тоже Iterable[str], и без проверки словарь молча стал бы
        # набором отдельных букв.
        with pytest.raises(TypeError, match="коллекция строк"):
            vocabulary_words("оквэд")


class TestLoadVocabulary:
    def test_reads_list_of_strings(self, tmp_path):
        path = tmp_path / "vocabulary.json"
        path.write_text(json.dumps(["ФТП", "Фондтехпроект"]), encoding="utf-8")
        assert load_vocabulary(path) == frozenset({"фтп", "фондтехпроект"})

    def test_accepts_a_plain_string_path(self, tmp_path):
        path = tmp_path / "vocabulary.json"
        path.write_text(json.dumps(["ФТП"]), encoding="utf-8")
        assert load_vocabulary(str(path)) == frozenset({"фтп"})

    def test_rejects_anything_but_a_list_of_strings(self, tmp_path):
        path = tmp_path / "vocabulary.json"
        path.write_text(json.dumps({"слова": ["фтп"]}), encoding="utf-8")
        with pytest.raises(ValueError, match="список строк"):
            load_vocabulary(path)


class TestInVocabulary:
    def test_known_word_is_domain(self):
        assert in_vocabulary("Фондтехпроект", frozenset({"фондтехпроект"}))

    def test_word_is_matched_case_insensitively(self):
        assert in_vocabulary("  ОКВЭД  ", frozenset({"оквэд"}))

    def test_unknown_word_is_not_domain(self):
        assert not in_vocabulary("предложния", frozenset({"техрегламент"}))

    def test_empty_word_is_not_domain(self):
        assert not in_vocabulary("   ", frozenset({"техрегламент"}))


class TestDropVocabularyWords:
    def test_domain_word_is_dropped(self):
        assert drop_vocabulary_words([issue("Фондтехпроект")], frozenset({"фондтехпроект"})) == []

    def test_expansion_word_is_no_longer_flagged(self):
        vocabulary = vocabulary_words(["ФТП", "Фондтехпроект"])
        assert drop_vocabulary_words([issue("Фондтехпроект")], vocabulary) == []

    def test_real_error_survives(self):
        assert len(drop_vocabulary_words([issue("предложния")], frozenset({"фтп"}))) == 1

    def test_empty_vocabulary_drops_nothing(self):
        assert len(drop_vocabulary_words([issue("Фондтехпроект")], frozenset())) == 1
