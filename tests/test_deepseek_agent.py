import pytest

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.deepseek_agent import DeepSeekAgent, _call_tool, _parse_arguments


def test_parse_arguments() -> None:
    assert _parse_arguments('{"days": 7}') == {"days": 7}
    assert _parse_arguments("") == {}
    assert _parse_arguments("not-json") == {}


def test_unknown_tool_returns_error() -> None:
    result = _call_tool("missing_tool", {})
    assert "unknown tool" in result["error"]


def test_agent_requires_external_health_data_opt_in() -> None:
    agent = DeepSeekAgent(
        settings=Settings(
            garmin_email="x",
            garmin_password="y",
            garmin_token_store=".",
            deepseek_api_key="dummy",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-v4-pro",
            cache_ttl_seconds=60,
        )
    )

    with pytest.raises(PermissionError):
        agent.ask("How is my recovery?", allow_external_health_data=False)
