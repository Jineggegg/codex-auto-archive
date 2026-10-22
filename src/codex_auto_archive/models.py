from __future__ import annotations

import ntpath
import os
import posixpath
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Days = Annotated[int, Field(strict=True, ge=1, le=36500)]
Minutes = Annotated[int, Field(strict=True, ge=0, le=525600)]
ThreadId = Annotated[
    str, Field(strict=True, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
]
Event = Literal[
    "pr_merged",
    "pr_closed",
    "ci_success",
    "issue_closed",
    "goal_completed",
    "user_explicit_completion",
]
EVENTS = (
    "pr_merged",
    "pr_closed",
    "ci_success",
    "issue_closed",
    "goal_completed",
    "user_explicit_completion",
)


def project_key(value: str) -> str:
    """Keep Windows and WSL stores distinct; never guess that paths share a project."""
    if not value or "\x00" in value:
        raise ValueError("A nonempty absolute project path is required")
    if ntpath.isabs(value) and ("\\" in value or ":" in value or value.startswith("//")):
        return ntpath.normcase(ntpath.normpath(value)).replace("\\", "/")
    if value.startswith("/") and os.name == "nt":
        return posixpath.normpath(value)
    if not os.path.isabs(value):
        raise ValueError("Project paths must be absolute")
    return str(Path(value).resolve())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Policy(StrictModel):
    archive_inactive_threads: bool = True
    inactive_days: Days = 30
    archive_completed_threads: bool = False
    archive_on_pr_merged: bool = False
    archive_on_pr_closed: bool = False
    archive_on_ci_success: bool = False
    archive_on_issue_closed: bool = False
    archive_on_goal_completed: bool = False
    archive_on_user_explicit_completion: bool = False
    completion_grace_minutes: Minutes = 30
    exclude_pinned: bool = True
    excluded_tags: list[str] = Field(default_factory=list, max_length=100)
    # Every event in this group must be true; ungrouped enabled events are OR triggers.
    workflow_all_of: list[Event] = Field(default_factory=list)


class PolicyPatch(StrictModel):
    archive_inactive_threads: bool | None = None
    inactive_days: Days | None = None
    archive_completed_threads: bool | None = None
    archive_on_pr_merged: bool | None = None
    archive_on_pr_closed: bool | None = None
    archive_on_ci_success: bool | None = None
    archive_on_issue_closed: bool | None = None
    archive_on_goal_completed: bool | None = None
    archive_on_user_explicit_completion: bool | None = None
    completion_grace_minutes: Minutes | None = None
    exclude_pinned: bool | None = None
    excluded_tags: list[str] | None = None
    workflow_all_of: list[Event] | None = None

    def changes(self) -> dict:
        return self.model_dump(exclude_none=True)

    @model_validator(mode="after")
    def reject_null(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Omit unchanged fields; explicit null is not a policy value")
        return self


class SettingsPatch(PolicyPatch):
    enabled: bool | None = None
    dry_run: bool | None = None
    check_interval_minutes: Annotated[int, Field(ge=1, le=1440)] | None = None
    restore_cooldown_days: Days | None = None
    max_archives_per_check: Annotated[int, Field(ge=1, le=100)] | None = None
    locale: Literal["auto", "en", "zh-CN", "ja", "es"] | None = None


class Connection(StrictModel):
    command: list[str] = Field(
        default_factory=lambda: ["codex", "app-server", "--listen", "stdio://"], min_length=1
    )
    # True only for an operator-configured shared runtime controlling all relevant clients.
    authoritative: bool = False
    timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 30


class Config(StrictModel):
    schema_version: Literal[1] = 1
    enabled: bool = True
    dry_run: bool = True
    policy: Policy = Field(default_factory=Policy)
    excluded_threads: list[ThreadId] = Field(default_factory=list)
    excluded_projects: list[str] = Field(default_factory=list)
    project_overrides: dict[str, PolicyPatch] = Field(default_factory=dict)
    thread_overrides: dict[ThreadId, PolicyPatch] = Field(default_factory=dict)
    check_interval_minutes: Annotated[int, Field(ge=1, le=1440)] = 60
    restore_cooldown_days: Days = 7
    max_archives_per_check: Annotated[int, Field(ge=1, le=100)] = 20
    locale: Literal["auto", "en", "zh-CN", "ja", "es"] = "auto"
    connection: Connection = Field(default_factory=Connection)

    def effective(self, project: str | None = None, thread_id: str | None = None) -> Policy:
        result = self.policy.model_dump()
        if project and (key := project_key(project)) in self.project_overrides:
            result.update(self.project_overrides[key].changes())
        if thread_id in self.thread_overrides:
            result.update(self.thread_overrides[thread_id].changes())
        return Policy.model_validate(result)


PRESETS = {
    "conservative": {"inactive_days": 90, "completion_grace_minutes": 1440},
    "standard": {"inactive_days": 30, "completion_grace_minutes": 30},
    "aggressive": {"inactive_days": 7, "completion_grace_minutes": 5},
}
