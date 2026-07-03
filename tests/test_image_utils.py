import base64
import io
from PIL import Image
import numpy as np
from src.utils.image import decode_image, preprocess_for_ocr, crop_to_square_center

def test_decode_image_bytes():
    img = Image.new("RGB", (1, 1), "black")
    b = io.BytesIO()
    img.save(b, format="PNG")
    
    decoded = decode_image(b.getvalue())
    assert decoded.size == (1, 1)

def test_decode_image_base64():
    img = Image.new("RGB", (1, 1), "black")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b64 = base64.b64encode(b.getvalue()).decode("utf-8")
    
    decoded = decode_image(b64)
    assert decoded.size == (1, 1)
    
    decoded_with_prefix = decode_image(f"data:image/png;base64,{b64}")
    assert decoded_with_prefix.size == (1, 1)

def test_preprocess_for_ocr():
    img = Image.new("RGB", (100, 100), "white")
    processed = preprocess_for_ocr(img)
    assert isinstance(processed, Image.Image)
    assert processed.size == (100, 100)

def test_crop_to_square_center():
    img = Image.new("RGB", (200, 100), "white")
    cropped = crop_to_square_center(img, size=50)
    assert cropped.size == (50, 50)
