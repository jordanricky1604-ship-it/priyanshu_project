import gc
import logging
import os
from typing import Any

logger = logging.getLogger("captcha_solver")


_global_model_manager = None

def get_model_manager() -> 'ModelManager':
    global _global_model_manager
    if _global_model_manager is None:
        _global_model_manager = ModelManager()
    return _global_model_manager


class ModelManager:
    """
    Dependency Injection container and Context Manager for heavy ML models.
    Lazy-loads models only when requested, and can unload them to free VRAM/RAM.
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, whisper_model_size: str = "tiny.en", clip_model_name: str = "ViT-B-32", ocr_languages: list[str] | None = None):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        
        self.whisper_model_size = whisper_model_size
        self.clip_model_name = clip_model_name
        self.ocr_languages = ocr_languages or ["en"]
        
        self._whisper_model = None
        self._clip_model = None
        self._clip_preprocess = None
        self._clip_tokenizer = None
        self._clip_device = "cpu"
        self._easyocr_reader = None
        self._ddddocr_reader = None

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

    def get_llm(self) -> Any:
        if not hasattr(self, "_llm_pipeline"):
            self._llm_pipeline = None
            
        if self._llm_pipeline is None:
            try:
                from transformers import pipeline
                import torch
                logger.info("loading Qwen2.5-0.5B-Instruct...")
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._llm_pipeline = pipeline(
                    "text-generation",
                    model="Qwen/Qwen2.5-0.5B-Instruct",
                    device=device,
                    torch_dtype=torch.float16 if device == "cuda" else torch.float32
                )
                logger.info("Qwen2.5-0.5B-Instruct ready")
            except ImportError:
                logger.error("transformers not installed. Run: pip install transformers")
                raise
        return self._llm_pipeline

    def get_owlvit(self) -> Any:
        if not hasattr(self, "_owlvit_processor"):
            self._owlvit_processor = None
            self._owlvit_model = None
            
        if self._owlvit_model is None:
            try:
                from transformers import OwlViTProcessor, OwlViTForObjectDetection
                import torch
                logger.info("loading OwlViT...")
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._owlvit_processor = OwlViTProcessor.from_pretrained("google/owlvit-base-patch32")
                self._owlvit_model = OwlViTForObjectDetection.from_pretrained("google/owlvit-base-patch32").to(device)
                self._owlvit_model.eval()
                self._owlvit_device = device
                logger.info("OwlViT ready")
            except ImportError:
                logger.error("transformers not installed")
                raise
        return self._owlvit_processor, self._owlvit_model, getattr(self, "_owlvit_device", "cpu")

    def get_ddddocr(self) -> Any:
        if self._ddddocr_reader is None:
            try:
                import ddddocr
                logger.info("loading ddddocr model...")
                self._ddddocr_reader = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr ready")
            except ImportError:
                logger.error("ddddocr not installed")
                raise
        return self._ddddocr_reader

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

        if getattr(self, "_ddddocr_reader", None) is not None:
            self._ddddocr_reader = None
            unloaded = True

        if getattr(self, "_llm_pipeline", None) is not None:
            self._llm_pipeline = None
            unloaded = True

        if getattr(self, "_owlvit_model", None) is not None:
            self._owlvit_model = None
            self._owlvit_processor = None
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
