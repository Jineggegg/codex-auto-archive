import os
import sys

import pytest

from codex_auto_archive.appserver import AppServer, AppServerError
from codex_auto_archive.models import Connection


async def test_protocol_multipage_events_and_disconnect(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text(
        """import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 method=m['method']; p=m['params']; result={}
 if method=='initialize': result={'codexHome':'test'}
 elif method=='thread/list':
  assert 'exec' in p['sourceKinds'] and 'unknown' in p['sourceKinds']
  result={'data':[{'id':'second' if p.get('cursor') else 'first'}],'nextCursor':None if p.get('cursor') else 'next'}
  print(json.dumps({'method':'thread/status/changed','params':{'threadId':'first','status':{'type':'idle'}}}),flush=True)
 elif method=='thread/read': sys.exit(0)
 print(json.dumps({'id':m['id'],'result':result}),flush=True)
""",
        encoding="utf-8",
    )
    events = []
    connection = Connection(command=[sys.executable, str(script)], timeout_seconds=2)
    async with AppServer(connection, events.append) as client:
        assert [t["id"] for t in await client.threads()] == ["first", "second"]
        assert events[0]["method"] == "thread/status/changed"
        with pytest.raises(AppServerError):
            await client.read("first")
        with pytest.raises(AppServerError, match="not allowed"):
            await client.call("thread/delete", {"threadId": "first"})
    async with AppServer(connection) as client:
        assert len(await client.threads()) == 2  # Fresh handshake after restart.


async def test_repeated_cursor_aborts(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text("""import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' in m:
  r={} if m['method']=='initialize' else {'data':[],'nextCursor':'same'}
  print(json.dumps({'id':m['id'],'result':r}),flush=True)
""")
    async with AppServer(Connection(command=[sys.executable, str(script)])) as client:
        with pytest.raises(AppServerError, match="Repeated pagination"):
            await client.threads()


async def test_real_mcp_stdio_discovery_and_call(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "CODEX_AUTO_ARCHIVE_HOME": str(tmp_path)}
    async with stdio_client(
        StdioServerParameters(
            command=sys.executable, args=["-m", "codex_auto_archive", "serve"], env=env
        )
    ) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            listing = await session.list_tools()
            assert len(listing.tools) >= 15
            result = await session.call_tool("get_archive_settings", {})
            assert not result.isError
            assert result.structuredContent["settings"]["dry_run"]
            result = await session.call_tool(
                "update_archive_settings", {"settings": {"inactive_days": 7}}
            )
            assert result.structuredContent["settings"]["policy"]["inactive_days"] == 7
            result = await session.call_tool(
                "update_archive_settings", {"settings": {"inactive_days": "7"}}
            )
            assert result.isError
