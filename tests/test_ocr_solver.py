import pytest
import base64
import io
from PIL import Image
from src.models import CaptchaChallenge, CaptchaType, CaptchaSolution
from src.solvers.ocr import OCRSolver

class DummyReader:
    def readtext(self, img, detail=1):
        return [
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "captcha", 0.95),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "text", 0.99),
            ([[0, 0], [1, 0], [1, 1], [0, 1]], "ignore", 0.1)
        ]

@pytest.fixture
def mock_easyocr(mocker):
    from src.utils.model_manager import ModelManager
    mocker.patch.object(ModelManager, 'get_easyocr', return_value=DummyReader())

@pytest.mark.asyncio
async def test_ocr_solver_success(mock_easyocr):
    solver = OCRSolver()
    img = Image.new("RGB", (1, 1), "black")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b64 = base64.b64encode(b.getvalue()).decode("utf-8")
    
    challenge = CaptchaChallenge(
        type=CaptchaType.IMAGE_CAPTCHA,
        extra={"image_data": b64}
    )
    
    solution = await solver.solve(challenge)
    assert solution.success is True
    assert solution.token == "captchatext"
    assert solution.solved_via == "ocr"

@pytest.mark.asyncio
async def test_ocr_solver_no_image():
    solver = OCRSolver()
    challenge = CaptchaChallenge(
        type=CaptchaType.IMAGE_CAPTCHA,
        extra={}
    )
    
    solution = await solver.solve(challenge)
    assert solution.success is False
    assert "no image_data" in solution.error
