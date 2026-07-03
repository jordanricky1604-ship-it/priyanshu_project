from __future__ import annotations

import logging
import time
import io
import base64

from PIL import Image
import numpy as np

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.image import decode_image, crop_to_square_center
from src.utils.model_manager import ModelManager

logger = logging.getLogger("captcha_solver")


COMMON_RECAPTCHA_LABELS = [
    "a photo of a bus",
    "a photo of a car",
    "a photo of a traffic light",
    "a photo of a fire hydrant",
    "a photo of a bicycle",
    "a photo of a motorcycle",
    "a photo of a crosswalk",
    "a photo of a bridge",
    "a photo of a stair",
    "a photo of a chimney",
    "a photo of a palm tree",
    "a photo of a boat",
    "a photo of a train",
    "a photo of a parking meter",
    "a photo of a truck",
    "a photo of a street sign",
    "a photo of a cat",
    "a photo of a dog",
    "a photo of a sidewalk",
    "a photo of a store front",
    "no objects in this image",
]

_HCAPTCHA_LABELS = [
    "a photo of an airplane in the sky",
    "a photo of a bicycle",
    "a photo of a bridge",
    "a photo of a bus",
    "a photo of a car",
    "a photo of a crosswalk",
    "a photo of a truck",
    "a photo of a boat",
    "a photo of a train",
    "a photo of a traffic signal",
    "a photo of a fire hydrant",
    "a photo of a staircase",
    "a photo of a store with a sign",
]


class ImageClassifierSolver(BaseSolver):
    name = "image_classifier"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.IMAGE_CAPTCHA and "image_data" in challenge.extra

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        try:
            image_data = challenge.extra.get("image_data", "")
            prompt = challenge.extra.get("prompt", "")
            grid_size = challenge.extra.get("grid_size", 9)

            if not image_data:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no image_data in challenge.extra",
                )

            img = decode_image(image_data)
            selected_tiles = self._classify_grid(img, prompt, grid_size)

            elapsed = (time.time() - start) * 1000
            result = ",".join(str(t) for t in selected_tiles)
            logger.info(f"image classifier selected tiles: {result}")
            return CaptchaSolution(
                type=challenge.type,
                token=result,
                solved_via="image_classifier",
                extra={"selected_tiles": selected_tiles},
                attempts=1,
                elapsed_ms=elapsed,
                success=len(selected_tiles) > 0,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
                attempts=1,
                elapsed_ms=elapsed,
            )

    def _classify_grid(
        self, img: Image.Image, prompt: str, grid_size: int = 9
    ) -> list[int]:
        import torch

        model, preprocess, tokenizer, device = self.model_manager.get_clip()

        grid_dim = int(grid_size ** 0.5)
        if grid_dim * grid_dim != grid_size:
            grid_dim = 3
        tile_w = img.width // grid_dim
        tile_h = img.height // grid_dim

        labels = self._get_labels_for_prompt(prompt)
        text_tokens = tokenizer(labels).to(device)

        with torch.no_grad():
            text_features = model.encode_text(text_tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

        selected = []
        for idx in range(grid_dim * grid_dim):
            row = idx // grid_dim
            col = idx % grid_dim
            tile = img.crop(
                (col * tile_w, row * tile_h, (col + 1) * tile_w, (row + 1) * tile_h)
            )
            tile = preprocess(tile).unsqueeze(0).to(device)

            with torch.no_grad():
                image_features = model.encode_image(tile)
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
                best_idx = similarity[0].argmax().item()

            if best_idx < len(labels) - 1 and similarity[0][best_idx] > 0.15:
                selected.append(idx)

        return selected

    def _get_labels_for_prompt(self, prompt: str) -> list[str]:
        prompt_lower = prompt.lower()

        prompt_map = {
            "bus": [l for l in COMMON_RECAPTCHA_LABELS if "bus" in l],
            "car": [l for l in COMMON_RECAPTCHA_LABELS if "car" in l or "truck" in l or "vehicle" in l],
            "traffic light": [l for l in COMMON_RECAPTCHA_LABELS if "traffic" in l],
            "fire hydrant": [l for l in COMMON_RECAPTCHA_LABELS if "hydrant" in l],
            "bicycle": [l for l in COMMON_RECAPTCHA_LABELS if "bicy" in l],
            "motorcycle": [l for l in COMMON_RECAPTCHA_LABELS if "motor" in l],
            "crosswalk": [l for l in COMMON_RECAPTCHA_LABELS if "cross" in l or "sidewalk" in l],
            "bridge": [l for l in COMMON_RECAPTCHA_LABELS if "bridge" in l],
            "stair": [l for l in COMMON_RECAPTCHA_LABELS if "stair" in l],
            "chimney": [l for l in COMMON_RECAPTCHA_LABELS if "chimney" in l],
            "boat": [l for l in COMMON_RECAPTCHA_LABELS if "boat" in l],
            "train": [l for l in COMMON_RECAPTCHA_LABELS if "train" in l],
            "parking meter": [l for l in COMMON_RECAPTCHA_LABELS if "parking" in l],
            "palm": [l for l in COMMON_RECAPTCHA_LABELS if "palm" in l],
            "truck": [l for l in COMMON_RECAPTCHA_LABELS if "truck" in l],
            "airplane": [l for l in HCAPTCHA_LABELS if "airplane" in l or "plane" in l],
        }

        for key, label_set in prompt_map.items():
            if key in prompt_lower:
                return label_set + ["no objects in this image"]

        return COMMON_RECAPTCHA_LABELS


SolverRegistry.register(ImageClassifierSolver())
