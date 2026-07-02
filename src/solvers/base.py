from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.models import CaptchaChallenge, CaptchaSolution

logger = logging.getLogger("captcha_solver")


class BaseSolver(ABC):
    name: str = "base"

    async def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        raise NotImplementedError

    def can_solve(self, challenge: CaptchaChallenge) -> bool:
        return False


class SolverRegistry:
    _solvers: list[BaseSolver] = []

    @classmethod
    def register(cls, solver: BaseSolver) -> None:
        cls._solvers.append(solver)
        logger.debug(f"registered solver: {solver.name}")

    @classmethod
    def get_solvers(cls) -> list[BaseSolver]:
        return cls._solvers

    @classmethod
    def find(cls, challenge: CaptchaChallenge) -> BaseSolver | None:
        for solver in cls._solvers:
            if solver.can_solve(challenge):
                return solver
        return None
