import pytest

from barda.importer_comic_vine import ComicVineImporter
from barda.settings import BardaSettings

test_data = [
    pytest.param(1928456, "No Stories", 0),
    pytest.param(246553, "One Story", 1),
    pytest.param(293, "Nine Stories", 9),
]


@pytest.mark.parametrize("comic,reason,expected", test_data)
def test_gcd_stories(comic: int, reason: str, expected: int, tmpdir):
    test_settings = BardaSettings(config_dir=tmpdir)
    IS = ComicVineImporter(test_settings)
    stories = IS._get_gcd_stories(comic)
    assert isinstance(stories, list)
    assert len(stories) == expected


# def test_gcd_reprints_lst(tmpdir) -> None:
#     expected_result = [
#         {"series": "Golden Age Starman Archives", "number": 1, "year_began": 2000},
#         {"series": "The New Gods", "number": 6, "year_began": 1971},
#         {"series": "Adventure Comics", "number": 499, "year_began": 1938},
#         {"series": "The Forever People", "number": 6, "year_began": 1971},
#     ]
#     test_settings = BardaSettings(config_dir=tmpdir)
#     cvi = ComicVineImporter(test_settings)
#     results = cvi.get_gcd_reprints(2240)
#     assert results == expected_result
