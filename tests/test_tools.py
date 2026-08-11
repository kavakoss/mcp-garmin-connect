from __future__ import annotations

from typing import Any

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.garmin_client import GarminClientManager, reset_manager
from mcp_garmin_connect.tools import TOOL_SPECS, get_recent_activities, get_recent_load, tool_schema


class FakeGarmin:
    def get_activities(self, start: int, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "activityId": 1,
                "activityName": "Run",
                "activityType": {"typeKey": "running"},
                "startTimeLocal": "2999-01-01 07:00:00",
                "duration": 1800,
                "distance": 5000,
                "averageHR": 140,
            },
            {
                "activityId": 2,
                "activityName": "Ride",
                "activityType": {"typeKey": "cycling"},
                "startTimeLocal": "2999-01-01 08:00:00",
                "duration": 3600,
                "distance": 30000,
                "averageHR": 130,
            },
        ]


class FakeManager(GarminClientManager):
    def __init__(self) -> None:
        super().__init__(
            Settings(
                garmin_email="x",
                garmin_password="y",
                garmin_token_store=".",
                deepseek_api_key=None,
                deepseek_base_url="https://api.deepseek.com",
                deepseek_model="deepseek-v4-pro",
                cache_ttl_seconds=60,
            )
        )
        self._client = FakeGarmin()


def test_recent_activities_with_fake_manager() -> None:
    reset_manager()
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_recent_activities(days=30)

    assert result["count"] == 2
    assert result["activities"][0]["sport"] == "bike"
    assert result["activities"][1]["sport"] == "run"


def test_recent_load_aggregates_by_sport() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_recent_load(days=30)

    assert result["by_sport"]["run"]["total_km"] == 5.0
    assert result["by_sport"]["bike"]["total_hours"] == 1.0


def test_tool_schemas_are_objects() -> None:
    for spec in TOOL_SPECS:
        schema = tool_schema(spec)
        assert schema["type"] == "object"
        assert "properties" in schema
