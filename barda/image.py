import logging
from enum import Enum, auto, unique
from pathlib import Path

from PIL import Image

COVER_WIDTH = 600
RESOURCE_WIDTH = 320
CREATOR_WIDTH = 256  # Also the height

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
handler = logging.FileHandler("barda.log")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)


@unique
class ImageShape(Enum):
    Square = auto()
    Wide = auto()
    Tall = auto()


class CVImage:
    def __init__(self, img: Path) -> None:
        self.image = img

    def _determine_shape(self) -> ImageShape | None:
        i = Image.open(self.image)
        width, height = i.size

        if width == height:
            return ImageShape.Square
        elif width > height:
            return ImageShape.Wide
        elif height > width:
            return ImageShape.Tall
        else:
            return None

    def _convert_to_rgb(self) -> None:
        LOGGER.debug("Entering covert_to_rgb()...")
        with Image.open(self.image) as img:
            mode = img.mode
            LOGGER.debug(f"Image '{self.image.name}' mode is '{mode}'.")
            if mode in ("RGBA", "P"):
                img = img.convert("RGB")
                img.save(self.image)
        LOGGER.debug("Exiting convert_to_rbg()...")

    def resize_cover(self) -> None:  # sourcery skip: class-extract-method
        if self._determine_shape() is not ImageShape.Tall:
            # Cover needs to be cropped
            return
        self._convert_to_rgb()
        with Image.open(self.image) as i:
            w, h = i.size
            if w == COVER_WIDTH:
                # No need to resize
                return
            wpercent = COVER_WIDTH / float(w)
            hsize = int(float(h) * float(wpercent))
            i = i.resize((COVER_WIDTH, hsize), Image.Resampling.LANCZOS)
            i.save(self.image)

    def resize_creator(self) -> None:  # sourcery skip: extract-duplicate-method
        LOGGER.debug("Entering resize_creator()...")
        left = top = 0
        self._convert_to_rgb()
        shape = self._determine_shape()

        with Image.open(self.image) as i:
            w, h = i.size
            LOGGER.debug(f"'{self.image.name}' - shape: {shape}, width: {w}, height: {h}.")
            match shape:
                case ImageShape.Square:
                    if w != CREATOR_WIDTH:
                        i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                        i.save(self.image)
                case ImageShape.Tall:
                    i = i.crop((left, top, w, w))
                    i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                    i.save(self.image)
                case ImageShape.Wide:
                    # TODO: Need to center crop this
                    i = i.crop((top, left, h, h))
                    i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                    i.save(self.image)
                case _:
                    return

        LOGGER.debug("Exiting resize_creator()...")

    def resize_resource(self) -> None:  # sourcery skip: extract-duplicate-method, extract-method
        shape = self._determine_shape()
        self._convert_to_rgb()
        with Image.open(self.image) as i:
            w, h = i.size
            top = 0
            match shape:
                case ImageShape.Tall:
                    wpercent = RESOURCE_WIDTH / float(w)
                    hsize = int(float(h) * float(wpercent))
                    i = i.resize((RESOURCE_WIDTH, hsize), Image.Resampling.LANCZOS)
                    i.save(self.image)
                case ImageShape.Wide | ImageShape.Square:
                    crop_width = int(float(h) / float(3) * float(2))
                    diff = w - crop_width
                    left = int(diff / 2)
                    right = left + crop_width
                    i = i.crop((left, top, right, h))
                    new_w, _ = i.size
                    wpercent = RESOURCE_WIDTH / float(new_w)
                    hsize = int(float(h) * float(wpercent))
                    i = i.resize((RESOURCE_WIDTH, hsize), Image.Resampling.LANCZOS)
                    i.save(self.image)
                case _:
                    return
