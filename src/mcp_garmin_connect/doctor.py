from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass

from .config import Settings
from .garmin_client import GarminClientManager


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_checks(include_live: bool = False) -> list[Check]:
    settings = Settings.from_env()
    manager = GarminClientManager(settings=settings)
    checks = [
        Check("python-package", True, "mcp-garmin-connect import OK"),
        Check("mcp", importlib.util.find_spec("mcp") is not None, "Python MCP SDK installed"),
        Check(
            "garminconnect",
            importlib.util.find_spec("garminconnect") is not None,
            "garminconnect installed",
        ),
        Check("garmin-email", bool(settings.garmin_email), "GARMIN_EMAIL configured"),
        Check("garmin-password", bool(settings.garmin_password), "GARMIN_PASSWORD configured"),
        Check(
            "token-store",
            os.path.isdir(settings.garmin_token_store),
            f"Token store: {settings.garmin_token_store}",
        ),
        Check(
            "token-cache",
            manager.token_cache_present(),
            "Garmin token cache present" if manager.token_cache_present() else "Run garmin-mcp login",
        ),
        Check(
            "deepseek-key",
            bool(settings.deepseek_api_key),
            "DEEPSEEK_API_KEY configured" if settings.deepseek_api_key else "Optional demo key missing",
        ),
    ]
    if include_live:
        try:
            manager.login(allow_interactive_mfa=False)
            checks.append(Check("garmin-live-login", True, "Garmin login OK"))
        except Exception as exc:
            checks.append(Check("garmin-live-login", False, f"{type(exc).__name__}: {exc}"))
    return checks
