import pytest
from fastapi.testclient import TestClient
from src.daemon import app
import re

client = TestClient(app)

def test_metrics_endpoint():
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.text
    
    # Check if the metrics are correctly exposed
    assert "captcha_requests_total" in content
    assert "captcha_fallbacks_total" in content
    assert "captcha_rate_limits_total" in content
    assert "captcha_solve_duration_seconds" in content
    assert "captcha_active_solves" in content
