from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .tools import TOOLS_BY_NAME, TOOL_SPECS, tool_schema


SYSTEM_PROMPT = """You are a careful endurance training assistant.
Always use Garmin tools before giving personalized training, recovery, or performance advice.
Be practical, concise, and explicit about uncertainty when Garmin data is missing."""


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[str]


class DeepSeekAgent:
    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.model = model or self.settings.deepseek_model

    def ask(self, question: str, max_tool_rounds: int = 4) -> AgentResult:
        api_key = self.settings.require_deepseek_key()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        tool_calls_seen: list[str] = []

        with httpx.Client(base_url=self.settings.deepseek_base_url, timeout=120) as client:
            for _ in range(max_tool_rounds + 1):
                response = client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "tools": _deepseek_tools(),
                        "tool_choice": "auto",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                message = payload["choices"][0]["message"]
                messages.append(message)
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return AgentResult(answer=message.get("content") or "", tool_calls=tool_calls_seen)

                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name")
                    args = _parse_arguments(function.get("arguments"))
                    result = _call_tool(name, args)
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


def _deepseek_tools() -> list[dict[str, Any]]:
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


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _call_tool(name: str | None, args: dict[str, Any]) -> dict[str, Any]:
    if not name or name not in TOOLS_BY_NAME:
        return {"error": f"unknown tool: {name}"}
    try:
        return TOOLS_BY_NAME[name].function(**args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
