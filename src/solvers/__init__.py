from src.solvers.base import BaseSolver, SolverRegistry
from src.solvers.browser_token import BrowserTokenSolver
from src.solvers.geetest import GeeTestSolver
from src.solvers.image_classifier import ImageClassifierSolver
from src.solvers.browser_image import BrowserImageSolver
from src.solvers.browser_audio import BrowserAudioSolver
from src.solvers.ocr import OCRSolver
from src.solvers.funcaptcha import FunCaptchaSolver
from src.solvers.audio import AudioSolver
from src.solvers.browser_text import BrowserTextLogicSolver
from src.solvers.browser_click import BrowserClickSolver
from src.solvers.browser_rotate import BrowserRotateSolver
from src.solvers.browser_keycaptcha import BrowserKeyCaptchaSolver
from src.utils.model_manager import ModelManager

# Create a single global model manager for all solvers
_model_manager = ModelManager()

SolverRegistry.register(GeeTestSolver())

__all__ = [
    "BaseSolver",
    "SolverRegistry",
    "BrowserTokenSolver",
    "GeeTestSolver",
    "ImageClassifierSolver",
    "BrowserImageSolver",
    "BrowserAudioSolver",
    "OCRSolver",
    "FunCaptchaSolver",
    "AudioSolver",
    "BrowserTextLogicSolver",
    "BrowserClickSolver",
    "BrowserRotateSolver",
    "BrowserKeyCaptchaSolver",
]
