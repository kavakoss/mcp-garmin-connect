"""Garmin Connect **Personal API** backend (official, self-serve).

Garmin opened a personal tier of the Connect Developer Program in October 2026:
you create a key yourself at
https://connect.garmin.com/app/settings/personalApiToken, exchange it for a
24-hour OAuth2 bearer token, and read your own data. No application, no
business entity, no approval queue.

Compared with the email/password flow used by ``garminconnect`` this backend
trades breadth for stability: it is rate-limit friendly and does not fight
Cloudflare/SSO, but it only exposes the documented endpoints. Metrics Garmin
derives on top of an activity (VO2 Max, recovery time, performance condition,
training status/load, race predictions) are **not** in that list, so
``PersonalApiBackend`` raises :class:`PersonalApiUnsupported` for them and the
composite tools degrade to ``None`` plus an ``errors`` entry.

Docs: https://developer.garmin.com/gc-developer-program/personal/personal-api/
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from .errors import (
    PersonalApiAuthError,
    PersonalApiHttpError,
    PersonalApiRateLimitError,
    PersonalApiUnsupported,
)

log = logging.getLogger("mcp-garmin-connect")

DEFAULT_BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
DEFAULT_TOKEN_CACHE = "~/.garminconnect/personal_api_token.json"

# Refresh this long before the bearer token expires so a long tool call never
# dies half way through on a token that lapsed mid-request.
TOKEN_REFRESH_MARGIN_SECONDS = 3600


def jwt_expiry(token: str) -> int | None:
    """Return the ``exp`` claim (epoch seconds) of a JWT, or None if unreadable."""
    try:
        payload = token.split(".")[1]
    except (AttributeError, IndexError):
        return None
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    exp = decoded.get("exp") if isinstance(decoded, dict) else None
    return int(exp) if isinstance(exp, (int, float)) else None


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class BearerToken:
    access_token: str
    expires_at: int | None = None

    def is_fresh(self, margin_seconds: int = TOKEN_REFRESH_MARGIN_SECONDS) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at - margin_seconds > int(time.time())


class PersonalApiAuthenticator:
    """Exchanges a Personal API key for a bearer token and caches it.

    The cache is keyed by a hash of the key so rotating the key cannot serve a
    stale token. Tokens are valid for 24 hours and Garmin does not issue refresh
    tokens, so "refreshing" simply means asking for a new one.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cache_path: str = DEFAULT_TOKEN_CACHE,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise PersonalApiAuthError(
                "GARMIN_PERSONAL_API_KEY is empty. Create a key at "
                "https://connect.garmin.com/app/settings/personalApiToken"
            )
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.cache_path = os.path.expanduser(cache_path)
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> PersonalApiAuthenticator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
            self._owns_client = True
        return self._client

    # -- token cache -------------------------------------------------------
    def _read_cache(self) -> BearerToken | None:
        try:
            with open(self.cache_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("api_key_fingerprint") != _key_fingerprint(self.api_key):
            return None
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        expires_at = payload.get("expires_at")
        return BearerToken(
            access_token=token,
            expires_at=int(expires_at) if isinstance(expires_at, (int, float)) else None,
        )

    def _write_cache(self, token: BearerToken) -> None:
        payload = {
            "api_key_fingerprint": _key_fingerprint(self.api_key),
            "access_token": token.access_token,
            "expires_at": token.expires_at,
            "cached_at": int(time.time()),
        }
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            fd = os.open(self.cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except OSError as exc:  # cache is an optimisation, never a hard failure
            log.warning("Could not cache Personal API token at %s: %s", self.cache_path, exc)

    def clear_cache(self) -> None:
        try:
            os.remove(self.cache_path)
        except OSError:
            return

    # -- token exchange ----------------------------------------------------
    def obtain_token(self, force_refresh: bool = False) -> BearerToken:
        if not force_refresh:
            cached = self._read_cache()
            if cached is not None and cached.is_fresh():
                return cached

        try:
            response = self.http.post(
                f"{self.base_url}{TOKEN_PATH}",
                headers={"Authorization": f"ApiKey {self.api_key}"},
            )
        except httpx.HTTPError as exc:
            raise PersonalApiHttpError(f"Personal API token request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise PersonalApiAuthError(
                "Garmin rejected the Personal API key "
                f"(HTTP {response.status_code}). Keys expire after 30/90/180/365 days — "
                "create a new one at https://connect.garmin.com/app/settings/personalApiToken"
            )
        if response.status_code == 429:
            raise PersonalApiRateLimitError(
                "Garmin rate-limited the Personal API token endpoint. Wait a few minutes."
            )
        if response.status_code >= 400:
            raise PersonalApiHttpError(
                f"Personal API token request failed with HTTP {response.status_code}",
                status_code=response.status_code,
                url=str(response.request.url),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise PersonalApiHttpError("Personal API returned a non-JSON token response") from exc

        token = _extract_access_token(body)
        if not token:
            raise PersonalApiHttpError(
                "Personal API token response contained no access token", status_code=200
            )

        bearer = BearerToken(access_token=token, expires_at=jwt_expiry(token))
        self._write_cache(bearer)
        return bearer


def _extract_access_token(body: Any) -> str | None:
    if isinstance(body, str):
        return body.strip() or None
    if not isinstance(body, dict):
        return None
    for key in ("access_token", "accessToken", "token"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class PersonalApiClient:
    """Thin authenticated GET client for the Personal API host."""

    def __init__(self, authenticator: PersonalApiAuthenticator) -> None:
        self.authenticator = authenticator

    def close(self) -> None:
        self.authenticator.close()

    def __enter__(self) -> PersonalApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        _retry_on_401: bool = True,
    ) -> Any:
        token = self.authenticator.obtain_token()
        url = f"{self.authenticator.base_url}{path}"
        try:
            response = self.authenticator.http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
        except httpx.HTTPError as exc:
            raise PersonalApiHttpError(f"Personal API request failed: {exc}", url=url) from exc

        if response.status_code == 401 and _retry_on_401:
            # A token can be revoked before its exp claim; ask for a new one once.
            log.info("Personal API returned 401, refreshing bearer token")
            self.authenticator.obtain_token(force_refresh=True)
            return self.get(path, params, _retry_on_401=False)
        if response.status_code == 401:
            raise PersonalApiAuthError(
                "Personal API rejected the bearer token. Run "
                "`garmin-mcp personal-api --refresh-token` or delete the token cache."
            )
        if response.status_code == 429:
            raise PersonalApiRateLimitError(
                "Garmin rate-limited the Personal API. Wait a few minutes and retry."
            )
        if response.status_code >= 400:
            raise PersonalApiHttpError(
                f"Personal API request failed with HTTP {response.status_code}",
                status_code=response.status_code,
                url=str(response.request.url),
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        token = self.authenticator.obtain_token()
        url = f"{self.authenticator.base_url}{path}"
        try:
            response = self.authenticator.http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
        except httpx.HTTPError as exc:
            raise PersonalApiHttpError(f"Personal API download failed: {exc}", url=url) from exc
        if response.status_code == 401:
            self.authenticator.obtain_token(force_refresh=True)
            token = self.authenticator.obtain_token()
            try:
                response = self.authenticator.http.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token.access_token}"},
                )
            except httpx.HTTPError as exc:
                raise PersonalApiHttpError(
                    f"Personal API download failed: {exc}", url=url
                ) from exc
        if response.status_code >= 400:
            raise PersonalApiHttpError(
                f"Personal API download failed with HTTP {response.status_code}",
                status_code=response.status_code,
                url=str(response.request.url),
            )
        return response.content


def _first(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
        return {}
    return payload if isinstance(payload, dict) else {}


class PersonalApiBackend:
    """Adapter that gives the Personal API the same surface the tools already use.

    Method names and return shapes mirror the ``garminconnect`` client so
    ``tools.py`` does not need a second code path. Shapes are the same DTOs the
    Garmin web app consumes, with light wrapping where the official endpoint
    returns the inner object instead of the outer envelope.
    """

    backend_name = "personal"

    def __init__(self, client: PersonalApiClient) -> None:
        self._client = client
        self._display_name: str | None = None

    # -- identity ----------------------------------------------------------
    @property
    def display_name(self) -> str | None:
        if self._display_name is None:
            profile = self.get_user_profile()
            name = (profile.get("userData") or {}).get("displayName") or profile.get(
                "displayName"
            )
            self._display_name = name if isinstance(name, str) else None
        return self._display_name

    # -- wellness ----------------------------------------------------------
    def get_sleep_data(self, cdate: str) -> dict[str, Any]:
        raw = self._client.get("/sleep-service/sleep/dailySleep", {"date": cdate})
        if isinstance(raw, dict) and "dailySleepDTO" in raw:
            return raw
        return {"dailySleepDTO": raw} if isinstance(raw, dict) else {}

    def get_hrv_data(self, cdate: str) -> dict[str, Any]:
        raw = self._client.get(f"/hrv-service/hrv/{cdate}")
        if isinstance(raw, dict) and "hrvSummary" in raw:
            return raw
        return {"hrvSummary": raw} if isinstance(raw, dict) else {}

    def get_rhr_day(self, cdate: str) -> dict[str, Any]:
        raw = self._client.get(
            "/usersummary-service/v2/dailysummaries",
            {"startDate": cdate, "endDate": cdate},
        )
        item = _first(raw)
        value = item.get("restingHeartRate")
        if value is None:
            metrics = ((item.get("allMetrics") or {}).get("metricsMap") or {}).get(
                "WELLNESS_RESTING_HEART_RATE"
            )
            if isinstance(metrics, list):
                for metric in metrics:
                    if isinstance(metric, dict) and isinstance(metric.get("value"), (int, float)):
                        value = metric["value"]
                        break
        if isinstance(value, (int, float)):
            return {"calendarDate": cdate, "restingHeartRate": value}
        return item

    def get_all_day_stress(self, cdate: str) -> dict[str, Any]:
        raw = self._client.get(f"/usersummary-service/stats/stress/daily/{cdate}/{cdate}")
        return _first(raw)

    def get_body_battery(self, start: str, end: str) -> list[dict[str, Any]]:
        raw = self._client.get(
            "/wellness-service/wellness/bodyBattery/reports/daily",
            {"startDate": start, "endDate": end},
        )
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    # -- activities --------------------------------------------------------
    def get_activities(self, start: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        raw = self._client.get(
            "/activitylist-service/activities/search/activities",
            {"start": start, "limit": limit},
        )
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def get_activity(self, activity_id: int) -> dict[str, Any]:
        raw = self._client.get(f"/activity-service/activity/{activity_id}")
        return raw if isinstance(raw, dict) else {}

    def get_activity_splits(self, activity_id: int) -> dict[str, Any]:
        """Personal API exposes ``splitSummaries`` inside the activity payload.

        Garmin's dedicated splits endpoint is undocumented for this tier, so the
        activity detail is the source. Field names match the lap shape the
        normalizer already understands (distance, duration, averageHR, ...).
        """
        detail = self.get_activity(activity_id)
        splits = detail.get("splitSummaries")
        if isinstance(splits, list):
            return {"lapDTOs": [item for item in splits if isinstance(item, dict)]}
        return {}

    def get_activity_workouts(self, activity_id: int) -> Any:
        return self._client.get(f"/activity-service/activity/{activity_id}/workouts")

    def download_activity_file(self, activity_id: int) -> bytes:
        """Original activity file (ZIP containing the .FIT) for one activity."""
        return self._client.get_bytes(f"/download-service/files/activity/{activity_id}")

    # -- profile & zones ---------------------------------------------------
    def get_user_profile(self) -> dict[str, Any]:
        settings = self._client.get("/userprofile-service/userprofile/settings")
        profile = settings if isinstance(settings, dict) else {}
        zones = self._heart_rate_zones()
        if zones:
            profile.setdefault("userData", {})
            if isinstance(profile["userData"], dict):
                profile["userData"].setdefault("heartRateZones", zones)
        return profile

    def _heart_rate_zones(self) -> list[dict[str, Any]]:
        raw = self._client.get("/biometric-service/heartRateZones/v2")
        if isinstance(raw, list):
            candidates: Any = raw
        elif isinstance(raw, dict):
            candidates = raw.get("heartRateZones") or raw.get("zones") or []
        else:
            candidates = []
        zones: list[dict[str, Any]] = []
        for item in candidates if isinstance(candidates, list) else []:
            if not isinstance(item, dict):
                continue
            zone = item.get("zone") or item.get("zoneNumber") or item.get("zoneIndex")
            low = item.get("low") or item.get("lowBpm") or item.get("zoneLowBoundary")
            high = item.get("high") or item.get("highBpm") or item.get("zoneHighBoundary")
            if zone is None and low is None and high is None:
                continue
            zones.append({"zone": zone, "low": low, "high": high})
        return zones

    # -- personal-only extras ---------------------------------------------
    def get_body_composition(self, start: str, end: str) -> Any:
        return self._client.get(
            f"/weight-service/weight/range/{start}/{end}", {"includeAll": "true"}
        )

    def get_daily_summaries(self, start: str, end: str) -> Any:
        return self._client.get(
            "/usersummary-service/v2/dailysummaries",
            {"startDate": start, "endDate": end},
        )

    def get_spo2(self, cdate: str) -> Any:
        return self._client.get(f"/wellness-service/wellness/daily/spo2acclimation/{cdate}")

    def get_hydration(self, start: str, end: str) -> Any:
        return self._client.get(f"/usersummary-service/stats/hydration/daily/{start}/{end}")

    def get_steps(self, start: str, end: str) -> Any:
        return self._client.get(f"/usersummary-service/stats/steps/daily/{start}/{end}")

    def get_fitness_age(self, cdate: str | None = None) -> Any:
        day = cdate or date.today().isoformat()
        return self._client.get(f"/fitnessage-service/fitnessage/v2/{day}")

    # -- not available on the Personal API --------------------------------
    _UNSUPPORTED = {
        "get_training_status": "training status/load (Garmin-derived)",
        "get_training_readiness": "training readiness (Garmin-derived)",
        "get_race_predictions": "race predictions (Garmin-derived)",
        "get_max_metrics": "VO2 Max / max metrics (Garmin-derived)",
        "get_cycling_ftp": "cycling FTP (Garmin-derived)",
        "get_personal_record": "personal records (Garmin-derived)",
    }

    def __getattr__(self, name: str) -> Any:
        if name in self._UNSUPPORTED:
            what = self._UNSUPPORTED[name]

            def raise_unsupported(*_args: Any, **_kwargs: Any) -> Any:
                raise PersonalApiUnsupported(
                    f"{what} is not exposed by the Garmin Personal API; "
                    "use GARMIN_AUTH_MODE=unofficial for that metric."
                )

            return raise_unsupported
        raise AttributeError(name)
