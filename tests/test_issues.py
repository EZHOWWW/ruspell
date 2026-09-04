"""Тесты чистой логики: поиск, слияние, свёртка и применение замечаний.

Словарь подставной: ни pymorphy3, ни slovnet, ни файлов моделей — тесты
быстрые и не зависят от окружения.
"""

from __future__ import annotations

from ruspell.issues import (
    apply_issues,
    collapse_repeats,
    find_dictionary_issues,
    merge_issues,
    near_initials,
    shift,
)
from ruspell.models import Issue, IssueCategory

KNOWN = frozenset({"плана", "предложения", "приложения", "работа", "работ", "документ"})


def is_known(word: str) -> bool:
    return word in KNOWN


def suggest(word: str) -> list[str]:
    return {"предложния": ["предложения"], "работв": ["работа", "работ"]}.get(word, [])


def issue(word, start, end, *suggestions, category: IssueCategory = "SPELL") -> Issue:
    return Issue(
        word=word,
        start=start,
        end=end,
        category=category,
        suggestions=tuple(suggestions),
    )


class TestFindDictionaryIssues:
    def test_finds_unknown_word_with_suggestion(self):
        issues = find_dictionary_issues("направляем предложния", is_known, suggest)
        assert [(i.word, i.start, i.end, i.suggestions) for i in issues] == [
            ("предложния", 11, 21, ("предложения",)),
        ]

    def test_span_points_at_the_word(self):
        text = "направляем предложния"
        found = find_dictionary_issues(text, is_known, suggest)[0]
        assert text[found.start : found.end] == found.word

    def test_known_word_is_not_reported(self):
        assert find_dictionary_issues("направляем предложения", is_known, suggest) == []

    def test_word_without_suggestions_is_skipped(self):
        assert find_dictionary_issues("направляем бламбурда", is_known, suggest) == []

    def test_short_words_and_acronyms_are_skipped(self):
        assert find_dictionary_issues("ФТП про ннн", is_known, suggest) == []

    def test_every_occurrence_is_reported(self):
        issues = find_dictionary_issues("предложния и предложния", is_known, suggest)
        assert [(i.start, i.end) for i in issues] == [(0, 10), (13, 23)]

    def test_capitalised_word_gets_capitalised_suggestions(self):
        issues = find_dictionary_issues("Предложния направлены", is_known, suggest)
        assert issues[0].suggestions == ("Предложения",)

    def test_category_is_spell(self):
        issues = find_dictionary_issues("направляем предложния", is_known, suggest)
        assert issues[0].category == "SPELL"


class TestNearInitials:
    def test_word_after_initials_is_not_reported(self):
        assert find_dictionary_issues("Заместителю А.Б. предложния", is_known, suggest) == []

    def test_word_before_initials_is_not_reported(self):
        assert find_dictionary_issues("В адрес предложния А.Б.", is_known, suggest) == []

    def test_plain_typo_is_still_reported(self):
        issues = find_dictionary_issues("Направляем предложния", is_known, suggest)
        assert [i.word for i in issues] == ["предложния"]

    def test_initial_further_away_does_not_shield(self):
        assert near_initials("А.Б. слово прочее предложния", 18, 28) is False

    def test_single_initial_is_enough(self):
        assert near_initials("Ветровин А. подписал", 0, 8) is True


class TestShift:
    def test_span_moves_by_offset(self):
        moved = shift(issue("работв", 0, 6, "работа"), 20)
        assert (moved.start, moved.end) == (20, 26)

    def test_everything_else_survives(self):
        moved = shift(issue("работв", 0, 6, "работа"), 20)
        assert (moved.word, moved.category, moved.suggestions) == ("работв", "SPELL", ("работа",))


class TestCollapseRepeats:
    def test_repeated_typo_becomes_one_issue(self):
        issues = [
            issue("предложния", 0, 10, "предложения"),
            issue("предложния", 13, 23, "предложения"),
        ]
        assert [i.start for i in collapse_repeats(issues)] == [0]

    def test_case_does_not_make_a_second_issue(self):
        issues = [
            issue("Предложния", 0, 10, "Предложения"),
            issue("предложния", 13, 23, "предложения"),
        ]
        assert len(collapse_repeats(issues)) == 1

    def test_agreement_repeats_are_kept(self):
        issues = [
            issue("указанная", 0, 9, "указанные", category="AGREEMENT"),
            issue("указанная", 20, 29, "указанной", category="AGREEMENT"),
        ]
        assert len(collapse_repeats(issues)) == 2

    def test_different_words_are_all_kept(self):
        issues = [issue("предложния", 0, 10, "предложения"), issue("работв", 13, 19, "работа")]
        assert len(collapse_repeats(issues)) == 2


class TestMergeIssues:
    def test_earlier_layer_wins_on_overlap(self):
        first = [issue("приказа", 9, 16, "приказу", category="AGREEMENT")]
        second = [issue("Согласно приказа", 0, 16, "Согласно приказу")]
        assert [i.word for i in merge_issues([first, second])] == ["приказа"]

    def test_non_overlapping_issues_are_all_kept(self):
        first = [issue("перв", 0, 4, "первый")]
        second = [issue("втор", 10, 14, "второй")]
        assert len(merge_issues([first, second])) == 2

    def test_result_is_sorted_by_position(self):
        first = [issue("поздн", 20, 25, "поздний")]
        second = [issue("ранн", 0, 4, "ранний")]
        assert [i.start for i in merge_issues([first, second])] == [0, 20]

    def test_touching_spans_do_not_count_as_overlap(self):
        first = [issue("перв", 0, 4, "первый")]
        second = [issue("втор", 4, 8, "второй")]
        assert len(merge_issues([first, second])) == 2

    def test_no_layers_give_no_issues(self):
        assert merge_issues([]) == []


class TestApplyIssues:
    def test_applies_first_suggestion(self):
        text = "направляем предложния"
        assert apply_issues(text, [issue("предложния", 11, 21, "предложения")]) == (
            "направляем предложения"
        )

    def test_issue_without_suggestions_leaves_text_alone(self):
        text = "направляем предложния"
        assert apply_issues(text, [issue("предложния", 11, 21)]) == text

    def test_overlapping_issue_is_ignored(self):
        text = "Согласно приказа"
        issues = [
            issue("Согласно приказа", 0, 16, "Согласно приказу"),
            issue("приказа", 9, 16, "приказу"),
        ]
        assert apply_issues(text, issues) == "Согласно приказу"

    def test_several_issues_are_applied_left_to_right(self):
        text = "предложния и работв"
        issues = [issue("предложния", 0, 10, "предложения"), issue("работв", 13, 19, "работа")]
        assert apply_issues(text, issues) == "предложения и работа"

    def test_empty_issue_list_returns_the_same_text(self):
        assert apply_issues("текст без ошибок", []) == "текст без ошибок"
