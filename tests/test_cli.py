import json

from mcp_garmin_connect.cli import main


def test_tools_command_lists_capabilities(capsys) -> None:
    main(["tools"])
    payload = json.loads(capsys.readouterr().out)
    assert "tools" in payload
    assert "prompts" in payload
    assert any(tool["name"] == "get_recovery" for tool in payload["tools"])
