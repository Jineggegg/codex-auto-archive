from __future__ import annotations

import hashlib
import json
import time

from pydantic import TypeAdapter

from .models import ThreadId

ACTIVITY = {
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "SubagentStart",
    "SubagentStop",
}
SUPPORTED = ACTIVITY | {"SessionStart", "SessionEnd", "Stop", "Interrupt"}


def ingest(store, payload: dict, now=None):
    now = time.time() if now is None else now
    name = payload.get("hook_event_name")
    if name not in SUPPORTED:
        return {"accepted": False, "reason": "Unsupported hook"}
    tid = TypeAdapter(ThreadId).validate_python(payload.get("session_id"))
    # No prompt/tool contents/transcript paths are retained.
    ident = payload.get("event_id")
    if not ident:
        keys = ("session_id", "hook_event_name", "turn_id", "tool_use_id", "agent_id", "reason")
        identity = {k: payload.get(k) for k in keys}
        identity["debounce_bucket"] = int(now // 2)
        ident = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM events WHERE id=?", (ident,)).fetchone():
            return {"accepted": False, "reason": "Duplicate event"}
        db.execute("INSERT INTO events VALUES (?,?,?)", (ident, tid, now))
        db.execute("DELETE FROM events WHERE at<?", (now - 7 * 86400,))
        row = db.execute("SELECT value FROM state WHERE key=?", ("thread:" + tid,)).fetchone()
        data = json.loads(row[0]) if row else {}
        if name in ACTIVITY:
            data["last_activity"] = now
            # A new turn cancels manual deferrals; every activity cancels automatic ones.
            pending = data.pop("pending_auto", None)
            if pending and pending.get("signal_key"):
                data["cancelled_signal_key"] = pending["signal_key"]
        if name == "UserPromptSubmit":
            data["last_user_prompt"] = now
            data["user_generation"] = data.get("user_generation", 0) + 1
            data.pop("pending_manual", None)
            data.pop("completion", None)
        if name in {"UserPromptSubmit", "PreToolUse", "PermissionRequest"}:
            data["hook_busy"] = True
        if name in {"Stop", "Interrupt", "SessionEnd"}:
            data["hook_busy"] = False
        agents = set(data.get("agents", []))
        agent = payload.get("agent_id")
        if name == "SubagentStart":
            agents.add(agent or "unknown")
        elif name == "SubagentStop" and agent:
            agents.discard(agent)
        data["agents"] = sorted(agents)
        data["last_hook"] = now
        data["last_hook_event"] = name
        # SessionEnd/Stop never imply task completion, and don't reset inactivity.
        db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", ("thread:" + tid, json.dumps(data)))
    return {"accepted": True, "thread_id": tid, "event": name}
