import pytest

from barda.import_series import ImportSeries
from barda.settings import BardaSettings

test_data = [
    pytest.param(1928456, "No Stories", 0),
    pytest.param(246553, "One Story", 1),
    pytest.param(293, "Nine Stories", 9),
]


@pytest.mark.parametrize("comic,reason,expected", test_data)
def test_gcd_stories(comic: int, reason: str, expected: int, tmpdir):
    test_settings = BardaSettings(config_dir=tmpdir)
    IS = ImportSeries(test_settings)
    stories = IS._get_gcd_stories(comic)
    assert isinstance(stories, list)
    assert len(stories) == expected
