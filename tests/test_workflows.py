import pytest
from conftest import NOW

from codex_auto_archive.github import GitHub
from codex_auto_archive.storage import data_dir


class GitHubFixture(GitHub):
    def __init__(self):
        super().__init__()
        self.requested = []
        self.pr = {
            "state": "closed",
            "merged_at": "2026-10-01T00:00:00Z",
            "head": {"ref": "feature", "sha": "abc"},
            "base": {"repo": {"full_name": "owner/repo"}},
        }
        self.checks = {
            "total_count": 1,
            "check_runs": [{"status": "completed", "conclusion": "success"}],
        }
        self.status = {"total_count": 0, "statuses": [], "state": "pending"}

    async def api(self, endpoint):
        self.requested.append(endpoint)
        if "/pulls/" in endpoint:
            return self.pr
        if "/check-runs?" in endpoint:
            return self.checks
        if "/status?" in endpoint:
            return self.status
        return {"state": "closed"}


async def test_github_exact_mapping_and_independent_network_requests():
    gh = GitHubFixture()
    r = await gh.signals({"repo": "owner/repo", "pr": 1}, required={"pr_merged"})
    assert r["pr_merged"] and len(gh.requested) == 1
    with pytest.raises(RuntimeError, match="branch"):
        await gh.signals({"repo": "owner/repo", "pr": 1, "branch": "wrong"})
    gh.pr["base"]["repo"]["full_name"] = "other/repo"
    with pytest.raises(RuntimeError, match="repository"):
        await gh.signals({"repo": "owner/repo", "pr": 1})


@pytest.mark.parametrize("condition", ["success", "failure", "pending", "empty", "too_many"])
async def test_ci_requires_actual_complete_success(condition):
    gh = GitHubFixture()
    if condition == "failure":
        gh.checks["check_runs"][0]["conclusion"] = "failure"
    elif condition == "pending":
        gh.checks["check_runs"][0]["status"] = "in_progress"
    elif condition == "empty":
        gh.checks = {"total_count": 0, "check_runs": []}
    elif condition == "too_many":
        gh.checks["total_count"] = 101
    r = await gh.signals({"repo": "owner/repo", "pr": 1})
    assert r["ci_success"] == (condition == "success")


async def test_pr_closed_is_not_merged():
    gh = GitHubFixture()
    gh.pr["merged_at"] = None
    r = await gh.signals({"repo": "owner/repo", "pr": 1})
    assert r["pr_closed"] and not r["pr_merged"]


async def test_expired_token_and_lock_conflict(setup_engine):
    s, c, clock, _, e = setup_engine
    p = await e.preview(ids=["one"])
    clock[0] += 601
    with pytest.raises(ValueError, match="expired"):
        await e.execute(p["confirmation_token"], True)
    import portalocker

    with s.lock():
        with pytest.raises(portalocker.exceptions.LockException):
            await e.check()
    assert not c.calls


async def test_tags_and_temporary_pause(setup_engine):
    s, c, clock, _, e = setup_engine
    s.edit(lambda cfg: cfg.policy.excluded_tags.append("keep"))
    s.mutate_activity("one", lambda d: d.update(tags=["keep"]))
    assert "excluded_tag" in (await e.evaluate("one"))["skip_reasons"]
    s.mutate_activity("one", lambda d: d.update(tags=[], pause_until=NOW + 7 * 86400))
    clock[0] += 8 * 86400
    assert (await e.evaluate("one"))["eligible"]


def test_separate_codex_home_profiles(monkeypatch):
    monkeypatch.delenv("CODEX_AUTO_ARCHIVE_HOME", raising=False)
    monkeypatch.setenv("CODEX_HOME", "/tmp/one")
    first = data_dir()
    monkeypatch.setenv("CODEX_HOME", "/tmp/two")
    assert first != data_dir()


async def test_partial_batch_failure_isolation(setup_engine):
    s, c, _, _, e = setup_engine
    c.add("two")
    preview = await e.preview(ids=["one", "two"])
    original = c.call

    async def call(method, params):
        if params["threadId"] == "one":
            raise RuntimeError("one failed")
        return await original(method, params)

    c.call = call
    result = await e.execute(preview["confirmation_token"], True)
    assert result["successful_thread_ids"] == ["two"]
    assert result["failed_thread_ids"] == ["one"]


async def test_cascade_counts_toward_batch_limit(setup_engine):
    s, c, _, _, e = setup_engine
    s.edit(lambda cfg: setattr(cfg, "max_archives_per_check", 1))
    s.edit(lambda cfg: setattr(cfg, "dry_run", False))
    c.add("child", parentThreadId="one")
    c.children["one"] = ["child"]
    row = await e.evaluate("one")
    r = await e.mutate_one(row, True, remaining=1)
    assert r["reason"] == "cascade_exceeds_remaining_batch_limit"
    assert not c.calls
