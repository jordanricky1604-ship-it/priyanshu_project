from __future__ import annotations

import logging
import time

from playwright.async_api import Page

from src.models import CaptchaChallenge, CaptchaSolution, CaptchaType
from src.solvers.base import BaseSolver, SolverRegistry
from src.utils.retry import PlaywrightError

logger = logging.getLogger("captcha_solver")


from src.utils.model_manager import ModelManager

class BrowserTextLogicSolver(BaseSolver):
    name = "browser_text"

    def __init__(self, model_manager: ModelManager | None = None):
        self.model_manager = model_manager or ModelManager()

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return challenge.type == CaptchaType.TEXT_QUESTION

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        start = time.time()
        try:
            page: Page = challenge.extra.get("page")
            if not page:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="no playwright Page in challenge.extra",
                )

            # Extract the actual question
            # The demo often puts the question in a specific element or simply in text.
            # Let's try to extract from known demo locators first, then fallback to looking for '?'.
            question = ""
            demo_question_locator = page.locator("div[class*='textCaptchaContent']").first
            if await demo_question_locator.count() > 0:
                question = await demo_question_locator.inner_text()
            else:
                text = await page.evaluate("document.body.innerText")
                for line in text.split('\n'):
                    if '?' in line and len(line) < 200:
                        question = line.strip()
                        break

            if not question:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not find a question ending in '?' on the page",
                )

            logger.info(f"extracted text question: {question}")
            
            # Use local LLM
            llm = self.model_manager.get_llm()
            prompt = f"Question: {question}\nProvide the exact answer in a single word with no extra context or explanation.\nAnswer:"
            
            # Run inference
            results = llm(prompt, max_new_tokens=10, temperature=0.1, do_sample=False)
            answer = results[0]["generated_text"].split("Answer:")[-1].strip()
            # Only take the first line to prevent hallucinated extra text
            answer = answer.split('\n')[0].strip()
            
            logger.info(f"LLM answered: {answer}")

            # Find input field
            input_locator = page.locator("input[type='text']").first
            count = await input_locator.count()
            if count == 0:
                return CaptchaSolution(
                    type=challenge.type,
                    success=False,
                    error="could not find input[type='text'] to type answer",
                )
            
            # Type answer
            await input_locator.fill(answer)
            await page.wait_for_timeout(500)

            # Find submit button (if we're in the 2captcha demo, it's type="submit" or button with check)
            submit_btn = page.locator("button[type='submit'], button:has-text('Check'), button:has-text('Submit'), input[type='submit']").first
            if await submit_btn.count() > 0:
                await submit_btn.click()
                await page.wait_for_timeout(1000)

            elapsed = (time.time() - start) * 1000
            return CaptchaSolution(
                type=challenge.type,
                success=True,
                token=answer,
                elapsed_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Text logic solve failed: {e}")
            return CaptchaSolution(
                type=challenge.type,
                success=False,
                error=str(e),
            )

SolverRegistry.register(BrowserTextLogicSolver())
