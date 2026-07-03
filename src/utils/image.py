import io
import base64
from typing import Optional, Union

import numpy as np
from PIL import Image, ImageFilter, ImageOps
import cv2


def decode_image(data: Union[bytes, str]) -> Image.Image:
    if isinstance(data, str):
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)
    return Image.open(io.BytesIO(data))


def pil_to_numpy(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    # 1. Convert PIL image to OpenCV (numpy array)
    img_np = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    
    # 2. Denoising (Non-Local Means)
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    
    # 3. Adaptive Thresholding (Binarization)
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    
    # 4. Morphological Transformations (Closing) to connect broken letters
    kernel = np.ones((2, 2), np.uint8)
    processed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    # 5. Convert back to PIL Image
    return Image.fromarray(processed)


def crop_to_square_center(img: Image.Image, size: int = 224) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)
