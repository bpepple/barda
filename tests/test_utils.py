import pytest

from barda.utils import fix_story_chapters

test_stories = [
    pytest.param("Devil in the Sand Part One", "Missing comma", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand,Part One", "Missing space", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand, Part One", "Correct entry", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand", "Nothing to fix", "Devil in the Sand"),
    pytest.param("On the Ground - Part 1", "Hyphen instead of comma", "On the Ground, Part 1"),
]


@pytest.mark.parametrize("story, reason, expected", test_stories)
def test_fix_story_chapters(story: str, reason: str, expected: str) -> None:
    assert fix_story_chapters(story) == expected
