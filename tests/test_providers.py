from __future__ import annotations

from typing import Any

import pytest

from mcp_garmin_connect.config import Settings
from mcp_garmin_connect.providers import (
    ClaudeAgent,
    OpenAIAgent,
    claude_tools,
    create_agent,
    openai_compatible_tools,
    provider_specs,
)


def settings() -> Settings:
    return Settings(
        garmin_email="x",
        garmin_password="y",
        garmin_token_store=".",
        deepseek_api_key="deepseek-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-pro",
        openai_api_key="openai-key",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-5",
        anthropic_api_key="anthropic-key",
        anthropic_base_url="https://api.anthropic.com",
        anthropic_model="claude-sonnet-5",
        cache_ttl_seconds=60,
    )


def test_provider_registry_and_defaults() -> None:
    specs = provider_specs(settings())
    assert specs["deepseek"].default_model == "deepseek-v4-pro"
    assert specs["openai"].default_model == "gpt-5"
    assert specs["claude"].default_model == "claude-sonnet-5"
    assert isinstance(create_agent("openai", settings=settings()), OpenAIAgent)
    assert isinstance(create_agent("claude", settings=settings()), ClaudeAgent)


def test_provider_requires_health_data_opt_in() -> None:
    agent = create_agent("openai", settings=settings())
    with pytest.raises(PermissionError):
        agent.ask("How is my recovery?")


def test_tool_payload_shapes() -> None:
    openai_tool = openai_compatible_tools()[0]
    claude_tool = claude_tools()[0]
    assert openai_tool["type"] == "function"
    assert "parameters" in openai_tool["function"]
    assert "input_schema" in claude_tool


def test_openai_compatible_tool_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            if len(calls) == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "function": {
                                            "name": "get_sleep",
                                            "arguments": '{"days": 1}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            return {"choices": [{"message": {"content": "done"}}]}

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, *args: Any, **kwargs: Any) -> Response:
            calls.append(kwargs["json"])
            return Response()

    monkeypatch.setattr("mcp_garmin_connect.providers.httpx.Client", Client)
    monkeypatch.setattr(
        "mcp_garmin_connect.providers.call_tool",
        lambda name, args: {"ok": True, "name": name, "args": args},
    )

    result = create_agent("openai", settings=settings()).ask(
        "test",
        allow_external_health_data=True,
    )

    assert result.answer == "done"
    assert result.tool_calls == ["get_sleep"]
    assert calls[0]["tools"][0]["type"] == "function"


def test_claude_tool_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            if len(calls) == 1:
                return {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "get_sleep",
                            "input": {"days": 1},
                        }
                    ]
                }
            return {"content": [{"type": "text", "text": "done"}]}

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, *args: Any, **kwargs: Any) -> Response:
            calls.append(kwargs["json"])
            return Response()

    monkeypatch.setattr("mcp_garmin_connect.providers.httpx.Client", Client)
    monkeypatch.setattr(
        "mcp_garmin_connect.providers.call_tool",
        lambda name, args: {"ok": True, "name": name, "args": args},
    )

    result = create_agent("claude", settings=settings()).ask(
        "test",
        allow_external_health_data=True,
    )

    assert result.answer == "done"
    assert result.tool_calls == ["get_sleep"]
    assert calls[0]["tools"][0]["input_schema"]["type"] == "object"
