from enum import Enum, auto, unique
from pathlib import Path

from PIL import Image

COVER_WIDTH = 600
RESOURCE_WIDTH = 320
CREATOR_WIDTH = 256  # Also the height


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
        i.close()
        if width == height:
            return ImageShape.Square
        elif width > height:
            return ImageShape.Wide
        elif height > width:
            return ImageShape.Tall
        else:
            return None

    def resize_cover(self) -> None:  # sourcery skip: class-extract-method
        if self._determine_shape() is not ImageShape.Tall:
            # Cover needs to be cropped
            return
        i = Image.open(self.image)
        w, h = i.size
        if w == COVER_WIDTH:
            # No need to resize
            return
        wpercent = COVER_WIDTH / float(w)
        hsize = int(float(h) * float(wpercent))
        i = i.resize((COVER_WIDTH, hsize), Image.Resampling.LANCZOS)
        i.save(self.image)
        i.close()

    def resize_creator(self) -> None:  # sourcery skip: extract-duplicate-method
        left = top = 0
        shape = self._determine_shape()
        i = Image.open(self.image)
        w, h = i.size
        match shape:
            case ImageShape.Square:
                if w != CREATOR_WIDTH:
                    i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                    i.save(self.image)
                    i.close()
            case ImageShape.Tall:
                i = i.crop((left, top, w, w))
                i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                i.save(self.image)
                i.close()
            case ImageShape.Wide:
                # TODO: Need to center crop this
                i = i.crop((top, left, h, h))
                i = i.resize((CREATOR_WIDTH, CREATOR_WIDTH), Image.Resampling.LANCZOS)
                i.save(self.image)
                i.close()
            case _:
                i.close()
                return

    def resize_resource(self) -> None:  # sourcery skip: extract-duplicate-method, extract-method
        shape = self._determine_shape()
        i = Image.open(self.image)
        w, h = i.size
        top = 0
        match shape:
            case ImageShape.Tall:
                wpercent = RESOURCE_WIDTH / float(w)
                hsize = int(float(h) * float(wpercent))
                i = i.resize((RESOURCE_WIDTH, hsize), Image.Resampling.LANCZOS)
                i.save(self.image)
                i.close()
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
                i.close()
            case _:
                i.close()
                return
