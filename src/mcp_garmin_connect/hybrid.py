"""Hybrid backend: use the official Personal API *and* the unofficial flow together.

Neither backend alone covers everything a training agent wants:

* the official Personal API is stable and returns the raw ``.FIT``, SpO2, weight,
  hydration and steps, but it cannot see metrics Garmin derives on the activity
  (training status/load, readiness, VO2 Max, race predictions, personal records);
* the unofficial email/password flow does expose those derived metrics, but it is
  fragile and can be rate-limited or locked out by SSO changes.

``GARMIN_AUTH_MODE=hybrid`` runs both and routes each call to the backend that
actually owns the data, falling back to the other one when a call fails. That way
one process can serve a full snapshot without the caller knowing which system
answered.
"""

from __future__ import annotations

import logging
from typing import Any

from .errors import (
    PersonalApiAuthError,
    PersonalApiHttpError,
    PersonalApiRateLimitError,
    PersonalApiUnsupported,
)

log = logging.getLogger("mcp-garmin-connect")

# Wellness and raw-recording reads: the official API owns these.
PERSONAL_METHODS = frozenset(
    {
        "get_sleep_data",
        "get_hrv_data",
        "get_rhr_day",
        "get_all_day_stress",
        "get_body_battery",
        "get_activities",
        "get_activity",
        "get_activity_splits",
        "get_activity_workouts",
        "get_body_composition",
        "get_daily_summaries",
        "get_spo2",
        "get_hydration",
        "get_steps",
        "get_fitness_age",
        "download_activity_file",
    }
)

# Garmin-derived metrics: only the unofficial flow has them.
UNOFFICIAL_METHODS = frozenset(
    {
        "get_training_status",
        "get_training_readiness",
        "get_race_predictions",
        "get_max_metrics",
        "get_cycling_ftp",
        "get_personal_record",
        "connectapi",
    }
)

# Errors that mean "this backend cannot answer", so the other one may try.
_FALLBACK_ERRORS = (PersonalApiUnsupported, PersonalApiHttpError, PersonalApiRateLimitError)
# Errors that mean "credentials are wrong" — never silently masked.
_FATAL_ERRORS = (PersonalApiAuthError,)


class HybridBackend:
    """Routes each client call to the backend that owns that data set."""

    backend_name = "hybrid"

    def __init__(self, personal: Any, unofficial: Any) -> None:
        self._personal = personal
        self._unofficial = unofficial

    @property
    def display_name(self) -> str | None:
        for backend in (self._personal, self._unofficial):
            name = getattr(backend, "display_name", None)
            if isinstance(name, str) and name:
                return name
        return None

    def close(self) -> None:
        for backend in (self._personal, self._unofficial):
            closer = getattr(backend, "close", None)
            if callable(closer):
                closer()

    def routing(self) -> dict[str, str]:
        """Which backend answers which method, for `doctor` and debugging."""
        return {
            "personal": sorted(PERSONAL_METHODS),
            "unofficial": sorted(UNOFFICIAL_METHODS),
        }

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        personal_fn = getattr(self._personal, name, None)
        unofficial_fn = getattr(self._unofficial, name, None)
        preferred = (
            (personal_fn, unofficial_fn)
            if name in PERSONAL_METHODS
            else (unofficial_fn, personal_fn)
        )
        available = [fn for fn in preferred if callable(fn)]
        if not available:
            raise AttributeError(name)
        return _make_router(name, available)


def _make_router(name: str, available: list[Any]) -> Any:
    def call(*args: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for index, fn in enumerate(available):
            try:
                return fn(*args, **kwargs)
            except _FATAL_ERRORS:
                raise
            except _FALLBACK_ERRORS as exc:
                last_error = exc
                if index == len(available) - 1:
                    break
                log.info("%s unavailable on one backend (%s), trying the other", name, exc)
            except Exception as exc:  # noqa: BLE001 - last resort fallback
                last_error = exc
                if index == len(available) - 1:
                    break
                log.info("%s failed (%s), trying the other backend", name, exc)
        if last_error is not None:
            raise last_error
        raise AttributeError(name)

    return call
