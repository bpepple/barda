import pytest

from barda.utils import clean_search_series_title, fix_story_chapters, clean_desc

test_stories = [
    pytest.param("Devil in the Sand Part One", "Missing comma", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand,Part One", "Missing space", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand, Part One", "Correct entry", "Devil in the Sand, Part One"),
    pytest.param("Devil in the Sand", "Nothing to fix", "Devil in the Sand"),
    pytest.param("On the Ground - Part 1", "Hyphen instead of comma", "On the Ground, Part 1"),
    # pytest.param(
    #     "The Bat-Man of Gotham: Part Two", "Semi-colon separator", "The Bat-Man of Gotham: Part Two"
    # ),
]


@pytest.mark.parametrize("story, reason, expected", test_stories)
def test_fix_story_chapters(story: str, reason: str, expected: str) -> None:
    assert fix_story_chapters(story) == expected


test_titles = [
    pytest.param("The Batman", "Title starting with 'the'", "batman"),
    pytest.param("Batman / Superman", "Title with space+backslash+space", "batman/superman"),
    # pytest.param("Batman and Outsiders", "Title with 'and'", "batman outsiders"),
    # pytest.param("Batman & Outsiders", "Title with '&'", "batman outsiders"),
]


@pytest.mark.parametrize("title, reason, expected", test_titles)
def test_clean_search_series_title(title: str, reason: str, expected: str) -> None:
    assert clean_search_series_title(title) == expected


test_desc = [
    pytest.param("Welcome to Riverdale\n\nContentsLead 'em", "regular bad content", "Welcome to Riverdale"),
    pytest.param("", "empty string", ""),
    pytest.param("ContentsLead 'em", "string starting with 'content'", "")
]


@pytest.mark.parametrize("txt, reason, expected", test_desc)
def test_clean_desc(txt: str, reason: str, expected: str) -> None:
    assert clean_desc(txt) == expected
