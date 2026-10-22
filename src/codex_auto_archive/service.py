from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .appserver import AppServer
from .engine import Engine
from .models import (
    PRESETS,
    Config,
    Days,
    Policy,
    PolicyPatch,
    SettingsPatch,
    StrictModel,
    ThreadId,
    project_key,
)
from .storage import Store

Ids = Annotated[list[ThreadId], Field(min_length=1, max_length=100)]


class Empty(StrictModel):
    pass


class Scope(StrictModel):
    thread_id: ThreadId | None = None
    project: str | None = None


class Update(StrictModel):
    settings: SettingsPatch
    activate: bool = False


class ListArgs(StrictModel):
    archived: bool = False
    project: str | None = None
    limit: Annotated[int, Field(ge=1, le=1000)] = 100


class Preview(StrictModel):
    thread_ids: Ids | None = None
    project: str | None = None
    inactive_days: Days | None = None
    horizon_days: Annotated[int, Field(ge=0, le=36500)] = 0
    automatic: bool = False
    current: bool = False


class Archive(StrictModel):
    confirmation_token: str
    confirmed: bool


class Restore(StrictModel):
    thread_ids: Ids
    confirmation_token: str | None = None
    confirmed: bool = False


class ThreadArg(StrictModel):
    thread_id: ThreadId | None = None
    current: bool = False


class ProjectArg(StrictModel):
    project: str


class ProjectPolicy(ProjectArg):
    policy: PolicyPatch


class ThreadPolicy(ThreadArg):
    policy: PolicyPatch


class History(StrictModel):
    limit: Annotated[int, Field(ge=1, le=1000)] = 10
    since: Annotated[int, Field(ge=0)] = 0
    action: (
        Literal[
            "auto_archive",
            "manual_archive",
            "restore",
            "archive_error",
            "archive_attempt",
            "external_restore_observed",
        ]
        | None
    ) = None


class Check(StrictModel):
    dry_run: bool = True


class Pause(ThreadArg):
    days: Days | None = None


class Preset(StrictModel):
    mode: Literal["conservative", "standard", "aggressive", "custom"]


class Reset(StrictModel):
    confirmed: bool = False


class Workflow(ThreadArg):
    repo: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    pr: Annotated[int, Field(ge=1)] | None = None
    issue: Annotated[int, Field(ge=1)] | None = None
    branch: str | None = None
    confirmed: bool


class Completion(ThreadArg):
    confirmed: bool
    evidence: Literal["user_explicit_completion"]


class Tags(ThreadArg):
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=100)


TOOL_DEFS = {
    "get_archive_settings": (
        Scope,
        "Read persisted global settings and effective project/thread policy.",
    ),
    "update_archive_settings": (
        Update,
        "Update independent global archive rules. Leaving Dry Run requires activate=true only after the user explicitly enables real automation. Never infer this consent.",
    ),
    "get_archive_status": (
        Empty,
        "Show health, last/next checks, runtime limitations, storage and defaults.",
    ),
    "list_threads": (
        ListArgs,
        "List local manageable threads with exact IDs. Never guess the current ID from recency or title.",
    ),
    "preview_archive": (
        Preview,
        "Read-only preview including candidates, descendants, skip reasons and a 10-minute confirmation token. Show preview to user before archive_threads.",
    ),
    "archive_threads": (
        Archive,
        "Execute the exact preview only after explicit user confirmation. Recheck live safety; current thread is delayed at least 60 seconds and until idle.",
    ),
    "restore_threads": (
        Restore,
        "First call confirmed=false to preview exact IDs. Then obtain user confirmation and call with token. Restores native Codex Archive; sets cooldown.",
    ),
    "exclude_thread": (
        ThreadArg,
        "Permanently whitelist an exact thread (or current=true with reliable CODEX_THREAD_ID).",
    ),
    "include_thread": (
        ThreadArg,
        "Remove permanent thread whitelist. Other protections still apply.",
    ),
    "exclude_project": (
        ProjectArg,
        "Permanently exclude the exact absolute project path from archiving.",
    ),
    "include_project": (ProjectArg, "Remove an exact project exclusion."),
    "set_project_policy": (ProjectPolicy, "Set project-specific independent rule overrides."),
    "set_thread_policy": (ThreadPolicy, "Set thread-specific independent rule overrides."),
    "get_archive_history": (
        History,
        "Read actual operation audit. For yesterday use a UTC Unix timestamp; auto_archive shows only verified successful automatic archives.",
    ),
    "run_archive_check": (
        Check,
        "Run rule evaluation now. Defaults to Dry Run. Real execution still obeys persisted Dry Run, exclusions and runtime protections.",
    ),
    "pause_auto_archive": (
        Pause,
        "Pause globally or an exact thread, temporarily for days or indefinitely when omitted.",
    ),
    "resume_auto_archive": (
        ThreadArg,
        "Remove a global/thread temporary pause; does not change Dry Run or independent rules.",
    ),
    "set_archive_mode": (
        Preset,
        "Conservative=90d, standard=30d, aggressive=7d. All presets disable completion/workflow rules, retain pin protection and never activate real execution. Custom leaves existing settings.",
    ),
    "reset_archive_settings": (
        Reset,
        "Reset all policies and exclusions to defaults, with Dry Run enabled. Requires explicit confirmation.",
    ),
    "link_workflow": (
        Workflow,
        "Explicitly associate exact thread with owner/repo and PR/Issue. Verify via existing gh auth; no token requested. Must be confirmed by the user.",
    ),
    "record_completion": (
        Completion,
        "Record user's explicit statement that this entire thread task is finished. Stop/SessionEnd/turn completion never count. Do not invent completion evidence.",
    ),
    "set_thread_tags": (Tags, "Set reliable plugin-owned thread tags used by exclusion rules."),
}


class Service:
    def __init__(self, store=None, client_factory=None):
        self.store = store or Store()
        self.client_factory = client_factory or (lambda: AppServer(self.store.config().connection))

    @asynccontextmanager
    async def engine(self):
        async with self.client_factory() as client:
            yield Engine(self.store, client)

    async def resolve(self, args):
        tid = args.thread_id
        if args.current:
            actual = os.environ.get("CODEX_THREAD_ID")
            if not actual or (tid and tid != actual):
                raise ValueError(
                    "Current thread unavailable or mismatched. Use list_threads and ask the user to select an exact ID; do not guess."
                )
            tid = actual
        if not tid:
            raise ValueError("Provide an exact thread_id or current=true")
        tid = TypeAdapter(ThreadId).validate_python(tid)
        async with self.engine() as engine:
            await engine.client.read(tid)
        return tid

    async def call(self, name, arguments):
        if name not in TOOL_DEFS:
            raise ValueError("Unknown tool")
        args = TOOL_DEFS[name][0].model_validate(arguments)
        store = self.store
        if name == "get_archive_settings":
            cfg = store.config()
            project = args.project
            if args.thread_id and not project:
                async with self.engine() as engine:
                    project = (await engine.client.read(args.thread_id)).get("cwd")
            return {
                "settings": cfg.model_dump(),
                "effective_policy": cfg.effective(project, args.thread_id).model_dump(),
                "affected_count": 0,
            }
        if name == "update_archive_settings":
            patch = args.settings.changes()
            if patch.get("dry_run") is False and not args.activate:
                raise ValueError(
                    "Keep Dry Run until the user explicitly enables real automation; then pass activate=true"
                )

            def update(cfg):
                policy = {k: v for k, v in patch.items() if k in Policy.model_fields}
                cfg.policy = Policy.model_validate({**cfg.policy.model_dump(), **policy})
                for k, v in patch.items():
                    if k not in Policy.model_fields:
                        setattr(cfg, k, v)

            cfg = store.edit(update)
            store.audit("settings_updated", None, {"changes": patch})
            return {"updated": True, "affected_count": 0, "settings": cfg.model_dump()}
        if name == "get_archive_status":
            cfg = store.config()
            last = store.get("last_check", {})
            return {
                "enabled": cfg.enabled,
                "dry_run": cfg.dry_run,
                "locale": cfg.locale,
                "pause_until": store.get("pause_until", 0),
                "last_check": last,
                "last_error": store.get("last_error"),
                "next_check_at": last.get("at", time.time()) + cfg.check_interval_minutes * 60,
                "scheduler": store.get("scheduler", {"installed": False}),
                "storage": str(store.root),
                "connection": cfg.connection.model_dump(),
                "affected_count": 0,
                "limitations": [
                    "Detached app-server cannot prove Desktop/other-process runtime safety; automatic execution is blocked unless a shared controlling runtime is explicitly configured.",
                    "Pin protection skips threads when the installed protocol does not expose isPinned.",
                    "Hooks need the user's native Codex trust review. This installer does not bypass hook trust.",
                    "No atomic compare-and-archive API; final recheck reduces but cannot remove concurrent-activity races in a shared runtime.",
                ],
            }
        if name == "list_threads":
            async with self.engine() as engine:
                threads = await engine.client.threads(
                    args.archived, **({"cwd": args.project} if args.project else {})
                )
            # Don't return transcript contents or unstable filesystem paths.
            fields = (
                "id",
                "name",
                "cwd",
                "source",
                "status",
                "updatedAt",
                "isPinned",
                "parentThreadId",
            )
            return {
                "threads": [{k: t.get(k) for k in fields} for t in threads[: args.limit]],
                "total_count": len(threads),
                "truncated": len(threads) > args.limit,
                "affected_count": 0,
            }
        if name == "preview_archive":
            current = None
            if args.current:
                current = await self.resolve(ThreadArg(current=True))
                if args.thread_ids and args.thread_ids != [current]:
                    raise ValueError("current=true must target only the verified current thread")
            async with self.engine() as engine:
                return await engine.preview(
                    ids=[current] if current else args.thread_ids,
                    project=args.project,
                    inactive_days=args.inactive_days,
                    horizon_days=args.horizon_days,
                    automatic=args.automatic,
                    current_thread_id=current,
                )
        if name == "archive_threads":
            async with self.engine() as engine:
                return await engine.execute(
                    args.confirmation_token, args.confirmed, os.environ.get("CODEX_THREAD_ID")
                )
        if name == "restore_threads":
            async with self.engine() as engine:
                return await engine.restore(
                    args.thread_ids, args.confirmation_token, args.confirmed
                )
        if name in (
            "exclude_thread",
            "include_thread",
            "set_thread_policy",
            "set_thread_tags",
            "record_completion",
            "link_workflow",
        ):
            tid = await self.resolve(args)
            if name in ("exclude_thread", "include_thread"):

                def change(cfg):
                    ids = set(cfg.excluded_threads)
                    (ids.add if name == "exclude_thread" else ids.discard)(tid)
                    cfg.excluded_threads = sorted(ids)

                cfg = store.edit(change)
                return {
                    "updated": True,
                    "thread_id": tid,
                    "excluded": tid in cfg.excluded_threads,
                    "affected_count": 1,
                }
            if name == "set_thread_policy":

                def change(cfg):
                    old = cfg.thread_overrides.get(tid, PolicyPatch()).changes()
                    cfg.thread_overrides[tid] = PolicyPatch.model_validate(
                        {**old, **args.policy.changes()}
                    )

                cfg = store.edit(change)
                return {
                    "updated": True,
                    "thread_id": tid,
                    "policy": cfg.thread_overrides[tid].changes(),
                    "affected_count": 1,
                }
            if name == "set_thread_tags":
                store.mutate_activity(tid, lambda d: d.update(tags=args.tags))
                return {"updated": True, "thread_id": tid, "tags": args.tags, "affected_count": 1}
            if name == "record_completion":
                if not args.confirmed:
                    raise ValueError("The user must explicitly declare the thread's task complete")
                store.mutate_activity(
                    tid,
                    lambda d: d.update(
                        completion={
                            "at": time.time(),
                            "evidence": args.evidence,
                            "generation": d.get("user_generation", 0),
                        }
                    ),
                )
                return {"recorded": True, "thread_id": tid, "archived": False, "affected_count": 0}
            if not args.confirmed or not (args.pr or args.issue):
                raise ValueError("A user-confirmed exact PR or Issue mapping is required")
            mapping = {
                k: v
                for k, v in args.model_dump().items()
                if k in ("repo", "pr", "issue", "branch") and v is not None
            }
            from .github import GitHub

            signals = await GitHub().signals(mapping)
            store.put("workflow:" + tid, mapping)
            return {
                "linked": True,
                "thread_id": tid,
                "mapping": mapping,
                "verified_signals": signals,
                "affected_count": 1,
            }
        if name in ("exclude_project", "include_project", "set_project_policy"):
            key = project_key(args.project)

            def change(cfg):
                if name == "set_project_policy":
                    old = cfg.project_overrides.get(key, PolicyPatch()).changes()
                    cfg.project_overrides[key] = PolicyPatch.model_validate(
                        {**old, **args.policy.changes()}
                    )
                else:
                    projects = set(cfg.excluded_projects)
                    (projects.add if name == "exclude_project" else projects.discard)(key)
                    cfg.excluded_projects = sorted(projects)

            cfg = store.edit(change)
            return {
                "updated": True,
                "project": key,
                "policy": cfg.effective(key).model_dump(),
                "excluded": key in cfg.excluded_projects,
                "affected_count": 1,
            }
        if name == "get_archive_history":
            return {
                "history": store.history(args.limit, args.since, args.action),
                "affected_count": 0,
            }
        if name == "run_archive_check":
            async with self.engine() as engine:
                return await engine.check(args.dry_run)
        if name in ("pause_auto_archive", "resume_auto_archive"):
            tid = await self.resolve(args) if args.thread_id or args.current else None
            until = (
                (time.time() + args.days * 86400 if args.days else 253402300799)
                if name == "pause_auto_archive"
                else 0
            )
            if tid:
                store.mutate_activity(tid, lambda d: d.update(pause_until=until))
            else:
                store.put("pause_until", until)
            return {
                "updated": True,
                "thread_id": tid,
                "pause_until": until,
                "affected_count": 1 if tid else 0,
            }
        if name == "set_archive_mode":
            if args.mode != "custom":
                store.edit(
                    lambda cfg: setattr(
                        cfg,
                        "policy",
                        Policy.model_validate({**Policy().model_dump(), **PRESETS[args.mode]}),
                    )
                )
            return {
                "mode": args.mode,
                "effective_policy": store.config().policy.model_dump(),
                "dry_run": store.config().dry_run,
                "affected_count": 0,
            }
        if name == "reset_archive_settings":
            if not args.confirmed:
                raise ValueError("Confirm resetting policies and whitelist")

            def reset(cfg):
                defaults = Config(connection=cfg.connection)
                for key in Config.model_fields:
                    setattr(cfg, key, getattr(defaults, key))

            cfg = store.edit(reset)
            store.put("pause_until", 0)
            return {"reset": True, "settings": cfg.model_dump(), "affected_count": 0}
        raise ValueError("Unimplemented tool")
