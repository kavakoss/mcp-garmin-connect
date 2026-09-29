from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field

from .garmin_client import date_range_iso, get_manager, today_iso
from .normalizers import (
    activity_type_key,
    normalize_activity,
    round_number,
    sport_bucket,
)

ErrorList = list[dict[str, str]]
_FAILED = object()
_ZONE_KEY_RE = re.compile(r"(zone|threshold|lactate|ftp|vo2)", re.IGNORECASE)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    function: Callable[..., dict[str, Any]]
    parameters: dict[str, Any]


_KNOWN_PR_LABELS_BY_KEY = {
    "pr.label.1k.run": "Fastest 1K",
    "pr.label.1mile.run": "Fastest 1 mile",
    "pr.label.5k.run": "Fastest 5K",
    "pr.label.10k.run": "Fastest 10K",
    "pr.label.half.marathon": "Fastest half marathon",
    "pr.label.full.marathon": "Fastest marathon",
    "pr.label.longest.run": "Longest run",
    "pr.label.40k.cycling": "Fastest 40K ride",
    "pr.label.longest.ride": "Longest ride",
    "pr.label.max.elevation.gain": "Most elevation gained",
    "pr.label.best.20min.power": "Best 20-minute average power",
    "pr.label.most.steps.day": "Most steps in a day",
    "pr.label.most.steps.week": "Most steps in a week",
    "pr.label.most.steps.month": "Most steps in a month",
    "pr.label.longest.goal.streak": "Longest step goal streak",
}

_KNOWN_PR_LABELS_BY_TYPE_ID = {
    1: "Fastest 1K",
    2: "Fastest 1 mile",
    3: "Fastest 5K",
    4: "Fastest 10K",
    5: "Fastest half marathon",
    6: "Fastest marathon",
}


def _client() -> Any:
    return get_manager().client()


def _errors_payload(errors: ErrorList) -> dict[str, Any]:
    return {"errors": errors} if errors else {}


def _endpoint(
    key: str,
    label: str,
    factory: Callable[[], Any],
    default: Any,
    errors: ErrorList | None = None,
) -> Any:
    """Fetch one Garmin endpoint through the shared TTL cache.

    Failures are not cached: the sentinel result is evicted immediately so the
    next caller retries the endpoint.
    """
    manager = get_manager()

    def cached_factory() -> Any:
        return manager.safe_call(factory, default=_FAILED, label=label, errors=errors)

    value = manager.cached(key, cached_factory)
    if value is _FAILED:
        manager.cache.delete(key)
        return default
    return value


def _fetch_days(dates: list[str], fetch: Callable[[str], Any], max_workers: int = 4) -> list[Any]:
    if len(dates) <= 1:
        return [fetch(day) for day in dates]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(dates))) as ex:
        return list(ex.map(fetch, dates))


def _sleep_day(day: str, errors: ErrorList | None = None) -> dict[str, Any]:
    client = _client()
    raw = _endpoint(
        f"sleep_day:{day}",
        f"sleep:{day}",
        lambda: client.get_sleep_data(day),
        {},
        errors,
    )
    return raw if isinstance(raw, dict) else {}


def _hrv_day(day: str, errors: ErrorList | None = None) -> dict[str, Any]:
    client = _client()
    raw = _endpoint(
        f"hrv_day:{day}",
        f"hrv:{day}",
        lambda: client.get_hrv_data(day),
        {},
        errors,
    )
    return raw if isinstance(raw, dict) else {}


def _rhr_day(day: str, errors: ErrorList | None = None) -> dict[str, Any]:
    client = _client()
    raw = _endpoint(
        f"rhr_day:{day}",
        f"resting_heart_rate:{day}",
        lambda: client.get_rhr_day(day),
        {},
        errors,
    )
    return raw if isinstance(raw, dict) else {}


def _stress_day(day: str, errors: ErrorList | None = None) -> dict[str, Any]:
    client = _client()
    raw = _endpoint(
        f"stress_day:{day}",
        f"stress:{day}",
        lambda: client.get_all_day_stress(day),
        {},
        errors,
    )
    return raw if isinstance(raw, dict) else {}


def _training_readiness(day: str, errors: ErrorList | None = None) -> Any:
    client = _client()
    return _endpoint(
        f"training_readiness:{day}",
        f"training_readiness:{day}",
        lambda: client.get_training_readiness(day),
        None,
        errors,
    )


def _training_status(day: str, errors: ErrorList | None = None) -> dict[str, Any]:
    client = _client()
    raw = _endpoint(
        f"training_status:{day}",
        f"training_status:{day}",
        lambda: client.get_training_status(day),
        {},
        errors,
    )
    return raw if isinstance(raw, dict) else {}


def _body_battery(start: str, end: str, errors: ErrorList | None = None) -> Any:
    client = _client()
    return _endpoint(
        f"body_battery:{start}:{end}",
        f"body_battery:{start}:{end}",
        lambda: client.get_body_battery(start, end),
        [],
        errors,
    )


def _max_metrics(day: str, errors: ErrorList | None = None) -> Any:
    client = _client()
    return _endpoint(
        f"max_metrics:{day}",
        f"max_metrics:{day}",
        lambda: client.get_max_metrics(day),
        None,
        errors,
    )


def _activities_raw(limit: int = 200, errors: ErrorList | None = None) -> list[dict[str, Any]]:
    client = _client()
    raw = _endpoint(
        f"activities_raw:{limit}",
        f"activities:{limit}",
        lambda: client.get_activities(0, limit),
        [],
        errors,
    )
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _extract_resting_heart_rate_bpm(raw: Any) -> int | None:
    if not isinstance(raw, dict):
        return None

    for key in (
        "restingHeartRate",
        "restingHR",
        "restingHeartRateBpm",
        "averageRestingHeartRate",
        "value",
    ):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return int(round(value))

    try:
        metrics = raw["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
    except (KeyError, TypeError):
        metrics = None

    if isinstance(metrics, list):
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            value = metric.get("value")
            if isinstance(value, (int, float)):
                return int(round(value))
    return None


def _avg(values: list[int | float]) -> float | None:
    return round_number(sum(values) / len(values), 1) if values else None


def _personal_record_type_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _personal_record_label_key(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("key", "labelKey", "typeLabelKey", "displayName", "label"):
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return label.strip()
    return None


def _personal_record_label(label_key: str | None, type_id: int | None) -> str | None:
    if label_key:
        if label_key in _KNOWN_PR_LABELS_BY_KEY:
            return _KNOWN_PR_LABELS_BY_KEY[label_key]
        if not any(separator in label_key for separator in (".", "_", "-")):
            return label_key
        cleaned = re.sub(r"^pr[._-]label[._-]", "", label_key, flags=re.IGNORECASE)
        cleaned = re.sub(r"[._-]+", " ", cleaned).strip()
        return cleaned.title() if cleaned else label_key
    if type_id is not None:
        return _KNOWN_PR_LABELS_BY_TYPE_ID.get(type_id)
    return None


def _personal_record_type_map(client: Any, manager: Any) -> dict[int, dict[str, Any]]:
    display_name = getattr(client, "display_name", None)
    if not display_name or not hasattr(client, "connectapi"):
        return {}

    def fetch() -> Any:
        return manager.safe_call(
            lambda: client.connectapi(
                f"/personalrecord-service/personalrecordtype/prtypes/{display_name}"
            ),
            default=[],
            label="personal_record_types",
        )

    raw = manager.cached("personal_record_types", fetch)
    if not isinstance(raw, list):
        return {}

    type_map = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        type_id = _personal_record_type_id(item.get("id") or item.get("typeId"))
        if type_id is not None:
            type_map[type_id] = item
    return type_map


def get_recovery() -> dict[str, Any]:
    """Current recovery state: readiness, HRV, sleep, body battery, and status."""
    today = today_iso()
    dates = date_range_iso(7)
    errors: ErrorList = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_readiness = ex.submit(_training_readiness, today, errors)
        f_status = ex.submit(_training_status, today, errors)
        f_body = ex.submit(_body_battery, dates[-1], today, errors)
        f_rhr = ex.submit(_rhr_day, today, errors)
        hrv_days = _fetch_days(dates, lambda day: _hrv_day(day, errors))
        sleep_days = _fetch_days(dates, lambda day: _sleep_day(day, errors))
        hrv_raw = dict(zip(dates, hrv_days, strict=True))
        sleep_raw = dict(zip(dates, sleep_days, strict=True))
        readiness_raw = f_readiness.result()
        status_raw = f_status.result()
        body_raw = f_body.result()
        rhr_raw = f_rhr.result()

    readiness = None
    item = readiness_raw[0] if isinstance(readiness_raw, list) and readiness_raw else readiness_raw
    if isinstance(item, dict):
        readiness = {
            "score": item.get("score"),
            "level": item.get("level"),
            "feedback_short": item.get("feedbackShort"),
            "feedback_long": item.get("feedbackLong"),
            "recovery_time_hours": item.get("recoveryTime"),
            "sleep_score": item.get("sleepScore"),
            "hrv_weekly_avg": item.get("hrvWeeklyAverage"),
        }

    hrv_daily = []
    for day in dates:
        raw = hrv_raw.get(day)
        if not isinstance(raw, dict):
            continue
        summary = raw.get("hrvSummary") or {}
        if summary.get("lastNightAvg") is None and summary.get("weeklyAvg") is None:
            continue
        hrv_daily.append(
            {
                "date": day,
                "last_night_avg_ms": summary.get("lastNightAvg"),
                "weekly_avg_ms": summary.get("weeklyAvg"),
                "status": summary.get("status"),
            }
        )
    hrv_values = [
        entry["last_night_avg_ms"]
        for entry in hrv_daily
        if isinstance(entry.get("last_night_avg_ms"), (int, float))
    ]

    sleep_hours = []
    sleep_scores = []
    for day in dates:
        raw = sleep_raw.get(day)
        if not isinstance(raw, dict):
            continue
        dto = raw.get("dailySleepDTO") or {}
        seconds = dto.get("sleepTimeSeconds")
        if isinstance(seconds, (int, float)) and seconds > 0:
            sleep_hours.append(seconds / 3600)
        overall = (dto.get("sleepScores") or {}).get("overall")
        score = overall.get("value") if isinstance(overall, dict) else None
        if isinstance(score, (int, float)):
            sleep_scores.append(score)

    body_battery = None
    if isinstance(body_raw, list) and body_raw and isinstance(body_raw[-1], dict):
        latest = body_raw[-1]
        body_battery = {
            "charged": latest.get("charged"),
            "drained": latest.get("drained"),
            "highest": latest.get("highestBatteryLevel") or latest.get("highest"),
            "lowest": latest.get("lowestBatteryLevel") or latest.get("lowest"),
            "end_of_day": latest.get("endOfDayBatteryLevel"),
        }

    resting_heart_rate = _extract_resting_heart_rate_bpm(rhr_raw)

    training_status = None
    if isinstance(status_raw, dict):
        latest_map = (
            status_raw.get("mostRecentTrainingStatus") or {}
        ).get("latestTrainingStatusData") or {}
        if latest_map:
            first = next(iter(latest_map.values()))
            if isinstance(first, dict):
                training_status = {
                    "status": first.get("trainingStatus"),
                    "feedback": first.get("trainingStatusFeedbackPhrase"),
                    "fitness_trend": first.get("fitnessTrend"),
                }

    return {
        "date": today,
        "training_readiness": readiness,
        "hrv": {
            "weekly_avg_ms": round_number(sum(hrv_values) / len(hrv_values), 1)
            if hrv_values
            else None,
            "status_latest": hrv_daily[0]["status"] if hrv_daily else None,
            "daily": hrv_daily,
        },
        "sleep": {
            "weekly_avg_hours": round_number(sum(sleep_hours) / len(sleep_hours), 2)
            if sleep_hours
            else None,
            "weekly_avg_score": round_number(sum(sleep_scores) / len(sleep_scores), 1)
            if sleep_scores
            else None,
        },
        "body_battery_today": body_battery,
        "resting_heart_rate_bpm": resting_heart_rate,
        "training_status": training_status,
        **_errors_payload(errors),
    }


def get_sleep(
    days: Annotated[int, Field(ge=1, le=30, description="Lookback window in days.")] = 7,
) -> dict[str, Any]:
    """Sleep duration and sleep scores for the last N days."""
    dates = date_range_iso(days)
    errors: ErrorList = []
    daily = []
    for day, raw in zip(dates, _fetch_days(dates, lambda d: _sleep_day(d, errors)), strict=True):
        dto = raw.get("dailySleepDTO") or {}
        seconds = dto.get("sleepTimeSeconds")
        scores = dto.get("sleepScores") or {}
        overall = scores.get("overall") if isinstance(scores, dict) else None
        daily.append(
            {
                "date": day,
                "hours": round_number(seconds / 3600, 2)
                if isinstance(seconds, (int, float))
                else None,
                "score": overall.get("value") if isinstance(overall, dict) else None,
            }
        )
    valid_hours = [d["hours"] for d in daily if isinstance(d.get("hours"), (int, float))]
    valid_scores = [d["score"] for d in daily if isinstance(d.get("score"), (int, float))]
    return {
        "period_days": len(dates),
        "avg_hours": round_number(sum(valid_hours) / len(valid_hours), 2)
        if valid_hours
        else None,
        "avg_score": round_number(sum(valid_scores) / len(valid_scores), 1)
        if valid_scores
        else None,
        "daily": daily,
        **_errors_payload(errors),
    }


def get_resting_heart_rate(
    days: Annotated[int, Field(ge=1, le=30, description="Lookback window in days.")] = 30,
) -> dict[str, Any]:
    """Daily resting heart rate with 7-day and 30-day trend summaries, up to 30 days."""
    safe_days = max(1, min(days, 30))
    dates = date_range_iso(safe_days)
    errors: ErrorList = []
    daily = []
    for day, raw in zip(dates, _fetch_days(dates, lambda d: _rhr_day(d, errors)), strict=True):
        daily.append({"date": day, "bpm": _extract_resting_heart_rate_bpm(raw)})

    values = [item["bpm"] for item in daily if isinstance(item.get("bpm"), int)]
    week_values = [item["bpm"] for item in daily[:7] if isinstance(item.get("bpm"), int)]
    month_values = [item["bpm"] for item in daily[:30] if isinstance(item.get("bpm"), int)]
    latest = next((item for item in daily if isinstance(item.get("bpm"), int)), None)
    latest_bpm = latest["bpm"] if latest else None
    weekly_avg = _avg(week_values)
    monthly_avg = _avg(month_values)

    return {
        "period_days": safe_days,
        "latest": latest,
        "latest_bpm": latest_bpm,
        "weekly_avg_bpm": weekly_avg,
        "monthly_avg_bpm": monthly_avg,
        "min_bpm": min(values) if values else None,
        "max_bpm": max(values) if values else None,
        "delta_latest_vs_weekly_avg_bpm": round_number(latest_bpm - weekly_avg, 1)
        if isinstance(latest_bpm, int) and isinstance(weekly_avg, (int, float))
        else None,
        "delta_latest_vs_monthly_avg_bpm": round_number(latest_bpm - monthly_avg, 1)
        if isinstance(latest_bpm, int) and isinstance(monthly_avg, (int, float))
        else None,
        "daily": daily,
        **_errors_payload(errors),
    }


def get_stress(
    days: Annotated[int, Field(ge=1, le=30, description="Lookback window in days.")] = 7,
) -> dict[str, Any]:
    """Daily all-day stress levels and stress duration buckets."""
    dates = date_range_iso(days)
    errors: ErrorList = []
    daily = []
    for day, raw in zip(dates, _fetch_days(dates, lambda d: _stress_day(d, errors)), strict=True):
        daily.append(
            {
                "date": day,
                "stress_avg": raw.get("avgStressLevel") or raw.get("overallStressLevel"),
                "max_stress": raw.get("maxStressLevel"),
                "rest_minutes": round_number((raw.get("restStressDuration") or 0) / 60, 1),
                "low_minutes": round_number((raw.get("lowStressDuration") or 0) / 60, 1),
                "medium_minutes": round_number(
                    (raw.get("mediumStressDuration") or 0) / 60, 1
                ),
                "high_minutes": round_number((raw.get("highStressDuration") or 0) / 60, 1),
                "activity_minutes": round_number(
                    (raw.get("activityStressDuration") or 0) / 60, 1
                ),
            }
        )
    valid = [d["stress_avg"] for d in daily if isinstance(d.get("stress_avg"), (int, float))]
    return {
        "period_days": len(dates),
        "period_avg_stress": round_number(sum(valid) / len(valid), 1) if valid else None,
        "daily": daily,
        **_errors_payload(errors),
    }


def _fetch_recent_activities(days: int, errors: ErrorList | None = None) -> list[dict[str, Any]]:
    cutoff = date_range_iso(days)[-1]
    activities = []
    for item in _activities_raw(200, errors):
        started = item.get("startTimeLocal") or ""
        if started[:10] < cutoff:
            continue
        normalized = normalize_activity(item)
        if normalized:
            activities.append(normalized)
    activities.sort(key=lambda item: item.get("date") or "", reverse=True)
    return activities


def _recent_activity_dates(days: int = 120, errors: ErrorList | None = None) -> list[str]:
    dates: list[str] = []
    cutoff = date_range_iso(days)[-1]
    for item in _activities_raw(200, errors):
        started = item.get("startTimeLocal") or ""
        day = started[:10]
        if not day or day < cutoff or day in dates:
            continue
        dates.append(day)
    return dates


def _latest_max_metrics(
    errors: ErrorList | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    candidate_dates = [today_iso(), *_recent_activity_dates(errors=errors)]
    seen: set[str] = set()
    for day in candidate_dates:
        if day in seen:
            continue
        seen.add(day)
        raw = _max_metrics(day, errors)
        item = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(item, dict) and item:
            return day, item
    return None, None


def get_recent_activities(
    days: Annotated[
        int, Field(ge=1, le=365, description="How many days back to include.")
    ] = 14,
    limit: Annotated[
        int, Field(ge=1, le=200, description="Maximum number of activities to return.")
    ] = 50,
) -> dict[str, Any]:
    """Recent Garmin activities with normalized sport-aware summary fields."""
    safe_limit = max(1, min(limit, 200))
    safe_days = max(1, min(days, 365))
    errors: ErrorList = []
    activities = _fetch_recent_activities(safe_days, errors)
    return {
        "period_days": safe_days,
        "count": min(len(activities), safe_limit),
        "activities": activities[:safe_limit],
        **_errors_payload(errors),
    }


def get_activity_detail(activity_id: int) -> dict[str, Any]:
    """Detailed summary for one activity by Garmin activity ID."""
    client = _client()
    manager = get_manager()
    errors: ErrorList = []
    raw = manager.cached(
        f"activity_detail:{activity_id}",
        lambda: manager.safe_call(
            lambda: client.get_activity(activity_id),
            default={},
            errors=errors,
            label=f"activity:{activity_id}",
        ),
    )
    if not isinstance(raw, dict) or not raw:
        return {
            "activity_id": activity_id,
            "error": "activity not found or inaccessible",
            **_errors_payload(errors),
        }
    summary = raw.get("summaryDTO") or raw.get("summary") or raw
    type_key = activity_type_key(raw)
    return {
        "activity_id": activity_id,
        "name": raw.get("activityName") or summary.get("activityName"),
        "sport": sport_bucket(type_key),
        "type_key": type_key,
        "summary": normalize_activity(summary) or summary,
        "training_effect": {
            "aerobic": summary.get("trainingEffect") or summary.get("aerobicTrainingEffect"),
            "anaerobic": summary.get("anaerobicTrainingEffect"),
            "label": summary.get("trainingEffectLabel"),
            "aerobic_message": summary.get("aerobicTrainingEffectMessage"),
            "anaerobic_message": summary.get("anaerobicTrainingEffectMessage"),
        },
        "raw_keys": sorted(raw.keys())[:80],
        **_errors_payload(errors),
    }


def _run_activities(days: int, errors: ErrorList | None = None) -> list[dict[str, Any]]:
    return [
        activity
        for activity in _fetch_recent_activities(days, errors)
        if activity.get("sport") == "run"
    ]


def _pace_seconds_from_activity(activity: dict[str, Any]) -> float | None:
    distance = activity.get("distance_km")
    duration = activity.get("duration_min")
    if not isinstance(distance, (int, float)) or not isinstance(duration, (int, float)):
        return None
    if distance <= 0 or duration <= 0:
        return None
    return (duration * 60) / distance


def _format_pace(seconds_per_km: float | None) -> str | None:
    if seconds_per_km is None:
        return None
    minutes = int(seconds_per_km // 60)
    seconds = int(seconds_per_km % 60)
    return f"{minutes}:{seconds:02d}/km"


def _month_key(activity: dict[str, Any]) -> str:
    date_value = activity.get("date") or ""
    return str(date_value)[:7] if date_value else "unknown"


def get_running_summary(
    days: Annotated[
        int, Field(ge=1, le=365, description="Lookback window in days.")
    ] = 90,
) -> dict[str, Any]:
    """Running summary: sessions, distance, pace, HR, longest run, fastest run, monthly split."""
    safe_days = max(1, min(days, 365))
    errors: ErrorList = []
    runs = _run_activities(safe_days, errors)
    total_distance = sum(activity.get("distance_km") or 0 for activity in runs)
    total_minutes = sum(activity.get("duration_min") or 0 for activity in runs)
    hr_values = [
        activity["hr_avg"]
        for activity in runs
        if isinstance(activity.get("hr_avg"), (int, float))
    ]
    longest = max(runs, key=lambda activity: activity.get("distance_km") or 0, default=None)
    paced_runs = [
        (activity, _pace_seconds_from_activity(activity))
        for activity in runs
        if _pace_seconds_from_activity(activity) is not None
    ]
    fastest = min(paced_runs, key=lambda item: item[1] or 999999, default=(None, None))[0]
    return {
        "period_days": safe_days,
        "sessions": len(runs),
        "total_distance_km": round_number(total_distance, 2),
        "total_duration_hours": round_number(total_minutes / 60, 2),
        "average_pace": _format_pace((total_minutes * 60) / total_distance)
        if total_distance
        else None,
        "average_hr": round_number(sum(hr_values) / len(hr_values), 0) if hr_values else None,
        "longest_run": _compact_activity(longest),
        "fastest_run": _compact_activity(fastest),
        "monthly": get_monthly_running_stats(months=max(1, min(12, (safe_days + 30) // 31)))[
            "months"
        ],
        **_errors_payload(errors),
    }


def get_monthly_running_stats(
    months: Annotated[
        int, Field(ge=1, le=12, description="How many recent months to summarize.")
    ] = 3,
) -> dict[str, Any]:
    """Monthly running stats for the last N calendar-ish months based on recent activities."""
    safe_months = max(1, min(months, 12))
    errors: ErrorList = []
    runs = _run_activities(safe_months * 31, errors)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        buckets[_month_key(run)].append(run)
    months_out = []
    for month in sorted(buckets.keys(), reverse=True)[:safe_months]:
        items = buckets[month]
        distance = sum(item.get("distance_km") or 0 for item in items)
        minutes = sum(item.get("duration_min") or 0 for item in items)
        hr_values = [
            item["hr_avg"] for item in items if isinstance(item.get("hr_avg"), (int, float))
        ]
        months_out.append(
            {
                "month": month,
                "sessions": len(items),
                "total_distance_km": round_number(distance, 2),
                "total_duration_hours": round_number(minutes / 60, 2),
                "average_pace": _format_pace((minutes * 60) / distance)
                if distance
                else None,
                "average_hr": round_number(sum(hr_values) / len(hr_values), 0)
                if hr_values
                else None,
            }
        )
    return {"months_requested": safe_months, "months": months_out, **_errors_payload(errors)}


def _compact_activity(activity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not activity:
        return None
    return {
        "activity_id": activity.get("activity_id"),
        "name": activity.get("name"),
        "date": activity.get("date"),
        "distance_km": activity.get("distance_km"),
        "duration": activity.get("duration"),
        "pace": _format_pace(_pace_seconds_from_activity(activity)),
        "hr_avg": activity.get("hr_avg"),
    }


def get_recent_load(
    days: Annotated[
        int, Field(ge=1, le=365, description="Lookback window in days.")
    ] = 28,
) -> dict[str, Any]:
    """Training volume aggregated by sport over the last N days."""
    safe_days = max(1, min(days, 365))
    errors: ErrorList = []
    activities = _fetch_recent_activities(safe_days, errors)
    buckets: dict[str, dict[str, Any]] = {}
    for activity in activities:
        sport = activity.get("sport") or "other"
        bucket = buckets.setdefault(
            sport, {"sessions": 0, "total_km": 0.0, "total_minutes": 0.0, "hr_sum": 0, "hr_n": 0}
        )
        bucket["sessions"] += 1
        bucket["total_km"] += activity.get("distance_km") or 0
        bucket["total_minutes"] += activity.get("duration_min") or 0
        if isinstance(activity.get("hr_avg"), (int, float)):
            bucket["hr_sum"] += activity["hr_avg"]
            bucket["hr_n"] += 1
    by_sport = {}
    for sport, bucket in buckets.items():
        by_sport[sport] = {
            "sessions": bucket["sessions"],
            "total_km": round_number(bucket["total_km"], 2),
            "total_minutes": round_number(bucket["total_minutes"], 1),
            "total_hours": round_number(bucket["total_minutes"] / 60, 2),
            "avg_hr": round_number(bucket["hr_sum"] / bucket["hr_n"], 0)
            if bucket["hr_n"]
            else None,
        }
    return {"period_days": safe_days, "by_sport": by_sport, **_errors_payload(errors)}


def get_training_load() -> dict[str, Any]:
    """Garmin training load status, acute/chronic load, and load focus."""
    today = today_iso()
    errors: ErrorList = []
    raw = _training_status(today, errors)
    if not raw:
        return {
            "date": today,
            "source": "garmin_training_status",
            "available": False,
            "reason": "training status endpoint returned no data",
            **_errors_payload(errors),
        }

    acute = chronic = ratio = status = None
    load_balance = raw.get("mostRecentTrainingLoadBalance")
    if isinstance(load_balance, dict):
        acute = round_number(
            load_balance.get("acuteTrainingLoad")
            or load_balance.get("dailyTrainingLoadAcute")
            or load_balance.get("load")
            or load_balance.get("trainingLoad"),
            1,
        )
        chronic = round_number(
            load_balance.get("chronicTrainingLoad")
            or load_balance.get("dailyTrainingLoadChronic"),
            1,
        )
        ratio = round_number(
            load_balance.get("acuteChronicWorkloadRatio")
            or load_balance.get("dailyAcuteChronicWorkloadRatio"),
            2,
        )
        status = load_balance.get("acwrStatus") or load_balance.get("loadStatus")

    latest_map = (raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
    if latest_map:
        first = next(iter(latest_map.values()))
        if isinstance(first, dict):
            atl = first.get("acuteTrainingLoadDTO") or {}
            acute = acute or round_number(atl.get("dailyTrainingLoadAcute"), 1)
            chronic = chronic or round_number(atl.get("dailyTrainingLoadChronic"), 1)
            ratio = ratio or round_number(atl.get("dailyAcuteChronicWorkloadRatio"), 2)
            status = status or atl.get("acwrStatus")

    return {
        "date": today,
        "source": "garmin_training_status",
        "available": any(value is not None for value in [acute, chronic, ratio, status]),
        "acute_load": acute,
        "chronic_load": chronic,
        "load_ratio": ratio,
        "acwr_status": status,
        "raw_sections_present": {
            "mostRecentTrainingLoadBalance": raw.get("mostRecentTrainingLoadBalance") is not None,
            "mostRecentTrainingStatus": raw.get("mostRecentTrainingStatus") is not None,
        },
        **_errors_payload(errors),
    }


def get_fitness() -> dict[str, Any]:
    """VO2 max, cycling FTP, and race predictions."""
    client = _client()
    manager = get_manager()
    errors: ErrorList = []
    race_raw = manager.cached(
        "race_predictions",
        lambda: manager.safe_call(
            lambda: client.get_race_predictions(),
            default=None,
            errors=errors,
            label="race_predictions",
        ),
    )
    ftp_raw = manager.cached(
        "cycling_ftp",
        lambda: manager.safe_call(
            lambda: client.get_cycling_ftp(),
            default=None,
            errors=errors,
            label="cycling_ftp",
        ),
    )

    vo2_run = vo2_bike = None
    metrics_date, item = _latest_max_metrics(errors)
    if isinstance(item, dict):
        generic = item.get("generic") or {}
        cycling = item.get("cycling") or {}
        vo2_run = round_number(generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"), 1)
        vo2_bike = round_number(cycling.get("vo2MaxPreciseValue") or cycling.get("vo2MaxValue"), 1)

    race_item = race_raw[-1] if isinstance(race_raw, list) and race_raw else race_raw
    race = {}
    if isinstance(race_item, dict):
        for key_in, key_out in [
            ("time5K", "5k"),
            ("time10K", "10k"),
            ("timeHalfMarathon", "half_marathon"),
            ("timeMarathon", "marathon"),
        ]:
            seconds = race_item.get(key_in)
            if isinstance(seconds, (int, float)) and seconds > 0:
                race[key_out] = {"seconds": int(seconds)}

    return {
        "metrics_date": metrics_date,
        "vo2_max_running": vo2_run,
        "vo2_max_cycling": vo2_bike,
        "cycling_ftp_w": ftp_raw.get("functionalThresholdPower")
        if isinstance(ftp_raw, dict)
        else ftp_raw,
        "race_predictions": race or None,
        **_errors_payload(errors),
    }


def get_zones() -> dict[str, Any]:
    """Heart-rate zones and thresholds from Garmin user settings when available."""
    client = _client()
    errors: ErrorList = []
    raw = _endpoint(
        "user_profile",
        "user_profile",
        lambda: client.get_user_profile(),
        {},
        errors,
    )
    user_data = raw.get("userData") if isinstance(raw, dict) else None
    zones: dict[str, Any] = {}
    if isinstance(user_data, dict):
        for key, value in user_data.items():
            if not isinstance(key, str) or value in (None, [], {}):
                continue
            if _ZONE_KEY_RE.search(key):
                zones[key] = value
    return {
        "available": bool(zones),
        "source": "garmin_user_settings",
        "zones": zones or None,
        "reason": None if zones else "user settings did not expose zone data for this account",
        **_errors_payload(errors),
    }


def get_personal_records() -> dict[str, Any]:
    """Personal records returned by Garmin Connect."""
    client = _client()
    manager = get_manager()
    errors: ErrorList = []
    getter = getattr(client, "get_personal_record", None) or getattr(
        client, "get_personal_records", None
    )
    if getter is None:
        return {
            "count": 0,
            "records": [],
            "available": False,
            "reason": "garminconnect client does not expose a personal records endpoint",
        }
    raw = manager.cached(
        "personal_records",
        lambda: manager.safe_call(getter, default=[], errors=errors, label="personal_records"),
    )
    if isinstance(raw, dict):
        raw = (
            raw.get("personalRecords")
            or raw.get("userPersonalRecords")
            or raw.get("records")
            or raw.get("prRecords")
            or []
        )
    type_map = _personal_record_type_map(client, manager)
    records = []
    if isinstance(raw, list):
        for record in raw:
            if not isinstance(record, dict):
                continue
            type_id = _personal_record_type_id(record.get("typeId"))
            type_info = type_map.get(type_id) if type_id is not None else None
            label_key = (
                _personal_record_label_key(record.get("prTypeLabelKey"))
                or _personal_record_label_key(record.get("typeLabelKey"))
                or _personal_record_label_key(type_info)
            )
            label = _personal_record_label(label_key, type_id)
            records.append(
                {
                    "type_id": type_id,
                    "name": label,
                    "label": label,
                    "label_key": label_key,
                    "sport": type_info.get("sport") if isinstance(type_info, dict) else None,
                    "value": record.get("value"),
                    "date": record.get("prStartTimeGmtFormatted") or record.get("prStartTimeGmt"),
                }
            )
    return {"count": len(records), "records": records, "available": True, **_errors_payload(errors)}


def get_health_summary(
    days: Annotated[
        int, Field(ge=1, le=30, description="Lookback window in days.")
    ] = 7,
) -> dict[str, Any]:
    """Compact health snapshot combining recovery, sleep, and stress."""
    return {
        "date": today_iso(),
        "recovery": get_recovery(),
        "sleep": get_sleep(days),
        "resting_heart_rate": get_resting_heart_rate(min(max(days, 1), 30)),
        "stress": get_stress(days),
    }


def get_full_snapshot(
    activity_days: Annotated[
        int, Field(ge=1, le=365, description="Activity window in days.")
    ] = 14,
    load_days: Annotated[
        int, Field(ge=1, le=365, description="Training load window in days.")
    ] = 28,
) -> dict[str, Any]:
    """Comprehensive Garmin data snapshot for holistic analysis."""
    sections: dict[str, Callable[[], dict[str, Any]]] = {
        "recovery": get_recovery,
        "sleep": lambda: get_sleep(7),
        "resting_heart_rate": lambda: get_resting_heart_rate(30),
        "stress": lambda: get_stress(7),
        "recent_activities": lambda: get_recent_activities(activity_days),
        "recent_load": lambda: get_recent_load(load_days),
        "training_load": get_training_load,
        "fitness": get_fitness,
        "running_summary": lambda: get_running_summary(activity_days),
        "zones": get_zones,
        "personal_records": get_personal_records,
    }
    out: dict[str, Any] = {
        "snapshot_date": today_iso(),
        "activity_window_days": activity_days,
        "load_window_days": load_days,
    }
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {name: ex.submit(_safe_section, fn) for name, fn in sections.items()}
        for name, future in futures.items():
            out[name] = future.result()
    return out


def _safe_section(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


TOOL_SPECS = [
    ToolSpec("get_recovery", get_recovery.__doc__ or "", get_recovery, {}),
    ToolSpec(
        "get_sleep",
        get_sleep.__doc__ or "",
        get_sleep,
        {"days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30}},
    ),
    ToolSpec(
        "get_resting_heart_rate",
        get_resting_heart_rate.__doc__ or "",
        get_resting_heart_rate,
        {"days": {"type": "integer", "default": 30, "minimum": 1, "maximum": 30}},
    ),
    ToolSpec(
        "get_stress",
        get_stress.__doc__ or "",
        get_stress,
        {"days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30}},
    ),
    ToolSpec(
        "get_recent_activities",
        get_recent_activities.__doc__ or "",
        get_recent_activities,
        {
            "days": {"type": "integer", "default": 14, "minimum": 1, "maximum": 365},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        },
    ),
    ToolSpec(
        "get_activity_detail",
        get_activity_detail.__doc__ or "",
        get_activity_detail,
        {"activity_id": {"type": "integer"}},
    ),
    ToolSpec(
        "get_recent_load",
        get_recent_load.__doc__ or "",
        get_recent_load,
        {"days": {"type": "integer", "default": 28, "minimum": 1, "maximum": 365}},
    ),
    ToolSpec("get_training_load", get_training_load.__doc__ or "", get_training_load, {}),
    ToolSpec("get_fitness", get_fitness.__doc__ or "", get_fitness, {}),
    ToolSpec("get_zones", get_zones.__doc__ or "", get_zones, {}),
    ToolSpec("get_personal_records", get_personal_records.__doc__ or "", get_personal_records, {}),
    ToolSpec(
        "get_running_summary",
        get_running_summary.__doc__ or "",
        get_running_summary,
        {"days": {"type": "integer", "default": 90, "minimum": 1, "maximum": 365}},
    ),
    ToolSpec(
        "get_monthly_running_stats",
        get_monthly_running_stats.__doc__ or "",
        get_monthly_running_stats,
        {"months": {"type": "integer", "default": 3, "minimum": 1, "maximum": 12}},
    ),
    ToolSpec(
        "get_health_summary",
        get_health_summary.__doc__ or "",
        get_health_summary,
        {"days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30}},
    ),
    ToolSpec(
        "get_full_snapshot",
        get_full_snapshot.__doc__ or "",
        get_full_snapshot,
        {
            "activity_days": {"type": "integer", "default": 14, "minimum": 1, "maximum": 365},
            "load_days": {"type": "integer", "default": 28, "minimum": 1, "maximum": 365},
        },
    ),
]

TOOLS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def tool_schema(spec: ToolSpec) -> dict[str, Any]:
    required = [name for name, schema in spec.parameters.items() if "default" not in schema]
    return {
        "type": "object",
        "properties": spec.parameters,
        "required": required,
        "additionalProperties": False,
    }
