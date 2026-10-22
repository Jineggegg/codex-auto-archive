"""Official Codex plugin install, discovery and tool call; no real model required."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codex_auto_archive.appserver import ALLOWED, AppServer
from codex_auto_archive.models import Connection


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("ARCHIVE_REAL_INTEGRATION")
    or not shutil.which("codex")
    or not shutil.which("uv"),
    reason="Opt-in Codex/uv plugin integration",
)
async def test_official_plugin_install_discover_and_call(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("CODEX_AUTO_ARCHIVE_HOME", str(tmp_path / "plugin-state"))
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["codex", "plugin", "marketplace", "add", str(root)], check=True, capture_output=True
    )
    subprocess.run(
        ["codex", "plugin", "add", "codex-auto-archive@codex-auto-archive"],
        check=True,
        capture_output=True,
    )
    ALLOWED.update({"thread/start", "mcpServer/tool/call"})
    try:
        async with AppServer(Connection(timeout_seconds=60)) as c:
            status = await c.call(
                "mcpServerStatus/list", {"serverName": "auto-archive", "detail": "toolsAndAuthOnly"}
            )
            server = next(x for x in status["data"] if x["name"] == "auto-archive")
            assert len(server["tools"]) == 22, server.get("toolsError")
            thread = await c.call("thread/start", {"ephemeral": True, "cwd": str(tmp_path)})
            result = await c.call(
                "mcpServer/tool/call",
                {
                    "threadId": thread["thread"]["id"],
                    "server": "auto-archive",
                    "tool": "get_archive_settings",
                    "arguments": {},
                },
            )
            assert not result.get("isError")
            assert result["structuredContent"]["settings"]["dry_run"]
            status_result = await c.call(
                "mcpServer/tool/call",
                {
                    "threadId": thread["thread"]["id"],
                    "server": "auto-archive",
                    "tool": "get_archive_status",
                    "arguments": {},
                },
            )
            assert status_result["structuredContent"]["storage"] == str(tmp_path / "plugin-state")
            result = await c.call(
                "mcpServer/tool/call",
                {
                    "threadId": thread["thread"]["id"],
                    "server": "auto-archive",
                    "tool": "update_archive_settings",
                    "arguments": {"settings": {"inactive_days": 7}},
                },
            )
            assert result["structuredContent"]["settings"]["policy"]["inactive_days"] == 7
            assert result["structuredContent"]["settings"]["dry_run"]
    finally:
        ALLOWED.difference_update({"thread/start", "mcpServer/tool/call"})
    subprocess.run(
        ["codex", "plugin", "remove", "codex-auto-archive@codex-auto-archive"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["codex", "plugin", "marketplace", "remove", "codex-auto-archive"],
        check=True,
        capture_output=True,
    )
