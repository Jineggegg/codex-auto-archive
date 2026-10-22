"""Opt-in real native Archive test. Creates ONLY a disposable isolated test thread."""

import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from codex_auto_archive.appserver import ALLOWED, AppServer
from codex_auto_archive.engine import Engine
from codex_auto_archive.models import Connection
from codex_auto_archive.storage import Store


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("ARCHIVE_REAL_INTEGRATION") or not shutil.which("codex"),
    reason="Set ARCHIVE_REAL_INTEGRATION=1 with Codex installed",
)
async def test_real_native_archive_restore_no_inference(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))

    # A local mock response materializes a native test conversation without a real model.
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            item = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Archive fixture ready.", "annotations": []}
                ],
            }
            completed = {
                "type": "response.completed",
                "response": {
                    "id": "resp_fixture",
                    "status": "completed",
                    "output": [item],
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                },
            }
            body = ("event: response.completed\ndata: " + json.dumps(completed) + "\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    mock = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=mock.serve_forever, daemon=True)
    worker.start()
    (home / "config.toml").write_text(f"""model="archive-fixture"
model_provider="archive_fixture"
[model_providers.archive_fixture]
name="Local test fixture"
base_url="http://127.0.0.1:{mock.server_port}/v1"
wire_api="responses"
requires_openai_auth=false
supports_websockets=false
""")
    store = Store(tmp_path / "plugin")
    store.edit(lambda c: setattr(c.policy, "exclude_pinned", False))
    ALLOWED.update({"thread/start", "turn/start"})
    try:
        async with AppServer(Connection()) as client:
            created = await client.call(
                "thread/start", {"cwd": str(tmp_path), "ephemeral": False, "historyMode": "legacy"}
            )
            tid = created["thread"]["id"]
            await client.call(
                "turn/start",
                {
                    "threadId": tid,
                    "input": [{"type": "text", "text": "Create archive fixture only."}],
                },
            )
            import asyncio

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if any(x.get("method") == "turn/completed" for x in client.events):
                    break
                await asyncio.sleep(0.05)
            assert any(x.get("method") == "turn/completed" for x in client.events), list(
                client.events
            )
            client.owned_ids.add(tid)  # This process owns the synthetic, completed test turn.
            active = {t["id"] for t in await client.threads()}
            assert tid in active
            engine = Engine(store, client)
            preview = await engine.preview(ids=[tid])
            assert preview["candidate_count"] == 1, preview
            archived = await engine.execute(preview["confirmation_token"], True)
            assert archived["successful_thread_ids"] == [tid], archived
            assert tid in {t["id"] for t in await client.threads(archived=True)}
            preview = await engine.restore([tid])
            restored = await engine.restore([tid], preview["confirmation_token"], True)
            assert restored["successful_thread_ids"] == [tid]
            assert tid in {t["id"] for t in await client.threads()}
            assert store.activity(tid)["cooldown_until"] > 0
    finally:
        ALLOWED.difference_update({"thread/start", "turn/start"})
        mock.shutdown()
        mock.server_close()
        worker.join(timeout=2)
