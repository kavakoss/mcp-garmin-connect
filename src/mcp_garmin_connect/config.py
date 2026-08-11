from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def load_environment() -> None:
    load_dotenv()
    for key in list(os.environ):
        if key.startswith("\ufeff"):
            os.environ.setdefault(key.lstrip("\ufeff"), os.environ[key])


@dataclass(frozen=True)
class Settings:
    garmin_email: str | None
    garmin_password: str | None
    garmin_token_store: str
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    cache_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_environment()
        return cls(
            garmin_email=os.getenv("GARMIN_EMAIL"),
            garmin_password=os.getenv("GARMIN_PASSWORD"),
            garmin_token_store=os.path.normpath(
                os.path.expanduser(os.getenv("GARMIN_TOKEN_STORE", "~/.garminconnect"))
            ),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            cache_ttl_seconds=int(os.getenv("GARMIN_CACHE_TTL_SECONDS", "120")),
        )

    def require_garmin_credentials(self) -> tuple[str, str]:
        if not self.garmin_email or not self.garmin_password:
            raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env or env vars.")
        return self.garmin_email, self.garmin_password

    def require_deepseek_key(self) -> str:
        if not self.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY must be set for the DeepSeek demo agent.")
        return self.deepseek_api_key
