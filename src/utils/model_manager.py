import gc
import logging
import os
from typing import Any

logger = logging.getLogger("captcha_solver")


class ModelManager:
    """
    Dependency Injection container and Context Manager for heavy ML models.
    Lazy-loads models only when requested, and can unload them to free VRAM/RAM.
    """
    
    def __init__(self, whisper_model_size: str = "tiny.en", clip_model_name: str = "ViT-B-32", ocr_languages: list[str] | None = None):
        self.whisper_model_size = whisper_model_size
        self.clip_model_name = clip_model_name
        self.ocr_languages = ocr_languages or ["en"]
        
        self._whisper_model = None
        self._clip_model = None
        self._clip_preprocess = None
        self._clip_tokenizer = None
        self._clip_device = "cpu"
        self._easyocr_reader = None

    def _get_model_path(self) -> str:
        model_dir = os.path.join(os.path.dirname(__file__), "..", "..", "models")
        return os.path.abspath(model_dir)

    def get_whisper(self) -> Any:
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                logger.info(f"loading faster-whisper model '{self.whisper_model_size}'...")
                self._whisper_model = WhisperModel(
                    self.whisper_model_size,
                    device="cpu",
                    compute_type="int8",
                    download_root=self._get_model_path(),
                )
                logger.info("faster-whisper ready")
            except ImportError:
                logger.error("faster-whisper not installed. Run: pip install faster-whisper")
                raise
        return self._whisper_model

    def get_clip(self) -> tuple[Any, Any, Any, str]:
        if self._clip_model is None:
            try:
                import torch
                import open_clip

                self._clip_device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"loading CLIP model '{self.clip_model_name}' on {self._clip_device}...")
                self._clip_model, _, self._clip_preprocess = open_clip.create_model_and_transforms(self.clip_model_name)
                self._clip_tokenizer = open_clip.get_tokenizer(self.clip_model_name)
                self._clip_model = self._clip_model.to(self._clip_device)
                self._clip_model.eval()
                logger.info("CLIP ready")
            except ImportError:
                logger.error("open-clip-torch not installed. Run: pip install open-clip-torch")
                raise
        return self._clip_model, self._clip_preprocess, self._clip_tokenizer, self._clip_device

    def get_easyocr(self) -> Any:
        if self._easyocr_reader is None:
            try:
                import easyocr
                logger.info("loading EasyOCR (first use, may take a moment)...")
                self._easyocr_reader = easyocr.Reader(self.ocr_languages, gpu=True)
                logger.info("EasyOCR ready")
            except ImportError:
                logger.error("easyocr not installed. Run: pip install easyocr")
                raise
        return self._easyocr_reader

    def unload_all(self):
        """Unloads all models and frees memory."""
        unloaded = False
        if self._whisper_model is not None:
            self._whisper_model = None
            unloaded = True
        
        if self._clip_model is not None:
            self._clip_model = None
            self._clip_preprocess = None
            self._clip_tokenizer = None
            unloaded = True
            
        if self._easyocr_reader is not None:
            self._easyocr_reader = None
            unloaded = True
            
        if unloaded:
            logger.info("Unloaded ML models from memory")
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload_all()
