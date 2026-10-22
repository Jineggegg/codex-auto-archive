import json
import sys
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from codex_auto_archive.models import Config, PolicyPatch, project_key
from codex_auto_archive.scheduler import windows_xml
from codex_auto_archive.service import TOOL_DEFS, Service
from codex_auto_archive.storage import Store


@pytest.mark.parametrize(
    "patch",
    [
        {"inactive_days": 0},
        {"inactive_days": -1},
        {"inactive_days": "7"},
        {"inactive_days": True},
        {"archive_inactive_threads": "yes"},
        {"unknown": True},
        {"inactive_days": None},
    ],
)
def test_strict_validation(patch):
    with pytest.raises(ValidationError):
        PolicyPatch.model_validate(patch)


def test_corrupt_and_migrate(tmp_path):
    s = Store(tmp_path)
    s.config_path.write_text('{"enabled": true, broken', encoding="utf-8")
    c = s.config()
    assert c.dry_run and not c.enabled
    assert list(tmp_path.glob("config.corrupt-*"))
    s.config_path.write_text(json.dumps({"inactive_days": 7, "dry_run": False}), encoding="utf-8")
    assert s.config().policy.inactive_days == 7 and s.config().dry_run


def test_windows_wsl_distinct():
    assert project_key("C:\\Work\\Foo") == project_key("c:/work/foo")
    assert project_key("/mnt/c/work/foo") != project_key("C:\\work\\foo")
    with pytest.raises(ValueError):
        project_key("relative")


def test_windows_task_xml(tmp_path):
    s = Store(tmp_path)
    root = ElementTree.fromstring(windows_xml(s))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert root.find(".//t:StartWhenAvailable", ns).text == "true"
    assert root.find(".//t:Command", ns).text == sys.executable


async def test_natural_language_config_uses_typed_tools(setup_engine):
    s, c, _, _, _ = setup_engine
    service = Service(s, lambda: c)
    r = await service.call(
        "update_archive_settings",
        {
            "settings": {
                "inactive_days": 7,
                "archive_on_pr_merged": True,
                "completion_grace_minutes": 0,
            }
        },
    )
    assert r["settings"]["policy"]["inactive_days"] == 7
    assert r["settings"]["dry_run"]
    with pytest.raises(ValueError):
        await service.call("update_archive_settings", {"settings": {"dry_run": False}})
    r = await service.call(
        "update_archive_settings", {"settings": {"dry_run": False}, "activate": True}
    )
    assert not r["settings"]["dry_run"]


async def test_current_id_never_guessed(setup_engine, monkeypatch):
    s, c, _, _, _ = setup_engine
    service = Service(s, lambda: c)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    with pytest.raises(ValueError, match="Current thread unavailable"):
        await service.call("exclude_thread", {"current": True})
    monkeypatch.setenv("CODEX_THREAD_ID", "one")
    assert (await service.call("exclude_thread", {"current": True}))["excluded"]


async def test_settings_project_thread_preset_reset(setup_engine):
    s, c, _, _, _ = setup_engine
    service = Service(s, lambda: c)
    await service.call(
        "set_project_policy", {"project": "/project", "policy": {"inactive_days": 14}}
    )
    await service.call("set_thread_policy", {"thread_id": "one", "policy": {"inactive_days": 3}})
    r = await service.call("get_archive_settings", {"thread_id": "one"})
    assert r["effective_policy"]["inactive_days"] == 3
    await service.call("set_archive_mode", {"mode": "aggressive"})
    assert s.config().dry_run and s.config().policy.inactive_days == 7
    await service.call("reset_archive_settings", {"confirmed": True})
    assert s.config() == Config()


async def test_all_tool_schemas_disallow_unknown_args(setup_engine):
    s, c, _, _, _ = setup_engine
    service = Service(s, lambda: c)
    for name, (model, _) in TOOL_DEFS.items():
        assert model.model_json_schema()["additionalProperties"] is False
        with pytest.raises(ValueError):
            await service.call(name, {"unexpected": True})


async def test_pause_and_whitelists(setup_engine, monkeypatch):
    s, c, clock, _, e = setup_engine
    monkeypatch.setattr("codex_auto_archive.service.time.time", lambda: clock[0])
    service = Service(s, lambda: c)
    await service.call("exclude_thread", {"thread_id": "one"})
    assert not (await e.evaluate("one"))["eligible"]
    await service.call("include_thread", {"thread_id": "one"})
    await service.call("pause_auto_archive", {"thread_id": "one", "days": 7})
    assert "thread_paused" in (await e.evaluate("one"))["skip_reasons"]
    await service.call("resume_auto_archive", {"thread_id": "one"})
    assert (await e.evaluate("one"))["eligible"]
