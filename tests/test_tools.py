from __future__ import annotations

from typing import Any

import pytest

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.errors import GarminAuthError
from mcp_garmin_connect.garmin_client import GarminClientManager, reset_manager
from mcp_garmin_connect.tools import (
    TOOL_SPECS,
    _hr_drift,
    get_activity_splits,
    get_monthly_running_stats,
    get_personal_records,
    get_recent_activities,
    get_recent_load,
    get_resting_heart_rate,
    get_running_summary,
    get_zones,
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

    def get_activity_splits(self, activity_id: int) -> dict[str, Any]:
        if activity_id == 2:
            return {
                "activityId": 2,
                "lapDTOs": [
                    {
                        "distance": 1000.0,
                        "duration": 500.0,
                        "averageSpeed": 2.0,
                        "averageHR": 140,
                        "maxHR": 148,
                        "averageRunCadence": 158,
                        "elevationGain": 4,
                    },
                    {
                        "distance": 1000.0,
                        "duration": 520.0,
                        "averageSpeed": 1.9230769,
                        "averageHR": 146,
                        "maxHR": 152,
                        "averageRunCadence": 156,
                    },
                ],
            }
        if activity_id == 3:
            return {}
        return {
            "activityId": 1,
            "lapDTOs": [
                {
                    "distance": 1000.0,
                    "duration": 480.0,
                    "averageSpeed": 2.0833333,
                    "averageHR": 138,
                    "maxHR": 145,
                    "averageRunCadence": 162,
                    "elevationGain": 3,
                },
                {
                    "distance": 1000.0,
                    "duration": 486.0,
                    "averageSpeed": 2.0576131,
                    "averageHR": 141,
                    "maxHR": 149,
                    "averageRunCadence": 160,
                    "elevationGain": 5,
                },
                {
                    "distance": 1000.0,
                    "duration": 492.0,
                    "averageSpeed": 2.0325203,
                    "averageHR": 145,
                    "maxHR": 153,
                    "averageRunCadence": 159,
                    "elevationGain": 2,
                },
                {
                    "distance": 1000.0,
                    "duration": 498.0,
                    "averageSpeed": 2.0080321,
                    "averageHR": 150,
                    "maxHR": 158,
                    "averageRunCadence": 157,
                    "elevationGain": 6,
                },
                {
                    "distance": 1000.0,
                    "duration": 504.0,
                    "averageSpeed": 1.9841270,
                    "averageHR": 156,
                    "maxHR": 163,
                    "averageRunCadence": 155,
                    "elevationGain": 1,
                },
                {
                    "distance": 1000.0,
                    "duration": 512.0,
                    "averageSpeed": 1.9531250,
                    "averageHR": 161,
                    "maxHR": 168,
                    "averageRunCadence": 153,
                    "elevationGain": 4,
                },
            ],
        }

    display_name = "fake-user"

    def get_user_profile(self) -> dict[str, Any]:
        return {
            "userData": {
                "gender": "MALE",
                "birthDate": "2005-07-11",
                "weight": 73000,
                "heartRateZones": [{"zone": 1, "low": 100, "high": 120}],
                "lactateThresholdHeartRate": 165,
            }
        }

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


def test_activity_splits_normalizes_laps_and_hr_drift() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_activity_splits(activity_id=1)

    assert result["lap_count"] == 6
    assert "errors" not in result
    first = result["laps"][0]
    assert first["index"] == 1
    assert first["distance_km"] == 1.0
    assert first["duration"] == "8:00"
    assert first["pace"] == "8:00/km"
    assert first["pace_seconds_per_km"] == 480.0
    assert first["hr_avg"] == 138
    assert first["hr_max"] == 145
    assert first["cadence"] == 162
    assert first["elevation_gain_m"] == 3.0
    assert result["laps"][1]["elevation_gain_m"] == 5.0
    assert result["laps"][1]["pace"] == "8:06/km"

    assert result["summary"]["distance_km"] == 6.0
    assert result["summary"]["duration"] == "49:32"
    assert result["summary"]["avg_pace"] == "8:15/km"
    assert result["summary"]["avg_hr"] == 149.0
    assert result["summary"]["avg_cadence"] == 158.0
    assert result["summary"]["elevation_gain_m"] == 21.0

    drift = result["hr_drift"]
    assert drift["first_half_avg_hr"] == 141.0
    assert drift["second_half_avg_hr"] == 156.0
    assert drift["drift_pct"] == 10.1
    assert drift["interpretation"].startswith("drift tinggi")
    assert "hr_drift_note" not in result


def test_activity_splits_reports_when_hr_drift_is_unavailable() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_activity_splits(activity_id=2)

    assert result["lap_count"] == 2
    assert result["laps"][0]["pace"] == "8:20/km"
    assert result["laps"][1]["elevation_gain_m"] is None
    assert result["summary"]["distance_km"] == 2.0
    assert result["summary"]["duration"] == "17:00"
    assert result["summary"]["elevation_gain_m"] == 4.0
    assert result["hr_drift"] is None
    assert result["hr_drift_note"] == "needs at least 4 laps, got 2"


def test_activity_splits_without_data_returns_error() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_activity_splits(activity_id=3)

    assert result["activity_id"] == 3
    assert result["error"] == "splits not found or inaccessible"


@pytest.mark.parametrize(
    ("hr_values", "expected"),
    [
        ([140, 141, 140, 141], "stabil"),
        ([140, 141, 144, 146], "drift ringan"),
        ([140, 145, 155, 160], "drift tinggi (cari penyebab: panas/dehidrasi/kelelahan)"),
    ],
)
def test_hr_drift_interpretation_thresholds(hr_values: list[int], expected: str) -> None:
    laps = [{"hr_avg": value} for value in hr_values]

    drift, note = _hr_drift(laps)

    assert note is None
    assert drift is not None
    assert drift["interpretation"] == expected


def test_hr_drift_needs_all_laps() -> None:
    drift, note = _hr_drift([{"hr_avg": 140}, {"hr_avg": 145}, {"hr_avg": 150}, {"hr_avg": None}])

    assert drift is None
    assert note == "not every lap reports an average heart rate"


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


def test_get_zones_trims_profile_pii() -> None:
    import mcp_garmin_connect.garmin_client as garmin_client

    garmin_client._manager = FakeManager()

    result = get_zones()

    assert result["available"] is True
    assert "heartRateZones" in result["zones"]
    assert "lactateThresholdHeartRate" in result["zones"]
    assert "gender" not in result["zones"]
    assert "birthDate" not in result["zones"]
    assert "weight" not in result["zones"]


def test_safe_call_records_endpoint_errors() -> None:
    manager = FakeManager()
    errors: list[dict[str, str]] = []

    result = manager.safe_call(
        lambda: (_ for _ in ()).throw(ValueError("bad payload")),
        default=None,
        errors=errors,
        label="sleep:2999-01-01",
    )

    assert result is None
    assert errors == [{"source": "sleep:2999-01-01", "error": "ValueError: bad payload"}]


def test_safe_call_maps_auth_errors() -> None:
    manager = FakeManager()

    class GarminConnectAuthenticationError(Exception):
        pass

    with pytest.raises(GarminAuthError):
        manager.safe_call(lambda: (_ for _ in ()).throw(GarminConnectAuthenticationError()))
