from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .tools import TOOL_SPECS, TOOLS_BY_NAME, tool_schema

SYSTEM_PROMPT = """You are a careful endurance training assistant.
Always use Garmin tools before giving personalized training, recovery, or performance advice.
Be practical, concise, and explicit about uncertainty when Garmin data is missing."""


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[str]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    default_model: str
    api_key_configured: bool
    base_url: str


class BaseToolCallingAgent(ABC):
    provider_name: str

    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.model = model or self.default_model()

    def ask(
        self,
        question: str,
        max_tool_rounds: int = 4,
        allow_external_health_data: bool = False,
    ) -> AgentResult:
        if not allow_external_health_data:
            raise PermissionError(
                f"The {self.provider_name} demo agent can send Garmin health/activity data to "
                f"{self.provider_name}. Pass allow_external_health_data=True only after the "
                "user explicitly agrees."
            )
        return self._ask(question=question, max_tool_rounds=max_tool_rounds)

    @abstractmethod
    def default_model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _ask(self, question: str, max_tool_rounds: int) -> AgentResult:
        raise NotImplementedError


class OpenAICompatibleAgent(BaseToolCallingAgent):
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        provider_name: str,
        settings: Settings | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._default_model = default_model
        self.provider_name = provider_name
        super().__init__(settings=settings, model=model)

    def default_model(self) -> str:
        return self._default_model

    def _ask(self, question: str, max_tool_rounds: int) -> AgentResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        tool_calls_seen: list[str] = []

        with httpx.Client(base_url=self.base_url, timeout=120) as client:
            for _ in range(max_tool_rounds + 1):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": openai_compatible_tools(),
                    "tool_choice": "auto",
                }
                response = client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                messages.append(message)

                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return AgentResult(
                        answer=message.get("content") or "",
                        tool_calls=tool_calls_seen,
                    )

                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name")
                    result = call_tool(name, parse_arguments(function.get("arguments")))
                    tool_calls_seen.append(name or "unknown")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )

        return AgentResult(
            answer="The model kept requesting tools and hit the configured tool-round limit.",
            tool_calls=tool_calls_seen,
        )


class ClaudeAgent(BaseToolCallingAgent):
    provider_name = "claude"

    def default_model(self) -> str:
        return self.settings.anthropic_model

    def _ask(self, question: str, max_tool_rounds: int) -> AgentResult:
        api_key = self.settings.require_provider_key("claude")
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tool_calls_seen: list[str] = []

        with httpx.Client(
            base_url=self.settings.anthropic_base_url.rstrip("/"),
            timeout=120,
        ) as client:
            for _ in range(max_tool_rounds + 1):
                payload = {
                    "model": self.model,
                    "max_tokens": 2048,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": claude_tools(),
                }
                response = client.post(
                    "/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json=payload,
                )
                response.raise_for_status()
                message = response.json()
                content = message.get("content") or []
                tool_uses = [block for block in content if block.get("type") == "tool_use"]
                if not tool_uses:
                    return AgentResult(answer=_claude_text(content), tool_calls=tool_calls_seen)

                messages.append({"role": "assistant", "content": content})
                tool_results = []
                for block in tool_uses:
                    name = block.get("name")
                    tool_input = block.get("input")
                    result = call_tool(name, tool_input if isinstance(tool_input, dict) else {})
                    tool_calls_seen.append(name or "unknown")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.get("id"),
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})

        return AgentResult(
            answer="The model kept requesting tools and hit the configured tool-round limit.",
            tool_calls=tool_calls_seen,
        )


class DeepSeekAgent(OpenAICompatibleAgent):
    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        settings = settings or Settings.from_env()
        super().__init__(
            api_key=settings.require_provider_key("deepseek"),
            base_url=settings.deepseek_base_url,
            default_model=settings.deepseek_model,
            provider_name="deepseek",
            settings=settings,
            model=model,
        )


class OpenAIAgent(OpenAICompatibleAgent):
    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        settings = settings or Settings.from_env()
        super().__init__(
            api_key=settings.require_provider_key("openai"),
            base_url=settings.openai_base_url,
            default_model=settings.openai_model,
            provider_name="openai",
            settings=settings,
            model=model,
        )


def create_agent(
    provider: str,
    settings: Settings | None = None,
    model: str | None = None,
) -> BaseToolCallingAgent:
    provider_key = provider.lower()
    if provider_key == "deepseek":
        return DeepSeekAgent(settings=settings, model=model)
    if provider_key == "openai":
        return OpenAIAgent(settings=settings, model=model)
    if provider_key == "claude":
        return ClaudeAgent(settings=settings, model=model)
    raise ValueError(f"Unsupported provider: {provider}")


def provider_specs(settings: Settings | None = None) -> dict[str, ProviderSpec]:
    settings = settings or Settings.from_env()
    return {
        "deepseek": ProviderSpec(
            name="deepseek",
            default_model=settings.deepseek_model,
            api_key_configured=bool(settings.deepseek_api_key),
            base_url=settings.deepseek_base_url,
        ),
        "openai": ProviderSpec(
            name="openai",
            default_model=settings.openai_model,
            api_key_configured=bool(settings.openai_api_key),
            base_url=settings.openai_base_url,
        ),
        "claude": ProviderSpec(
            name="claude",
            default_model=settings.anthropic_model,
            api_key_configured=bool(settings.anthropic_api_key),
            base_url=settings.anthropic_base_url,
        ),
    }


def supported_providers() -> list[str]:
    return ["deepseek", "openai", "claude"]


def openai_compatible_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": tool_schema(spec),
            },
        }
        for spec in TOOL_SPECS
    ]


def claude_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": tool_schema(spec),
        }
        for spec in TOOL_SPECS
    ]


def parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def call_tool(name: str | None, args: dict[str, Any]) -> dict[str, Any]:
    if not name or name not in TOOLS_BY_NAME:
        return {"error": f"unknown tool: {name}"}
    try:
        return TOOLS_BY_NAME[name].function(**args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _claude_text(content: list[dict[str, Any]]) -> str:
    parts = [block.get("text", "") for block in content if block.get("type") == "text"]
    return "\n".join(part for part in parts if part).strip()
