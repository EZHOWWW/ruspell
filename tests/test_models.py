"""Тесты контракта замечания."""

from __future__ import annotations

import dataclasses
import json

import pytest

from ruspell.models import Issue


def issue() -> Issue:
    return Issue(
        word="Указанная",
        start=0,
        end=9,
        category="AGREEMENT",
        suggestions=("Указанные",),
        message="Не согласовано с «работы» по признакам: Number",
    )


class TestIssue:
    def test_suggestions_and_message_are_optional(self):
        bare = Issue(word="слово", start=0, end=5, category="SPELL")
        assert bare.suggestions == ()
        assert bare.message == ""

    def test_issue_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(issue(), "word", "другое")

    def test_issues_with_the_same_fields_are_equal(self):
        assert issue() == issue()


class TestAsDict:
    def test_all_fields_are_serialised(self):
        assert issue().as_dict() == {
            "word": "Указанная",
            "start": 0,
            "end": 9,
            "category": "AGREEMENT",
            "suggestions": ["Указанные"],
            "message": "Не согласовано с «работы» по признакам: Number",
        }

    def test_suggestions_become_a_list(self):
        assert isinstance(issue().as_dict()["suggestions"], list)

    def test_result_is_json_serialisable(self):
        assert json.loads(json.dumps(issue().as_dict()))["word"] == "Указанная"
