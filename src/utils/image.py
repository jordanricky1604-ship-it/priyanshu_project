import io
import base64
from typing import Optional, Union

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def decode_image(data: Union[bytes, str]) -> Image.Image:
    if isinstance(data, str):
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)
    return Image.open(io.BytesIO(data))


def pil_to_numpy(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=5)
    img = img.filter(ImageFilter.MedianFilter(3))
    img = img.filter(ImageFilter.SHARPEN)
    return img


def crop_to_square_center(img: Image.Image, size: int = 224) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)
