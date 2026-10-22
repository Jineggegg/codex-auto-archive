from __future__ import annotations

import asyncio
import json
import os
from collections import deque

from .models import Connection

SOURCES = [
    "cli",
    "vscode",
    "exec",
    "appServer",
    "subAgent",
    "subAgentReview",
    "subAgentCompact",
    "subAgentThreadSpawn",
    "subAgentOther",
    "unknown",
]
READ_METHODS = {
    "thread/list",
    "thread/read",
    "thread/turns/list",
    "thread/loaded/list",
    "thread/goal/get",
    "mcpServerStatus/list",
}
ALLOWED = READ_METHODS | {"thread/archive", "thread/unarchive", "initialize"}


class AppServerError(RuntimeError):
    pass


class AppServer:
    def __init__(self, connection: Connection, on_event=None):
        self.connection = connection
        self.on_event = on_event
        self.pending = {}
        self.events = deque(maxlen=1000)
        self.counter = 0
        self.process = None
        self.reader = None
        self.writer_lock = asyncio.Lock()
        self.owned_ids = set()
        self.identity = {}

    async def __aenter__(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.connection.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=32 * 1024 * 1024,
                env=os.environ.copy(),
            )
            self.reader = asyncio.create_task(self._read())
            self.identity = await self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex_auto_archive",
                        "title": "Codex Auto Archive",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self._write({"method": "initialized", "params": {}})
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *_):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)

    async def _write(self, value):
        async with self.writer_lock:
            self.process.stdin.write((json.dumps(value) + "\n").encode())
            await self.process.stdin.drain()

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                msg = json.loads(line)
                if "id" in msg and "method" not in msg:
                    f = self.pending.get(msg["id"])
                    if f and not f.done():
                        if "error" in msg:
                            f.set_exception(AppServerError(json.dumps(msg["error"])))
                        else:
                            f.set_result(msg.get("result", {}))
                elif "id" in msg:
                    # Never approve commands, edits or model work initiated by the server.
                    await self._write(
                        {
                            "id": msg["id"],
                            "error": {
                                "code": -32601,
                                "message": "Archive client does not execute server requests",
                            },
                        }
                    )
                else:
                    self.events.append(msg)
                    if self.on_event:
                        self.on_event(msg)
        except Exception as e:
            error = AppServerError(f"App Server stream failed: {type(e).__name__}")
        else:
            error = AppServerError("App Server disconnected")
        for f in self.pending.values():
            if not f.done():
                f.set_exception(error)

    async def call(self, method, params=None):
        if method not in ALLOWED:
            raise AppServerError("Method is not allowed by the archive client")
        self.counter += 1
        ident = self.counter
        f = asyncio.get_running_loop().create_future()
        self.pending[ident] = f
        try:
            await self._write({"id": ident, "method": method, "params": params or {}})
            return await asyncio.wait_for(f, self.connection.timeout_seconds)
        except (BrokenPipeError, ConnectionError, TimeoutError) as e:
            raise AppServerError(
                f"{method} failed ({type(e).__name__}); mutation outcome may be unknown"
            ) from e
        finally:
            self.pending.pop(ident, None)

    async def pages(self, method, params):
        result, cursor, seen = [], None, set()
        while True:
            page = await self.call(method, {**params, "cursor": cursor, "limit": 100})
            if not isinstance(page.get("data"), list):
                raise AppServerError("Invalid paginated response; scan aborted")
            result.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                return result
            if cursor in seen:
                raise AppServerError("Repeated pagination cursor; scan aborted")
            seen.add(cursor)

    async def threads(self, archived=False, **filters):
        return await self.pages(
            "thread/list",
            {"archived": archived, "sourceKinds": SOURCES, "modelProviders": [], **filters},
        )

    async def read(self, tid):
        return (await self.call("thread/read", {"threadId": tid, "includeTurns": False}))["thread"]

    async def turns(self, tid):
        return await self.pages(
            "thread/turns/list",
            {"threadId": tid, "itemsView": "notLoaded", "sortDirection": "desc"},
        )

    async def descendants(self, tid):
        return await self.threads(ancestorThreadId=tid)

    async def goal(self, tid):
        return (await self.call("thread/goal/get", {"threadId": tid})).get("goal")
