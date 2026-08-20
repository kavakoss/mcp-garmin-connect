from __future__ import annotations

from typing import Any

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.garmin_client import GarminClientManager, reset_manager
from mcp_garmin_connect.tools import (
    TOOL_SPECS,
    get_monthly_running_stats,
    get_personal_records,
    get_recent_activities,
    get_recent_load,
    get_resting_heart_rate,
    get_running_summary,
    tool_schema,
)


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

    def get_personal_record(self) -> dict[str, Any]:
        return {
            "personalRecords": [
                {
                    "typeId": 3,
                    "prTypeLabelKey": None,
                    "value": "00:30:00",
                    "prStartTimeGmtFormatted": "2999-01-01",
                },
                {
                    "typeId": 4,
                    "value": "01:05:00",
                    "prStartTimeGmtFormatted": "2999-01-02",
                }
            ]
        }

    def get_rhr_day(self, cdate: str) -> dict[str, Any]:
        return {
            "allMetrics": {
                "metricsMap": {
                    "WELLNESS_RESTING_HEART_RATE": [
                        {
                            "calendarDate": cdate,
                            "value": 50,
                        }
                    ]
                }
            }
        }

    display_name = "fake-user"

    def connectapi(self, url: str) -> list[dict[str, Any]]:
        assert url == "/personalrecord-service/personalrecordtype/prtypes/fake-user"
        return [
            {
                "id": 3,
                "key": "pr.label.5k.run",
                "visible": True,
                "sport": "RUNNING",
            }
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


def test_running_summary() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_running_summary(days=90)

    assert result["sessions"] == 1
    assert result["total_distance_km"] == 5.0
    assert result["average_pace"] == "6:00/km"
    assert result["longest_run"]["name"] == "Run"


def test_monthly_running_stats() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_monthly_running_stats(months=3)

    assert result["months"][0]["month"] == "2999-01"
    assert result["months"][0]["sessions"] == 1


def test_personal_records_uses_garminconnect_singular_method() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_personal_records()

    assert result["count"] == 2
    assert result["records"][0]["name"] == "Fastest 5K"
    assert result["records"][0]["label_key"] == "pr.label.5k.run"
    assert result["records"][0]["sport"] == "RUNNING"
    assert result["records"][1]["name"] == "Fastest 10K"


def test_resting_heart_rate_daily_weekly_monthly_summary() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_resting_heart_rate(days=3)

    assert result["period_days"] == 3
    assert result["latest_bpm"] == 50
    assert result["weekly_avg_bpm"] == 50
    assert result["monthly_avg_bpm"] == 50
    assert len(result["daily"]) == 3


def test_resting_heart_rate_clamps_to_30_days() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_resting_heart_rate(days=365)

    assert result["period_days"] == 30
    assert len(result["daily"]) == 30


def test_tool_schemas_are_objects() -> None:
    for spec in TOOL_SPECS:
        schema = tool_schema(spec)
        assert schema["type"] == "object"
        assert "properties" in schema
