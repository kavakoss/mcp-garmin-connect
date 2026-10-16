"""Regression tests for issue #3 (recovery unit) and the env-tunable history caps.

Covers:
* `recovery_time_hours` must convert Garmin's minutes to hours (issue #3, @sheloab).
* Activity history must page through Garmin instead of silently stopping at 200.
* The tool caps (30/365/200) are configuration, not hardcoded numbers.
"""

from __future__ import annotations

from typing import Any

from mcp_garmin_connect.config import (
    MAX_ACTIVITY_LIMIT,
    MAX_DAYS_ACTIVITIES,
    MAX_DAYS_HEALTH,
    Settings,
)
from mcp_garmin_connect.garmin_client import GarminClientManager, reset_manager
from mcp_garmin_connect.tools import TOOL_SPECS, _activities_paged, _minutes_to_hours

# --------------------------------------------------------------- issue #3


def test_recovery_time_is_converted_from_minutes_to_hours() -> None:
    """Values reported in issue #3: 793, 1082, 660, 1 minutes."""
    assert _minutes_to_hours(793) == 13.2
    assert _minutes_to_hours(1082) == 18.0
    assert _minutes_to_hours(660) == 11.0
    assert _minutes_to_hours(1) == 0.0


def test_recovery_time_handles_missing_and_non_numeric_values() -> None:
    assert _minutes_to_hours(None) is None
    assert _minutes_to_hours("not a number") is None
    # bool is a subclass of int in Python and must not be treated as a duration.
    assert _minutes_to_hours(True) is None
    assert _minutes_to_hours(False) is None


# --------------------------------------------------------------- pagination


class FakeGarmin:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def get_activities(self, start: int, limit: int) -> list[dict[str, Any]]:
        self.calls.append((start, limit))
        return [
            {
                "activityId": index + 1,
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "startTimeLocal": "2999-01-01 07:00:00",
                "duration": 1800,
                "distance": 5000,
                "averageHR": 140,
            }
            for index in range(start, min(start + limit, self.total))
        ]


class FakeManager(GarminClientManager):
    def __init__(self, total: int = 0) -> None:
        super().__init__(
            Settings(
                garmin_email="x",
                garmin_password="y",
                garmin_token_store=".",
                deepseek_api_key=None,
                deepseek_base_url="https://api.deepseek.com",
                deepseek_model="deepseek-v4-pro",
                openai_api_key=None,
                openai_base_url="https://api.openai.com/v1",
                openai_model="gpt-5",
                anthropic_api_key=None,
                anthropic_base_url="https://api.anthropic.com",
                anthropic_model="claude-sonnet-5",
                openrouter_api_key=None,
                openrouter_base_url="https://openrouter.ai/api/v1",
                openrouter_model="google/gemini-3-flash-preview",
                gemini_api_key=None,
                gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
                gemini_model="gemini-3.6-flash",
                cache_ttl_seconds=60,
            )
        )
        self._client = FakeGarmin(total)


def _install(total: int) -> FakeGarmin:
    reset_manager()
    import mcp_garmin_connect.garmin_client as garmin_client

    manager = FakeManager(total)
    garmin_client._manager = manager
    return manager._client  # type: ignore[return-value]


def test_activities_paged_walks_every_page() -> None:
    fake = _install(450)

    activities = _activities_paged(450)

    assert len(activities) == 450
    assert fake.calls == [(0, 200), (200, 200), (400, 200)]


def test_activities_paged_stops_at_max_items() -> None:
    fake = _install(1000)

    activities = _activities_paged(250)

    assert len(activities) == 250
    # Only two pages are needed for 250 items.
    assert fake.calls == [(0, 200), (200, 200)]


def test_activities_paged_handles_fewer_items_than_one_page() -> None:
    fake = _install(12)

    activities = _activities_paged(500)

    assert len(activities) == 12
    assert fake.calls == [(0, 200)]


def test_activities_paged_with_zero_budget_makes_no_call() -> None:
    fake = _install(100)

    assert _activities_paged(0) == []
    assert fake.calls == []


# --------------------------------------------------------------- caps


def test_default_caps_are_backwards_compatible() -> None:
    assert (MAX_DAYS_HEALTH, MAX_DAYS_ACTIVITIES, MAX_ACTIVITY_LIMIT) == (30, 365, 200)


def test_tool_specs_share_the_configured_caps() -> None:
    """Changing the env vars must move the tool schema too, not just the clamp."""
    spec_by_name = {spec.name: spec for spec in TOOL_SPECS}

    assert spec_by_name["get_sleep"].parameters["days"]["maximum"] == MAX_DAYS_HEALTH
    assert spec_by_name["get_stress"].parameters["days"]["maximum"] == MAX_DAYS_HEALTH
    assert spec_by_name["get_health_summary"].parameters["days"]["maximum"] == MAX_DAYS_HEALTH
    assert (
        spec_by_name["get_recent_activities"].parameters["days"]["maximum"] == MAX_DAYS_ACTIVITIES
    )
    assert (
        spec_by_name["get_recent_activities"].parameters["limit"]["maximum"] == MAX_ACTIVITY_LIMIT
    )
    assert (
        spec_by_name["get_full_snapshot"].parameters["activity_days"]["maximum"]
        == MAX_DAYS_ACTIVITIES
    )
