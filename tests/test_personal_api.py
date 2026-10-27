"""Personal API backend: token handling, endpoint mapping and backend selection."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.errors import (
    PersonalApiAuthError,
    PersonalApiRateLimitError,
    PersonalApiUnsupported,
)
from mcp_garmin_connect.garmin_client import reset_manager
from mcp_garmin_connect.personal_api import (
    PersonalApiAuthenticator,
    PersonalApiBackend,
    PersonalApiClient,
    jwt_expiry,
)
from mcp_garmin_connect.tools import (
    download_activity_file,
    get_body_composition,
    get_fitness_age,
    get_hydration,
    get_spo2,
    get_steps_history,
)

API_KEY = "test-personal-key"


def _jwt(exp: int | None = 1000) -> str:
    def seg(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    claims = {} if exp is None else {"exp": exp}
    return f"{seg({'alg': 'none'})}.{seg(claims)}.signature"


def _authenticator(tmp_path: Path, handler: httpx.MockTransport) -> PersonalApiAuthenticator:
    client = httpx.Client(transport=handler)
    return PersonalApiAuthenticator(
        API_KEY,
        cache_path=str(tmp_path / "token.json"),
        client=client,
    )


def _token_response(exp_offset: int = 86_400) -> httpx.Response:
    return httpx.Response(200, json={"access_token": _jwt(int(time.time()) + exp_offset)})


def test_jwt_expiry_reads_exp_claim() -> None:
    assert jwt_expiry(_jwt(1_234_567)) == 1_234_567
    assert jwt_expiry(_jwt(None)) is None
    assert jwt_expiry("not-a-jwt") is None


def test_token_is_cached_and_reused(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _token_response()

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    first = auth.obtain_token()
    second = auth.obtain_token()

    assert first.access_token == second.access_token
    assert len(calls) == 1, "second call must reuse the cached bearer token"
    assert (tmp_path / "token.json").exists()
    mode = (tmp_path / "token.json").stat().st_mode & 0o777
    assert mode == 0o600, "bearer token cache must not be world readable"


def test_expired_cache_is_refreshed(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _token_response()

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    (tmp_path / "token.json").write_text(
        json.dumps(
            {
                "api_key_fingerprint": auth._read_cache and _fingerprint(API_KEY),
                "access_token": _jwt(int(time.time()) - 60),
                "expires_at": int(time.time()) - 60,
            }
        ),
        encoding="utf-8",
    )

    token = auth.obtain_token()

    assert token.is_fresh()
    assert len(calls) == 1


def test_cache_from_a_different_key_is_ignored(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _token_response()

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    (tmp_path / "token.json").write_text(
        json.dumps(
            {
                "api_key_fingerprint": "deadbeefdeadbeef",
                "access_token": _jwt(int(time.time()) + 86_400),
                "expires_at": int(time.time()) + 86_400,
            }
        ),
        encoding="utf-8",
    )

    auth.obtain_token()

    assert len(calls) == 1, "a token issued for another key must never be reused"


def test_rejected_key_raises_auth_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(PersonalApiAuthError):
        auth.obtain_token()


def test_token_endpoint_rate_limit_maps_to_rate_limit_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(PersonalApiRateLimitError):
        auth.obtain_token()


def test_data_401_refreshes_token_and_retries(tmp_path: Path) -> None:
    tokens: list[str] = []
    data_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            tokens.append("issued")
            return _token_response()
        data_calls.append(str(request.url))
        if len(data_calls) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    client = PersonalApiClient(auth)

    assert client.get("/activitylist-service/activities/search/activities") == {"ok": True}
    assert len(data_calls) == 2
    assert len(tokens) == 2, "401 must trigger exactly one forced token refresh"


def _backend(tmp_path: Path, routes: dict[str, Any]) -> PersonalApiBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return _token_response()
        for prefix, payload in routes.items():
            if request.url.path.startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "no route", "path": request.url.path})

    auth = _authenticator(tmp_path, httpx.MockTransport(handler))
    return PersonalApiBackend(PersonalApiClient(auth))


def test_sleep_payload_is_wrapped_for_the_tool_layer(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        {
            "/sleep-service/sleep/dailySleep": {
                "sleepTimeSeconds": 25200,
                "sleepScores": {"overall": {"value": 88}},
            }
        },
    )
    raw = backend.get_sleep_data("2026-10-26")
    assert raw["dailySleepDTO"]["sleepTimeSeconds"] == 25200

    enveloped = _backend(
        tmp_path,
        {"/sleep-service/sleep/dailySleep": {"dailySleepDTO": {"sleepTimeSeconds": 1}}},
    ).get_sleep_data("2026-10-26")
    assert enveloped["dailySleepDTO"]["sleepTimeSeconds"] == 1


def test_resting_heart_rate_comes_from_daily_summaries(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        {"/usersummary-service/v2/dailysummaries": [{"restingHeartRate": 58}]},
    )
    assert backend.get_rhr_day("2026-10-26")["restingHeartRate"] == 58


def test_stress_and_body_battery_shapes(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        {
            "/usersummary-service/stats/stress/daily": [
                {"calendarDate": "2026-10-26", "avgStressLevel": 41, "maxStressLevel": 99}
            ],
            "/wellness-service/wellness/bodyBattery/reports/daily": [
                {"date": "2026-10-26T00:00:00.0", "charged": 76, "drained": 63}
            ],
        },
    )
    assert backend.get_all_day_stress("2026-10-26")["avgStressLevel"] == 41
    assert backend.get_body_battery("2026-10-19", "2026-10-26")[0]["charged"] == 76


def test_splits_are_built_from_split_summaries(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        {
            "/activity-service/activity/123": {
                "activityId": 123,
                "splitSummaries": [{"distance": 1000.0, "duration": 555.0, "averageHR": 150}],
            }
        },
    )
    splits = backend.get_activity_splits(123)
    assert splits["lapDTOs"][0]["averageHR"] == 150


def test_derived_metrics_are_reported_as_unsupported(tmp_path: Path) -> None:
    backend = _backend(tmp_path, {})
    for method in ("get_max_metrics", "get_training_status", "get_race_predictions"):
        with pytest.raises(PersonalApiUnsupported):
            getattr(backend, method)("2026-10-26")


def test_auth_mode_selection() -> None:
    base = Settings.from_env()
    with_key = replace(
        base, garmin_personal_api_key=API_KEY, garmin_auth_mode="auto", garmin_demo=False
    )
    without_key = replace(
        base, garmin_personal_api_key=None, garmin_auth_mode="auto", garmin_demo=False
    )
    forced_unofficial = replace(with_key, garmin_auth_mode="unofficial")
    demo = replace(with_key, garmin_demo=True)

    assert with_key.resolved_auth_mode() == "personal"
    assert without_key.resolved_auth_mode() == "unofficial"
    assert forced_unofficial.resolved_auth_mode() == "unofficial"
    assert demo.resolved_auth_mode() == "demo"


def _personal_tools_use_demo(tmp_path: Path) -> None:
    reset_manager(replace(Settings.from_env(), garmin_demo=True))

    composition = get_body_composition(days=7)
    assert composition["latest_weight_kg"] == 71.2
    assert composition["days_with_data"] == 7

    assert get_spo2(days=3)["avg_spo2"] == 96.0
    assert get_hydration(days=3)["daily"][0]["intake_ml"] == 2400
    assert get_steps_history(days=3)["avg_steps"] == 8280
    assert get_fitness_age()["fitness_age"] == 19.4

    target = tmp_path / "run.zip"
    written = download_activity_file(900001, save_path=str(target))
    assert written["bytes"] > 0
    assert target.read_bytes().startswith(b"PK")


def test_personal_tools_work_in_demo_mode(tmp_path: Path) -> None:
    _personal_tools_use_demo(tmp_path)


def test_personal_tools_explain_themselves_on_the_unofficial_backend() -> None:
    reset_manager(
        replace(
            Settings.from_env(),
            garmin_demo=False,
            garmin_personal_api_key=None,
            garmin_auth_mode="unofficial",
        )
    )

    for payload in (
        get_body_composition(days=7),
        get_spo2(days=3),
        get_hydration(days=3),
        get_steps_history(days=3),
        get_fitness_age(),
        download_activity_file(1),
    ):
        assert payload["error"] == "personal api required"
        assert "GARMIN_PERSONAL_API_KEY" in payload["hint"]


def _fingerprint(key: str) -> str:
    import hashlib

    return hashlib.sha256(key.encode()).hexdigest()[:16]
