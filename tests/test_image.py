from pathlib import Path
from shutil import copyfile

from PIL import Image

from barda.image import COVER_WIDTH, CREATOR_WIDTH, RESOURCE_WIDTH, CVImage

TEST_COVER = Path("tests/test_files/cover.jpg")
TEST_CREATOR = Path("tests/test_files/creator-rectangle.jpg")
TEST_RESOURCE = Path("tests/test_files/resource-wide.jpg")
TEST_CONVERT = Path("tests/test_files/test_convert.png")
PHIL_FILE = Path("tests/test_files/phil.jpg")


def get_image_width(img: Path) -> int:
    i = Image.open(img)
    w, _ = i.size
    return w


def test_cover_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_COVER, test_file)
    assert get_image_width(TEST_COVER) == 1665
    img = CVImage(test_file)
    img.resize_cover()
    assert get_image_width(test_file) == COVER_WIDTH


def test_creator_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_CREATOR, test_file)
    assert get_image_width(TEST_CREATOR) == 541
    img = CVImage(test_file)
    img.resize_creator()
    assert get_image_width(test_file) == CREATOR_WIDTH


def test_phil_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(PHIL_FILE, test_file)
    assert get_image_width(test_file) == 202
    img = CVImage(test_file)
    img.resize_creator()
    assert get_image_width(test_file) == CREATOR_WIDTH


def test_resource_resize(tmp_path: Path) -> None:
    test_file = tmp_path / "test.jpg"
    copyfile(TEST_RESOURCE, test_file)
    assert get_image_width(TEST_RESOURCE) == 916
    img = CVImage(test_file)
    img.resize_resource()
    assert get_image_width(test_file) == RESOURCE_WIDTH


def test_convert_resource(tmp_path: Path) -> None:
    test_file = tmp_path / "test.png"
    copyfile(TEST_CONVERT, test_file)
    img = CVImage(test_file)
    img.resize_resource()
    assert get_image_width(test_file) == RESOURCE_WIDTH
