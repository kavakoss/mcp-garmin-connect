from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .garmin_client import date_range_iso, get_manager, today_iso
from .normalizers import (
    activity_type_key,
    normalize_activity,
    round_number,
    sport_bucket,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    function: Callable[..., dict[str, Any]]
    parameters: dict[str, Any]


def _client() -> Any:
    return get_manager().client()


def _manager_call(key: str, factory: Callable[[], Any]) -> Any:
    return get_manager().cached(key, factory)


def get_recovery() -> dict[str, Any]:
    """Current recovery state: readiness, HRV, sleep, body battery, and status."""
    client = _client()
    today = today_iso()
    dates = date_range_iso(7)
    manager = get_manager()

    def fetch() -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_readiness = ex.submit(manager.safe_call, lambda: client.get_training_readiness(today))
            f_status = ex.submit(manager.safe_call, lambda: client.get_training_status(today))
            f_hrv = {
                day: ex.submit(manager.safe_call, lambda d=day: client.get_hrv_data(d))
                for day in dates
            }
            f_sleep = {
                day: ex.submit(manager.safe_call, lambda d=day: client.get_sleep_data(d))
                for day in dates
            }
            f_body = ex.submit(
                manager.safe_call, lambda: client.get_body_battery(dates[-1], today)
            )
            f_rhr = ex.submit(manager.safe_call, lambda: client.get_resting_heart_rate(today))
            readiness_raw = f_readiness.result()
            status_raw = f_status.result()
            hrv_raw = {day: future.result() for day, future in f_hrv.items()}
            sleep_raw = {day: future.result() for day, future in f_sleep.items()}
            body_raw = f_body.result()
            rhr_raw = f_rhr.result()

        readiness = None
        item = (
            readiness_raw[0]
            if isinstance(readiness_raw, list) and readiness_raw
            else readiness_raw
        )
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

        resting_heart_rate = None
        if isinstance(rhr_raw, dict):
            try:
                metrics = rhr_raw["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
                if metrics:
                    value = metrics[0].get("value")
                    resting_heart_rate = int(value) if isinstance(value, (int, float)) else None
            except (KeyError, TypeError, IndexError):
                resting_heart_rate = None

        training_status = None
        if isinstance(status_raw, dict):
            latest_map = (
                (status_raw.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData")
                or {}
            )
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
        }

    return _manager_call(f"recovery:{today}", fetch)


def get_sleep(days: int = 7) -> dict[str, Any]:
    """Sleep duration and sleep scores for the last N days."""
    client = _client()
    dates = date_range_iso(days)
    manager = get_manager()

    def fetch() -> dict[str, Any]:
        daily = []
        for day in dates:
            raw = manager.safe_call(lambda d=day: client.get_sleep_data(d), default={})
            dto = raw.get("dailySleepDTO") if isinstance(raw, dict) else {}
            dto = dto or {}
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
        }

    return _manager_call(f"sleep:{len(dates)}:{dates[0]}", fetch)


def get_stress(days: int = 7) -> dict[str, Any]:
    """Daily all-day stress levels and stress duration buckets."""
    client = _client()
    dates = date_range_iso(days)
    manager = get_manager()

    def fetch() -> dict[str, Any]:
        daily = []
        for day in dates:
            raw = manager.safe_call(lambda d=day: client.get_all_day_stress(d), default={})
            raw = raw if isinstance(raw, dict) else {}
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
        }

    return _manager_call(f"stress:{len(dates)}:{dates[0]}", fetch)


def _fetch_recent_activities(days: int, limit: int = 200) -> list[dict[str, Any]]:
    client = _client()
    manager = get_manager()
    raw = manager.safe_call(lambda: client.get_activities(0, limit), default=[]) or []
    cutoff = date_range_iso(days)[-1]
    activities = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        started = item.get("startTimeLocal") or ""
        if started[:10] < cutoff:
            continue
        normalized = normalize_activity(item)
        if normalized:
            activities.append(normalized)
    activities.sort(key=lambda item: item.get("date") or "", reverse=True)
    return activities


def _recent_activity_dates(days: int = 120, limit: int = 200) -> list[str]:
    client = _client()
    manager = get_manager()
    raw = manager.safe_call(lambda: client.get_activities(0, limit), default=[]) or []
    dates: list[str] = []
    cutoff = date_range_iso(days)[-1]
    for item in raw:
        if not isinstance(item, dict):
            continue
        started = item.get("startTimeLocal") or ""
        day = started[:10]
        if not day or day < cutoff or day in dates:
            continue
        dates.append(day)
    return dates


def _latest_max_metrics() -> tuple[str | None, dict[str, Any] | None]:
    client = _client()
    manager = get_manager()
    candidate_dates = [today_iso(), *_recent_activity_dates()]
    seen: set[str] = set()
    for day in candidate_dates:
        if day in seen:
            continue
        seen.add(day)
        raw = manager.safe_call(lambda d=day: client.get_max_metrics(d), default=None)
        item = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(item, dict) and item:
            return day, item
    return None, None


def get_recent_activities(days: int = 14, limit: int = 50) -> dict[str, Any]:
    """Recent Garmin activities with normalized sport-aware summary fields."""
    safe_limit = max(1, min(limit, 200))
    safe_days = max(1, min(days, 365))
    activities = _manager_call(
        f"activities:{safe_days}:{safe_limit}", lambda: _fetch_recent_activities(safe_days, 200)
    )
    return {
        "period_days": safe_days,
        "count": min(len(activities), safe_limit),
        "activities": activities[:safe_limit],
    }


def get_activity_detail(activity_id: int) -> dict[str, Any]:
    """Detailed summary for one activity by Garmin activity ID."""
    client = _client()
    manager = get_manager()
    raw = _manager_call(
        f"activity_detail:{activity_id}",
        lambda: manager.safe_call(lambda: client.get_activity(activity_id), default={}),
    )
    if not isinstance(raw, dict) or not raw:
        return {"activity_id": activity_id, "error": "activity not found or inaccessible"}
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
    }


def _run_activities(days: int) -> list[dict[str, Any]]:
    return [
        activity
        for activity in _fetch_recent_activities(days)
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


def get_running_summary(days: int = 90) -> dict[str, Any]:
    """Running summary: sessions, distance, pace, HR, longest run, fastest run, monthly split."""
    safe_days = max(1, min(days, 365))
    runs = _run_activities(safe_days)
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
    }


def get_monthly_running_stats(months: int = 3) -> dict[str, Any]:
    """Monthly running stats for the last N calendar-ish months based on recent activities."""
    safe_months = max(1, min(months, 12))
    runs = _run_activities(safe_months * 31)
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
    return {"months_requested": safe_months, "months": months_out}


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


def get_recent_load(days: int = 28) -> dict[str, Any]:
    """Training volume aggregated by sport over the last N days."""
    safe_days = max(1, min(days, 365))
    activities = _fetch_recent_activities(safe_days)
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
    return {"period_days": safe_days, "by_sport": by_sport}


def get_training_load() -> dict[str, Any]:
    """Garmin training load status, acute/chronic load, and load focus."""
    client = _client()
    today = today_iso()
    manager = get_manager()
    raw = _manager_call(
        f"training_load:{today}",
        lambda: manager.safe_call(lambda: client.get_training_status(today), default={}),
    )
    if not isinstance(raw, dict) or not raw:
        return {
            "date": today,
            "source": "garmin_training_status",
            "available": False,
            "reason": "training status endpoint returned no data",
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
    }


def get_fitness() -> dict[str, Any]:
    """VO2 max, cycling FTP, and race predictions."""
    client = _client()
    manager = get_manager()
    race_raw = manager.safe_call(lambda: client.get_race_predictions(), default=None)
    ftp_raw = manager.safe_call(lambda: client.get_cycling_ftp(), default=None)

    vo2_run = vo2_bike = None
    metrics_date, item = _latest_max_metrics()
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
    }


def get_zones() -> dict[str, Any]:
    """Heart-rate and power zones from Garmin profile data when available."""
    client = _client()
    manager = get_manager()
    hr = manager.safe_call(lambda: client.get_heart_rates(), default=None)
    zones = manager.safe_call(lambda: client.get_user_profile(), default=None)
    power = manager.safe_call(lambda: client.get_cycling_power_zones(), default=None)
    return {
        "heart_rate": hr,
        "profile_zones": zones.get("userData") if isinstance(zones, dict) else zones,
        "power": power,
    }


def get_personal_records() -> dict[str, Any]:
    """Personal records returned by Garmin Connect."""
    client = _client()
    manager = get_manager()
    raw = _manager_call(
        "personal_records", lambda: manager.safe_call(client.get_personal_records, default=[])
    )
    records = []
    if isinstance(raw, list):
        for record in raw:
            if not isinstance(record, dict):
                continue
            records.append(
                {
                    "type_id": record.get("typeId"),
                    "label": record.get("prTypeLabelKey") or record.get("typeLabelKey"),
                    "value": record.get("value"),
                    "date": record.get("prStartTimeGmtFormatted") or record.get("prStartTimeGmt"),
                }
            )
    return {"count": len(records), "records": records}


def get_health_summary(days: int = 7) -> dict[str, Any]:
    """Compact health snapshot combining recovery, sleep, and stress."""
    return {
        "date": today_iso(),
        "recovery": get_recovery(),
        "sleep": get_sleep(days),
        "stress": get_stress(days),
    }


def get_full_snapshot(activity_days: int = 14, load_days: int = 28) -> dict[str, Any]:
    """Comprehensive Garmin data snapshot for holistic analysis."""
    sections: dict[str, Callable[[], dict[str, Any]]] = {
        "recovery": get_recovery,
        "sleep": lambda: get_sleep(7),
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
    required = [
        name for name, schema in spec.parameters.items() if "default" not in schema
    ]
    return {
        "type": "object",
        "properties": spec.parameters,
        "required": required,
        "additionalProperties": False,
    }
