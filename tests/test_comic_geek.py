import pytest

from barda.importer_comic_geek import GeeksImporter
from barda.settings import BardaSettings

test_var_name = [
    pytest.param(
        "The Amazing Spider-Man #39 Joel Mandish Tactical Suit Marvel's Spider-Man 2 Variant",
        "Regular variant name",
        "Joel Mandish Tactical Suit Marvel's Spider-Man 2 Variant",
    ),
    pytest.param(
        "Superman '78: The Metal Curtain #2 Cover B Michael Cho Card Stock Variant",
        "DC Comic",
        "Cover B Michael Cho Variant",
    ),
]


@pytest.mark.parametrize("name, reason, expected", test_var_name)
def test_logc_variant_name(name: str, reason: str, expected: str) -> None:
    barda_settings = BardaSettings()
    locg = GeeksImporter(barda_settings)
    result = locg._variant_name(name)
    assert result == expected
