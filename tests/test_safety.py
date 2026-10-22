import pytest
from conftest import NOW

from codex_auto_archive.hooks import ingest


@pytest.mark.parametrize(
    "status",
    [
        {"type": "active", "activeFlags": []},
        {"type": "active", "activeFlags": ["waitingOnApproval"]},
        {"type": "systemError"},
        {"type": "unexpected"},
    ],
)
async def test_runtime_protection(setup_engine, status):
    _, c, _, _, e = setup_engine
    c.active["one"]["status"] = status
    assert not (await e.evaluate("one"))["eligible"]


@pytest.mark.parametrize("goal", ["active", "blocked", "paused", "budgetLimited", "usageLimited"])
async def test_goal_protection(setup_engine, goal):
    _, c, _, _, e = setup_engine
    c.goals["one"] = {"status": goal}
    assert "goal_not_complete" in (await e.evaluate("one"))["skip_reasons"]


@pytest.mark.parametrize("pin", [True, None])
async def test_pinned_or_unknown_protected(setup_engine, pin):
    _, c, _, _, e = setup_engine
    c.active["one"]["isPinned"] = pin
    assert not (await e.evaluate("one"))["eligible"]


async def test_detached_never_treats_not_loaded_as_idle(setup_engine):
    _, c, _, _, e = setup_engine
    c.connection.authoritative = False
    c.active["one"]["status"] = {"type": "notLoaded"}
    assert "cross_process_runtime_unknown" in (await e.evaluate("one"))["skip_reasons"]


async def test_safe_descendant_and_restore_cooldown(setup_engine):
    s, c, _, _, e = setup_engine
    c.add("child")
    c.children["one"] = ["child"]
    p = await e.preview(ids=["one"])
    result = await e.execute(p["confirmation_token"], True)
    assert result["successful_thread_ids"] == ["child", "one"]
    r = await e.restore(["child", "one"])
    result = await e.restore(["child", "one"], r["confirmation_token"], True)
    assert result["affected_count"] == 2
    assert "restored_thread_cooldown" in (await e.evaluate("one"))["skip_reasons"]
    assert s.history(10, action="restore")


async def test_parent_and_child_active(setup_engine):
    s, c, _, _, e = setup_engine
    c.add("child", parentThreadId="one")
    c.children["one"] = ["child"]
    c.active["child"]["status"] = {"type": "active", "activeFlags": []}
    assert any("unsafe_descendant" in r for r in (await e.evaluate("one"))["skip_reasons"])
    c.active["child"]["status"] = {"type": "idle"}
    c.active["one"]["status"] = {"type": "active", "activeFlags": []}
    assert "unsafe_parent:one" in (await e.evaluate("child"))["skip_reasons"]


async def test_descendant_recent_activity_cannot_be_cascaded(setup_engine):
    _, c, _, _, e = setup_engine
    c.add("child", days=1)
    c.children["one"] = ["child"]
    assert not (await e.evaluate("one"))["eligible"]


@pytest.mark.parametrize(
    "failed", ["thread/turns/list", "thread/goal/get", "thread/read", "descendants"]
)
async def test_read_failure_isolated(setup_engine, failed):
    s, c, _, _, e = setup_engine
    s.edit(lambda cfg: setattr(cfg, "dry_run", False))
    c.fail.add(failed)
    result = await e.check()
    assert result["affected_count"] == 0
    assert not c.calls
    c.fail.clear()
    assert (await e.evaluate("one"))["eligible"]


async def test_dry_run_then_restart_and_duplicate_check(setup_engine):
    s, c, _, _, e = setup_engine
    r = await e.check()
    assert r["candidate_count"] == 1 and not c.calls
    s.edit(lambda cfg: setattr(cfg, "dry_run", False))
    assert (await e.check())["affected_count"] == 1
    assert (await e.check())["affected_count"] == 0
    from codex_auto_archive.storage import Store

    assert Store(s.root).history(1)[0]["action"] == "auto_archive"


async def test_user_restore_detected(setup_engine):
    s, c, _, _, e = setup_engine
    s.edit(lambda cfg: setattr(cfg, "dry_run", False))
    await e.check()
    await c.call("thread/unarchive", {"threadId": "one"})
    assert (await e.check())["affected_count"] == 0
    assert s.activity("one")["cooldown_until"] > NOW


async def test_confirm_token_single_use_and_changed_thread(setup_engine):
    _, c, _, _, e = setup_engine
    p = await e.preview(ids=["one"])
    with pytest.raises(ValueError):
        await e.execute(p["confirmation_token"], False)
    c.active["one"]["updatedAt"] += 1
    r = await e.execute(p["confirmation_token"], True)
    assert not r["affected_count"]
    with pytest.raises(ValueError):
        await e.execute(p["confirmation_token"], True)


async def test_current_deferred_until_idle_new_prompt_cancels(setup_engine):
    s, c, clock, _, e = setup_engine
    p = await e.preview(ids=["one"], current_thread_id="one")
    result = await e.execute(p["confirmation_token"], True, "one")
    assert result["affected_count"] == 0 and result["results"][0]["scheduled"]
    await e.check()
    assert not c.calls
    ingest(
        s, {"session_id": "one", "hook_event_name": "UserPromptSubmit", "event_id": "new"}, NOW + 30
    )
    clock[0] += 61
    await e.check()
    assert not c.calls


async def test_current_deferred_executes_after_delay(setup_engine):
    s, c, clock, _, e = setup_engine
    p = await e.preview(ids=["one"], current_thread_id="one")
    await e.execute(p["confirmation_token"], True, "one")
    clock[0] += 61
    result = await e.check()
    assert result["affected_count"] == 1


async def test_cloud_and_ephemeral_unsupported(setup_engine):
    _, c, _, _, e = setup_engine
    c.active["one"]["source"] = {"custom": "cloud"}
    assert "unsupported_thread_source" in (await e.evaluate("one"))["skip_reasons"]


async def test_hook_dedup_and_subagent_not_cleared_by_stop(setup_engine):
    s, _, _, _, e = setup_engine
    payload = {
        "session_id": "one",
        "hook_event_name": "SubagentStart",
        "agent_id": "child",
        "event_id": "a",
    }
    assert ingest(s, payload, NOW)["accepted"]
    assert not ingest(s, payload, NOW + 1)["accepted"]
    ingest(s, {"session_id": "one", "hook_event_name": "Stop", "event_id": "b"}, NOW + 2)
    assert "hook_reports_active_work" in (await e.evaluate("one"))["skip_reasons"]
    ingest(
        s,
        {
            "session_id": "one",
            "hook_event_name": "SubagentStop",
            "agent_id": "child",
            "event_id": "c",
        },
        NOW + 3,
    )
    assert s.activity("one")["agents"] == []


async def test_restore_exact_token(setup_engine):
    _, c, _, _, e = setup_engine
    await c.call("thread/archive", {"threadId": "one"})
    p = await e.restore(["one"])
    with pytest.raises(ValueError):
        await e.restore(["other"], p["confirmation_token"], True)


async def test_current_new_turn_cancels_without_hooks(setup_engine):
    s, c, clock, _, e = setup_engine
    p = await e.preview(ids=["one"], current_thread_id="one")
    await e.execute(p["confirmation_token"], True, "one")
    c.turn_data["one"].append(
        {"id": "new", "status": "completed", "startedAt": NOW + 30, "completedAt": NOW + 40}
    )
    clock[0] += 61
    result = await e.check()
    assert result["affected_count"] == 0
    assert not s.activity("one").get("pending_manual")


async def test_completion_cancelled_by_new_turn_without_hooks(setup_engine):
    from test_rules import policy

    s, c, clock, gh, e = setup_engine
    policy(s, archive_inactive_threads=False, archive_on_pr_merged=True, completion_grace_minutes=5)
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    gh.values = {"pr_merged": True}
    await e.evaluate("one", persist=True)
    c.turn_data["one"].append(
        {"id": "new", "status": "completed", "startedAt": NOW + 30, "completedAt": NOW + 40}
    )
    clock[0] += 301
    row = await e.evaluate("one", persist=True)
    assert "completion_cancelled_by_activity" in row["skip_reasons"]
    clock[0] += 10000
    assert not (await e.evaluate("one"))["eligible"]
