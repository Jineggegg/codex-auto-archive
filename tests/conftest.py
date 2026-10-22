from __future__ import annotations

import copy

import pytest

from codex_auto_archive.engine import Engine
from codex_auto_archive.models import Connection
from codex_auto_archive.storage import Store

NOW = 1_800_000_000


class FakeClient:
    def __init__(self):
        self.connection = Connection(authoritative=True)
        self.owned_ids = set()
        self.active = {}
        self.archived = {}
        self.goals = {}
        self.turn_data = {}
        self.children = {}
        self.calls = []
        self.fail = set()
        self.on_archive = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def add(self, tid="one", days=31, **kwargs):
        t = {
            "id": tid,
            "name": tid,
            "cwd": "/project",
            "source": "cli",
            "status": {"type": "idle"},
            "isPinned": False,
            "updatedAt": NOW - days * 86400,
            "createdAt": NOW - 100 * 86400,
            "ephemeral": False,
            "parentThreadId": None,
            **kwargs,
        }
        self.active[tid] = t
        self.turn_data[tid] = [
            {
                "id": "turn",
                "status": "completed",
                "startedAt": NOW - days * 86400,
                "completedAt": NOW - days * 86400,
            }
        ]
        return t

    async def threads(self, archived=False, **filters):
        if "thread/list" in self.fail:
            raise RuntimeError("Disconnected")
        result = copy.deepcopy(list((self.archived if archived else self.active).values()))
        return [t for t in result if not filters.get("cwd") or t["cwd"] == filters["cwd"]]

    async def read(self, tid):
        if "thread/read" in self.fail:
            raise RuntimeError("Disconnected")
        return copy.deepcopy((self.active | self.archived)[tid])

    async def turns(self, tid):
        if "thread/turns/list" in self.fail:
            raise RuntimeError("Disconnected")
        return copy.deepcopy(self.turn_data.get(tid, []))

    async def goal(self, tid):
        if "thread/goal/get" in self.fail:
            raise RuntimeError("Unsupported goal safety API")
        return copy.deepcopy(self.goals.get(tid))

    async def descendants(self, tid):
        if "descendants" in self.fail:
            raise RuntimeError("Cannot enumerate descendants")
        return [
            copy.deepcopy(self.active[i]) for i in self.children.get(tid, []) if i in self.active
        ]

    async def call(self, method, params):
        self.calls.append(method)
        if method in self.fail:
            raise RuntimeError("Network failure")
        tid = params["threadId"]
        if method == "thread/archive":
            if self.on_archive:
                self.on_archive()
            for i in [tid, *self.children.get(tid, [])]:
                if i in self.active:
                    self.archived[i] = self.active.pop(i)
            return {}
        if method == "thread/unarchive":
            self.active[tid] = self.archived.pop(tid)
            return {"thread": copy.deepcopy(self.active[tid])}
        raise ValueError(method)


class FakeGitHub:
    def __init__(self, **signals):
        self.values = signals
        self.failed = False
        self.calls = 0

    async def signals(self, mapping, required=None):
        self.calls += 1
        if self.failed:
            raise RuntimeError("GitHub unavailable")
        return self.values


@pytest.fixture
def setup_engine(tmp_path):
    store = Store(tmp_path)
    client = FakeClient()
    client.add()
    clock = [NOW]
    github = FakeGitHub()
    engine = Engine(store, client, lambda: clock[0], github)
    return store, client, clock, github, engine
