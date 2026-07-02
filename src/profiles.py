from __future__ import annotations

import logging
import time
import os
import json
from pathlib import Path
from typing import Optional

from src.config import (
    AppConfig,
    BrowserProfile,
    ProxyConfig,
    SolverConfig,
    get_config,
    save_config,
)

logger = logging.getLogger("captcha_solver")


class ProfileManager:
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        Path(self.config.solver.profiles_dir).mkdir(parents=True, exist_ok=True)

    def create(self, name: str, proxy: Optional[ProxyConfig] = None) -> BrowserProfile:
        profile_dir = str(Path(self.config.solver.profiles_dir) / name)
        os.makedirs(profile_dir, exist_ok=True)

        profile = BrowserProfile(
            name=name,
            user_data_dir=profile_dir,
            proxy=proxy,
            created_at=time.time(),
        )
        self.config.add_profile(profile)
        save_config()
        logger.info(f"created profile '{name}' at {profile_dir}")
        return profile

    def get(self, name: str) -> Optional[BrowserProfile]:
        return self.config.get_profile(name)

    def get_or_create(self, name: str = "default") -> BrowserProfile:
        profile = self.get(name)
        if not profile:
            profile = self.create(name)
        return profile

    def list(self) -> list[BrowserProfile]:
        return self.config.profiles

    def record_use(self, name: str, success: bool) -> None:
        profile = self.get(name)
        if profile:
            profile.last_used_at = time.time()
            profile.use_count += 1
            if success:
                profile.success_count += 1
            save_config()

    def get_next_profile(self) -> BrowserProfile:
        if not self.config.profiles:
            return self.create("default")

        sorted_profiles = sorted(
            self.config.profiles, key=lambda p: p.last_used_at
        )
        return sorted_profiles[0]

    def serialize_state(self, state: dict, profile_name: str) -> None:
        profile = self.get(profile_name)
        if profile and profile.user_data_dir:
            state_path = Path(profile.user_data_dir) / "state.json"
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)

    def load_state(self, profile_name: str) -> Optional[dict]:
        profile = self.get(profile_name)
        if profile and profile.user_data_dir:
            state_path = Path(profile.user_data_dir) / "state.json"
            if state_path.exists():
                with open(state_path) as f:
                    return json.load(f)
        return None
