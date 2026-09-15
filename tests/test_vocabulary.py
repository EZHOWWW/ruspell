"""Тесты доменного словаря: сборка из фраз и чтение из файла."""

from __future__ import annotations

import json

import pytest

from ruspell.vocabulary import load_vocabulary, vocabulary_words


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

    def test_words_are_normalized_like_the_text(self):
        assert vocabulary_words(["Гос\u00adэкспертиза"]) == frozenset({"госэкспертиза"})

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
