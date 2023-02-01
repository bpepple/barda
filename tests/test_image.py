from pathlib import Path
from shutil import copyfile

from PIL import Image

from barda.image import COVER_WIDTH, CREATOR_WIDTH, RESOURCE_WIDTH, CVImage

TEST_COVER = Path("tests/test_files/cover.jpg")
TEST_CREATOR = Path("tests/test_files/creator-rectangle.jpg")
TEST_RESOURCE = Path("tests/test_files/resource-wide.jpg")


def _check_cover_size(img: Path, correct_size: int) -> None:
    i = Image.open(img)
    w, _ = i.size
    assert w == correct_size


def test_cover_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_COVER, test_file)
    _check_cover_size(TEST_COVER, 1665)
    img = CVImage(test_file)
    img.resize_cover()
    _check_cover_size(test_file, COVER_WIDTH)


def test_creator_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_CREATOR, test_file)
    _check_cover_size(TEST_CREATOR, 541)
    img = CVImage(test_file)
    img.resize_creator()
    _check_cover_size(test_file, CREATOR_WIDTH)


def test_resource_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_RESOURCE, test_file)
    _check_cover_size(TEST_RESOURCE, 916)
    img = CVImage(test_file)
    img.resize_resource()
    _check_cover_size(test_file, RESOURCE_WIDTH)
