import pytest
from conftest import NOW

from codex_auto_archive.hooks import ingest
from codex_auto_archive.models import Policy, PolicyPatch


def policy(store, **changes):
    store.edit(
        lambda c: setattr(c, "policy", Policy.model_validate({**c.policy.model_dump(), **changes}))
    )


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30, 60, 90, 17])
async def test_idle_days(setup_engine, days):
    s, c, clock, gh, e = setup_engine
    policy(s, inactive_days=days)
    c.add("one", days=days - 0.01)
    assert not (await e.evaluate("one"))["eligible"]
    c.add("one", days=days)
    row = await e.evaluate("one")
    assert row["eligible"] and row["triggers"] == ["inactive"]


async def test_creation_metadata_are_not_activity(setup_engine):
    s, c, _, _, e = setup_engine
    c.active["one"]["updatedAt"] = NOW
    assert (await e.evaluate("one"))["eligible"]
    c.turn_data["one"] = []
    assert "activity_unknown" in (await e.evaluate("one"))["skip_reasons"]


async def test_new_prompt_resets_clock(setup_engine):
    s, _, _, _, e = setup_engine
    ingest(
        s, {"session_id": "one", "hook_event_name": "UserPromptSubmit", "event_id": "prompt"}, NOW
    )
    row = await e.evaluate("one")
    assert "inactive" not in row["triggers"]
    assert "hook_reports_active_work" in row["skip_reasons"]


@pytest.mark.parametrize(
    "field",
    [
        "archive_inactive_threads",
        "archive_completed_threads",
        "archive_on_pr_merged",
        "archive_on_ci_success",
    ],
)
async def test_disabled_rules_do_not_trigger(setup_engine, field):
    s, c, _, gh, e = setup_engine
    policy(
        s,
        archive_inactive_threads=False,
        **({field: False} if field != "archive_inactive_threads" else {}),
    )
    c.goals["one"] = {"status": "complete", "updatedAt": NOW}
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    gh.values = {"pr_merged": True, "ci_success": True}
    assert not (await e.evaluate("one"))["eligible"]


async def test_only_pr_merged_and_not_unrelated_repo(setup_engine):
    s, _, _, gh, e = setup_engine
    policy(s, archive_inactive_threads=False, archive_on_pr_merged=True, completion_grace_minutes=0)
    gh.values = {"pr_merged": True}
    assert not (await e.evaluate("one"))["eligible"]
    assert gh.calls == 0
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    assert (await e.evaluate("one"))["eligible"]
    gh.values = {"pr_merged": False}
    assert not (await e.evaluate("one"))["eligible"]


async def test_ci_does_not_imply_completion(setup_engine):
    s, _, _, gh, e = setup_engine
    policy(s, archive_inactive_threads=False, archive_completed_threads=True)
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    gh.values = {"ci_success": True}
    assert not (await e.evaluate("one"))["eligible"]


async def test_all_of_and_or(setup_engine):
    s, _, _, gh, e = setup_engine
    policy(
        s,
        archive_inactive_threads=False,
        archive_on_pr_merged=True,
        archive_on_ci_success=True,
        workflow_all_of=["pr_merged", "ci_success"],
        completion_grace_minutes=0,
    )
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    gh.values = {"pr_merged": True, "ci_success": False}
    assert not (await e.evaluate("one"))["eligible"]
    gh.values["ci_success"] = True
    assert (await e.evaluate("one"))["eligible"]
    policy(s, archive_inactive_threads=True)
    gh.failed = True
    assert (await e.evaluate("one"))["eligible"]  # Independent time rule still works.


async def test_grace_and_activity_cancellation(setup_engine):
    s, c, clock, gh, e = setup_engine
    policy(s, archive_inactive_threads=False, archive_on_pr_merged=True, completion_grace_minutes=5)
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    gh.values = {"pr_merged": True}
    assert "completion_grace_period" in (await e.evaluate("one", persist=True))["skip_reasons"]
    clock[0] += 301
    assert (await e.evaluate("one"))["eligible"]
    ingest(s, {"session_id": "one", "hook_event_name": "PostToolUse", "event_id": "new"}, clock[0])
    assert "completion_cancelled_by_activity" in (await e.evaluate("one"))["skip_reasons"]
    clock[0] += 10000
    assert not (await e.evaluate("one"))["eligible"]


async def test_turn_stop_session_end_are_not_completion(setup_engine):
    s, _, _, _, e = setup_engine
    policy(s, archive_inactive_threads=False, archive_completed_threads=True)
    for name in ("Stop", "SessionEnd"):
        ingest(s, {"session_id": "one", "hook_event_name": name}, NOW)
    assert not (await e.evaluate("one"))["eligible"]


async def test_explicit_completion_and_goal_independent(setup_engine):
    s, c, _, _, e = setup_engine
    policy(
        s,
        archive_inactive_threads=False,
        archive_completed_threads=True,
        completion_grace_minutes=0,
    )
    s.mutate_activity("one", lambda d: d.update(completion={"at": NOW, "generation": 0}))
    assert (await e.evaluate("one"))["eligible"]
    ingest(
        s, {"session_id": "one", "hook_event_name": "UserPromptSubmit", "event_id": "p"}, NOW + 1
    )
    ingest(s, {"session_id": "one", "hook_event_name": "Stop", "event_id": "s"}, NOW + 2)
    assert not (await e.evaluate("one"))["eligible"]
    c.goals["one"] = {"status": "complete", "updatedAt": NOW + 3}
    assert (await e.evaluate("one"))["eligible"]


async def test_priority(setup_engine):
    s, _, _, _, e = setup_engine

    def edit(cfg):
        cfg.policy.inactive_days = 90
        cfg.project_overrides["/project"] = PolicyPatch(inactive_days=60)
        cfg.thread_overrides["one"] = PolicyPatch(inactive_days=7)

    s.edit(edit)
    assert (await e.evaluate("one"))["eligible"]
    s.edit(lambda c: c.excluded_projects.append("/project"))
    assert "project_whitelisted" in (await e.evaluate("one"))["skip_reasons"]


async def test_forecast_read_only_and_token_not_executable(setup_engine):
    s, c, _, _, e = setup_engine
    c.add("one", days=25)
    before = s.activity("one")
    preview = await e.preview(automatic=True, horizon_days=7)
    assert preview["candidate_count"] == 1
    assert s.activity("one") == before
    with pytest.raises(ValueError):
        await e.execute(preview["confirmation_token"], True)
    assert not c.calls


async def test_stale_goal_completion_after_new_turn_without_hooks(setup_engine):
    s, c, _, _, e = setup_engine
    policy(
        s,
        archive_inactive_threads=False,
        archive_completed_threads=True,
        completion_grace_minutes=0,
    )
    c.goals["one"] = {"status": "complete", "updatedAt": NOW - 100}
    c.turn_data["one"].append(
        {"id": "resumed", "status": "completed", "startedAt": NOW - 50, "completedAt": NOW - 40}
    )
    assert not (await e.evaluate("one"))["eligible"]


async def test_disabled_automation_makes_no_github_requests(setup_engine):
    s, c, _, gh, e = setup_engine
    policy(s, archive_on_pr_merged=True)
    s.put("workflow:one", {"repo": "owner/repo", "pr": 1})
    s.edit(lambda cfg: setattr(cfg, "enabled", False))
    await e.check()
    assert gh.calls == 0 and not c.calls
