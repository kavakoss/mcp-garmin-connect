"""Hybrid backend: routing, fallback and credential requirements."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.errors import PersonalApiAuthError, PersonalApiHttpError
from mcp_garmin_connect.hybrid import HybridBackend


class FakePersonal:
    backend_name = "personal"
    display_name = "personal-user"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_sleep_data(self, cdate: str) -> dict[str, object]:
        self.calls.append("sleep")
        return {"dailySleepDTO": {"sleepTimeSeconds": 25200}}

    def get_body_composition(self, start: str, end: str) -> dict[str, object]:
        self.calls.append("weight")
        raise PersonalApiHttpError("weight endpoint down", status_code=503)

    def get_max_metrics(self, cdate: str) -> object:
        raise AssertionError("personal backend must not be asked for VO2 Max first")


class FakeUnofficial:
    backend_name = "unofficial"
    display_name = None

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_training_status(self, cdate: str) -> dict[str, object]:
        self.calls.append("training_status")
        return {"mostRecentTrainingStatus": {"latestTrainingStatusData": {"d": {}}}}

    def get_body_composition(self, start: str, end: str) -> dict[str, object]:
        self.calls.append("weight-fallback")
        return {"dateWeightList": [{"calendarDate": start, "weight": 71200}]}

    def get_max_metrics(self, cdate: str) -> list[dict[str, object]]:
        self.calls.append("vo2")
        return [{"generic": {"vo2MaxPreciseValue": 44.4}}]


def _hybrid() -> tuple[HybridBackend, FakePersonal, FakeUnofficial]:
    personal = FakePersonal()
    unofficial = FakeUnofficial()
    return HybridBackend(personal=personal, unofficial=unofficial), personal, unofficial


def test_wellness_reads_go_to_the_official_backend() -> None:
    backend, personal, unofficial = _hybrid()

    backend.get_sleep_data("2026-10-27")

    assert personal.calls == ["sleep"]
    assert unofficial.calls == []


def test_derived_metrics_go_to_the_unofficial_backend() -> None:
    backend, personal, unofficial = _hybrid()

    backend.get_max_metrics("2026-10-27")
    backend.get_training_status("2026-10-27")

    assert unofficial.calls == ["vo2", "training_status"]
    assert personal.calls == []


def test_a_failing_official_endpoint_falls_back_to_the_other_backend() -> None:
    backend, _, unofficial = _hybrid()

    payload = backend.get_body_composition("2026-10-20", "2026-10-27")

    assert "dateWeightList" in payload
    assert unofficial.calls == ["weight-fallback"]


def test_auth_errors_are_never_masked_by_the_fallback() -> None:
    class Rejecting(FakePersonal):
        def get_sleep_data(self, cdate: str) -> dict[str, object]:
            raise PersonalApiAuthError("key expired")

    backend = HybridBackend(personal=Rejecting(), unofficial=FakeUnofficial())

    with pytest.raises(PersonalApiAuthError):
        backend.get_sleep_data("2026-10-27")


def test_display_name_falls_through_to_the_backend_that_has_one() -> None:
    backend, _, _ = _hybrid()
    assert backend.display_name == "personal-user"


def test_routing_map_is_introspectable() -> None:
    backend, _, _ = _hybrid()
    routing = backend.routing()
    assert "get_sleep_data" in routing["personal"]
    assert "get_max_metrics" in routing["unofficial"]


def test_hybrid_requires_both_credential_sets() -> None:
    base = Settings.from_env()
    both = replace(
        base,
        garmin_demo=False,
        garmin_auth_mode="hybrid",
        garmin_personal_api_key="key",
        garmin_email="a@b.c",
        garmin_password="secret",
    )
    only_key = replace(both, garmin_email=None)
    only_password = replace(both, garmin_personal_api_key=None)

    assert both.resolved_auth_mode() == "hybrid"
    assert only_key.garmin_personal_api_key and not only_key.garmin_email
    assert only_password.garmin_email and not only_password.garmin_personal_api_key
