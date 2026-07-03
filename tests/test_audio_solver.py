import pytest
from src.models import CaptchaChallenge, CaptchaType, CaptchaSolution
from src.solvers.audio import AudioSolver
import src.solvers.audio as audio_module

class DummyWhisperSegment:
    def __init__(self, text):
        self.text = text

class DummyWhisperInfo:
    def __init__(self):
        self.language = "en"
        self.language_probability = 0.99

class DummyWhisperModel:
    def transcribe(self, audio, **kwargs):
        segments = [DummyWhisperSegment("  1 2 3 4 5  ")]
        info = DummyWhisperInfo()
        return segments, info

@pytest.fixture
def mock_whisper(mocker):
    from src.utils.model_manager import ModelManager
    mocker.patch.object(ModelManager, 'get_whisper', return_value=DummyWhisperModel())

@pytest.mark.asyncio
async def test_audio_solver_success(mock_whisper):
    solver = AudioSolver()
    import base64
    valid_b64 = base64.b64encode(b"dummy audio data").decode("utf-8")
    challenge = CaptchaChallenge(
        type=CaptchaType.IMAGE_CAPTCHA,
        extra={"audio_data": valid_b64}
    )
    
    solution = await solver.solve(challenge)
    assert solution.success is True
    assert solution.token == "12345"
    assert solution.solved_via == "audio"

@pytest.mark.asyncio
async def test_audio_solver_no_data():
    solver = AudioSolver()
    challenge = CaptchaChallenge(
        type=CaptchaType.IMAGE_CAPTCHA,
        extra={}
    )
    
    solution = await solver.solve(challenge)
    assert solution.success is False
    assert "no audio_data" in solution.error
