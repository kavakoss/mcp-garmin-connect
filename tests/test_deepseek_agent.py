from mcp_garmin_connect.deepseek_agent import _call_tool, _parse_arguments


def test_parse_arguments() -> None:
    assert _parse_arguments('{"days": 7}') == {"days": 7}
    assert _parse_arguments("") == {}
    assert _parse_arguments("not-json") == {}


def test_unknown_tool_returns_error() -> None:
    result = _call_tool("missing_tool", {})
    assert "unknown tool" in result["error"]
