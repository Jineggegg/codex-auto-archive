from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time

from .github import GitHub
from .models import EVENTS, project_key


class Engine:
    def __init__(self, store, client, clock=time.time, github=None):
        self.store, self.client, self.clock = store, client, clock
        self.github = github or GitHub()

    def settings(self, thread):
        return self.store.config().effective(thread.get("cwd"), thread["id"])

    async def snapshot(self, tid):
        thread = await self.client.read(tid)
        turns = await self.client.turns(tid)
        state = self.store.activity(tid)
        goal = await self.client.goal(tid)  # Missing/failed safety interface must fail closed.
        timestamps = [state.get("last_activity", 0)]
        for turn in turns:
            timestamps.extend([turn.get("startedAt") or 0, turn.get("completedAt") or 0])
        # updatedAt includes metadata changes: never use it as effective activity.
        last = max(timestamps)
        return {
            "thread": thread,
            "turns": turns,
            "state": state,
            "goal": goal,
            "last_activity": last,
        }

    def protection(self, snap, automatic=True, defer_current=False):
        t, state, goal = snap["thread"], snap["state"], snap["goal"]
        cfg = self.store.config()
        policy = cfg.effective(t.get("cwd"), t["id"])
        reasons = []
        if t["id"] in cfg.excluded_threads:
            reasons.append("thread_whitelisted")
        if t.get("cwd") and project_key(t["cwd"]) in cfg.excluded_projects:
            reasons.append("project_whitelisted")
        if set(state.get("tags", [])) & set(policy.excluded_tags):
            reasons.append("excluded_tag")
        if state.get("pause_until", 0) > self.clock():
            reasons.append("thread_paused")
        if automatic and state.get("cooldown_until", 0) > self.clock():
            reasons.append("restored_thread_cooldown")
        if policy.exclude_pinned:
            pin = t.get("isPinned")
            if pin is True:
                reasons.append("pinned")
            elif pin is not False:
                reasons.append("pin_state_unsupported")
        source = t.get("source")
        local_source = (
            source in ("cli", "vscode", "exec", "appServer")
            if isinstance(source, str)
            else isinstance(source, dict) and "subAgent" in source
        )
        if not local_source or t.get("ephemeral"):
            reasons.append("unsupported_thread_source")
        status = t.get("status", {}).get("type")
        if status not in ("idle", "notLoaded") and not defer_current:
            reasons.append("runtime_" + str(status))
        if not self.client.connection.authoritative and t["id"] not in self.client.owned_ids:
            reasons.append("cross_process_runtime_unknown")
        if (state.get("hook_busy") or state.get("agents")) and not defer_current:
            reasons.append("hook_reports_active_work")
        if any(turn.get("status") == "inProgress" for turn in snap["turns"]) and not defer_current:
            reasons.append("turn_in_progress")
        if goal and goal.get("status") != "complete":
            reasons.append("goal_not_complete")
        return reasons

    async def evaluate(
        self, tid, automatic=True, horizon_days=0, defer_current=False, persist=False
    ):
        snap = await self.snapshot(tid)
        thread = snap["thread"]
        reasons = self.protection(snap, automatic, defer_current)
        parent_id = thread.get("parentThreadId")
        seen_parents = {tid}
        while parent_id:
            if parent_id in seen_parents or len(seen_parents) > 32:
                reasons.append("invalid_parent_tree")
                break
            seen_parents.add(parent_id)
            parent = await self.snapshot(parent_id)
            if self.protection(parent, automatic):
                reasons.append("unsafe_parent:" + parent_id)
            parent_id = parent["thread"].get("parentThreadId")
        descendants = await self.client.descendants(tid)
        child_ids = sorted(t["id"] for t in descendants)
        for child in descendants:
            child_snap = await self.snapshot(child["id"])
            blocked = self.protection(child_snap, automatic)
            # A descendant lacking usable activity/history is also unknown.
            if not child_snap["last_activity"]:
                blocked.append("activity_unknown")
            if automatic and child_snap["last_activity"] > snap["last_activity"]:
                blocked.append("descendant_has_newer_activity")
            if blocked:
                reasons.append("unsafe_descendant:" + child["id"] + ":" + ",".join(blocked))
        policy = self.settings(thread)
        triggers, errors = [], []
        now = self.clock()
        last = snap["last_activity"]
        due = last + policy.inactive_days * 86400 if last else None
        if automatic:
            cfg = self.store.config()
            if not cfg.enabled or self.store.get("pause_until", 0) > now:
                reasons.append("automation_paused")
            if (
                policy.archive_inactive_threads
                and due is not None
                and due <= now + horizon_days * 86400
            ):
                triggers.append("inactive")
            signals = {}
            completion = snap["state"].get("completion", {})
            signals["user_explicit_completion"] = bool(completion) and completion.get(
                "generation", 0
            ) == snap["state"].get("user_generation", 0)
            signals["goal_completed"] = bool(
                snap["goal"]
                and snap["goal"]["status"] == "complete"
                and snap["goal"].get("updatedAt", 0)
                >= max(
                    snap["state"].get("last_user_prompt", 0),
                    max([t.get("startedAt") or 0 for t in snap["turns"]], default=0),
                )
            )
            enabled = [event for event in EVENTS if getattr(policy, "archive_on_" + event)]
            if "automation_paused" in reasons:
                enabled = []
            remote = set(enabled) & {"pr_merged", "pr_closed", "ci_success", "issue_closed"}
            if remote:
                mapping = self.store.get("workflow:" + tid)
                if mapping:
                    try:
                        signals.update(await self.github.signals(mapping, required=remote))
                    except (RuntimeError, OSError, ValueError, KeyError) as e:
                        errors.append(str(e))
                else:
                    errors.append("workflow_mapping_missing")
            group = set(policy.workflow_all_of)
            if group:
                if group.issubset(enabled) and all(signals.get(e, False) for e in group):
                    triggers.append("all_of:" + "+".join(sorted(group)))
            triggers.extend(e for e in enabled if e not in group and signals.get(e, False))
            if (
                "automation_paused" not in reasons
                and policy.archive_completed_threads
                and (signals["goal_completed"] or signals["user_explicit_completion"])
            ):
                triggers.append("completed")
            if not triggers:
                reasons.append("no_enabled_trigger")
            if not last:
                reasons.append("activity_unknown")
            non_time = [x for x in triggers if x != "inactive"]
            if non_time and "inactive" not in triggers:
                pending = snap["state"].get("pending_auto")
                signal_key = hashlib.sha256(
                    json.dumps(
                        [
                            sorted(non_time),
                            completion.get("at"),
                            (snap["goal"] or {}).get("updatedAt"),
                            signals.get("_revision"),
                            self.store.get("workflow:" + tid),
                        ],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                signature = hashlib.sha256(json.dumps([last, signal_key]).encode()).hexdigest()
                if snap["state"].get("cancelled_signal_key") == signal_key:
                    reasons.append("completion_cancelled_by_activity")
                if (
                    pending
                    and pending.get("activity_at", last) != last
                    and pending.get("signal_key") == signal_key
                ):
                    reasons.append("completion_cancelled_by_activity")
                    if persist:
                        self.store.mutate_activity(
                            tid, lambda d: d.update(cancelled_signal_key=signal_key)
                        )
                if not pending or pending.get("signature") != signature:
                    pending = {
                        "signature": signature,
                        "signal_key": signal_key,
                        "activity_at": last,
                        "due": now + policy.completion_grace_minutes * 60,
                    }
                    if persist and "completion_cancelled_by_activity" not in reasons:
                        self.store.mutate_activity(tid, lambda d: d.update(pending_auto=pending))
                if pending["due"] > now:
                    reasons.append("completion_grace_period")
                    due = pending["due"]
            elif not non_time and persist:
                self.store.mutate_activity(tid, lambda d: d.pop("pending_auto", None))
        else:
            triggers = ["manual"]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "last": last,
                    "updated": thread.get("updatedAt"),
                    "children": child_ids,
                    "generation": snap["state"].get("user_generation", 0),
                    "config": self.store.config().model_dump(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return {
            "thread_id": tid,
            "name": thread.get("name"),
            "project": thread.get("cwd"),
            "last_activity": last or None,
            "latest_turn_started_at": max(
                [t.get("startedAt") or 0 for t in snap["turns"]], default=0
            ),
            "due_at": due,
            "triggers": triggers,
            "skip_reasons": reasons,
            "workflow_errors": errors,
            "descendants": child_ids,
            "fingerprint": fingerprint,
            "eligible": not reasons,
            "deferred": defer_current,
        }

    async def preview(
        self,
        ids=None,
        project=None,
        inactive_days=None,
        horizon_days=0,
        automatic=False,
        current_thread_id=None,
    ):
        threads = await self.client.threads()
        available = {t["id"]: t for t in threads}
        selected = list(ids) if ids is not None else list(available)
        rows = []
        for tid in selected:
            if tid not in available:
                rows.append(
                    {
                        "thread_id": tid,
                        "eligible": False,
                        "skip_reasons": ["not_found_in_local_active_store"],
                    }
                )
                continue
            if project and project_key(available[tid]["cwd"]) != project_key(project):
                continue
            try:
                row = await self.evaluate(
                    tid, automatic, horizon_days, tid == current_thread_id and not automatic
                )
                if inactive_days and (
                    not row["last_activity"]
                    or row["last_activity"] > self.clock() - inactive_days * 86400
                ):
                    row["eligible"] = False
                    row["skip_reasons"].append("below_requested_inactivity")
                rows.append(row)
            except Exception as e:
                rows.append(
                    {
                        "thread_id": tid,
                        "eligible": False,
                        "skip_reasons": ["safety_read_failed:" + str(e)],
                    }
                )
        token = secrets.token_urlsafe(24)
        candidates = [r for r in rows if r["eligible"]][:100]
        selected_ids = {r["thread_id"] for r in candidates}
        for row in rows:
            if row["eligible"] and row["thread_id"] not in selected_ids:
                row["eligible"] = False
                row["skip_reasons"].append("batch_limit_100")
        self.store.put(
            "preview:" + token,
            {
                "expires": self.clock() + 600,
                "rows": candidates,
                "action": "auto_preview" if automatic else "archive",
            },
        )
        return {
            "executed": False,
            "affected_count": 0,
            "candidate_count": len(candidates),
            "threads": rows,
            "confirmation_token": token,
            "expires_at": self.clock() + 600,
            "automatic": automatic,
        }

    async def mutate_one(self, row, automatic=False, remaining=100):
        tid = row["thread_id"]
        # Read every protection and descendant again immediately before mutation.
        fresh = await self.evaluate(tid, automatic)
        if not fresh["eligible"] or fresh["fingerprint"] != row["fingerprint"]:
            return {
                "thread_id": tid,
                "success": False,
                "reason": "changed_or_unsafe",
                "skip_reasons": fresh["skip_reasons"],
            }
        if 1 + len(fresh["descendants"]) > remaining:
            return {
                "thread_id": tid,
                "success": False,
                "reason": "cascade_exceeds_remaining_batch_limit",
            }
        if automatic and (self.store.config().dry_run or not self.store.config().enabled):
            return {
                "thread_id": tid,
                "success": False,
                "reason": "automation_disabled_before_mutation",
            }
        self.store.audit(
            "archive_attempt",
            tid,
            {
                "triggers": fresh["triggers"],
                "descendants": fresh["descendants"],
                "automatic": automatic,
            },
        )
        # No mutation retry: an RPC timeout has an unknown outcome, verified on the next check.
        await self.client.call("thread/archive", {"threadId": tid})
        archived = {t["id"] for t in await self.client.threads(archived=True)}
        expected = [tid, *fresh["descendants"]]
        succeeded = [t for t in expected if t in archived]
        failed = [t for t in expected if t not in archived]
        result = {
            "thread_id": tid,
            "success": tid in archived,
            "successful_thread_ids": succeeded,
            "failed_thread_ids": failed,
            "triggers": fresh["triggers"],
            "recoverable": succeeded,
        }
        for actual in succeeded:
            self.store.mutate_activity(
                actual,
                lambda d: d.update(plugin_archived_at=self.clock(), archive_automatic=automatic),
            )
            self.store.audit("auto_archive" if automatic else "manual_archive", actual, result)
        if failed:
            self.store.audit("archive_verification_failed", tid, result)
        return result

    async def execute(self, token, confirmed=False, current_thread_id=None):
        if not confirmed:
            raise ValueError("Explicit user confirmation of the displayed preview is required")
        with self.store.lock():
            preview = self.store.get("preview:" + token)
            if (
                not preview
                or preview.get("action") != "archive"
                or preview["expires"] < self.clock()
            ):
                raise ValueError("Preview is missing, expired or already consumed; preview again")
            self.store.put("preview:" + token, None)
            results = []
            for row in preview["rows"]:
                tid = row["thread_id"]
                if row.get("deferred") or tid == current_thread_id:
                    state = self.store.activity(tid)
                    pending = {
                        "due": self.clock() + 60,
                        "generation": state.get("user_generation", 0),
                        "expires": self.clock() + 86400,
                        "queued_at": self.clock(),
                    }
                    self.store.mutate_activity(
                        tid, lambda d, pending=pending: d.update(pending_manual=pending)
                    )
                    self.store.put("next_manual_due", pending["due"])
                    results.append(
                        {
                            "thread_id": tid,
                            "success": False,
                            "scheduled": True,
                            "due_at": pending["due"],
                            "reason": "current_thread_waits_for_idle",
                        }
                    )
                    continue
                try:
                    results.append(await self.mutate_one(row))
                except Exception as e:
                    results.append(
                        {
                            "thread_id": tid,
                            "success": False,
                            "reason": str(e),
                            "outcome": "unknown_check_history_before_retry",
                        }
                    )
                    self.store.audit("archive_error", tid, results[-1])
                await asyncio.sleep(0.1)
            return self.result(results)

    @staticmethod
    def result(results):
        success = sorted({tid for r in results for tid in r.get("successful_thread_ids", [])})
        failed = sorted(
            {tid for r in results for tid in r.get("failed_thread_ids", [])}
            | {r["thread_id"] for r in results if not r.get("success") and not r.get("scheduled")}
        )
        return {
            "affected_count": len(success),
            "successful_thread_ids": success,
            "failed_thread_ids": failed,
            "recoverable_thread_ids": success,
            "results": results,
        }

    async def restore(self, ids, token=None, confirmed=False):
        with self.store.lock():
            if not confirmed:
                archived = {t["id"]: t for t in await self.client.threads(archived=True)}
                token = secrets.token_urlsafe(24)
                selected = [i for i in ids if i in archived]
                self.store.put(
                    "preview:" + token,
                    {"expires": self.clock() + 600, "ids": selected, "action": "restore"},
                )
                return {
                    "executed": False,
                    "affected_count": 0,
                    "candidate_count": len(selected),
                    "threads": [
                        {"thread_id": i, "name": archived[i].get("name")} for i in selected
                    ],
                    "skipped_thread_ids": [i for i in ids if i not in archived],
                    "confirmation_token": token,
                }
            preview = self.store.get("preview:" + str(token))
            if (
                not preview
                or preview.get("action") != "restore"
                or preview["expires"] < self.clock()
                or set(ids) != set(preview["ids"])
            ):
                raise ValueError("Restore requires a fresh preview token for these exact IDs")
            self.store.put("preview:" + str(token), None)
            results = []
            for tid in ids:
                try:
                    await self.client.call("thread/unarchive", {"threadId": tid})
                    active = {t["id"] for t in await self.client.threads()}
                    if tid not in active:
                        raise RuntimeError("Restore verification failed")
                    self.cooldown(tid)
                    result = {
                        "thread_id": tid,
                        "success": True,
                        "successful_thread_ids": [tid],
                        "cooldown_until": self.store.activity(tid)["cooldown_until"],
                    }
                    self.store.audit("restore", tid, result)
                    results.append(result)
                except Exception as e:
                    results.append({"thread_id": tid, "success": False, "reason": str(e)})
                await asyncio.sleep(0.1)
            return self.result(results)

    def cooldown(self, tid):
        until = self.clock() + self.store.config().restore_cooldown_days * 86400

        def update(data):
            data["cooldown_until"] = until
            data.pop("plugin_archived_at", None)
            data.pop("pending_auto", None)
            data.pop("pending_manual", None)

        self.store.mutate_activity(tid, update)

    async def check(self, force_dry_run=False):
        with self.store.lock():
            cfg = self.store.config()
            now = self.clock()
            self.store.put("last_check_started", now)
            rows, results = [], []
            # Discovery must complete before any mutation: pagination errors cannot yield a partial batch.
            threads = await self.client.threads()
            for thread in threads:
                tid = thread["id"]
                state = self.store.activity(tid)
                if state.get("plugin_archived_at"):
                    self.cooldown(tid)  # User restored through Codex itself.
                    self.store.audit("external_restore_observed", tid, {"cooldown": True})
                pending = self.store.activity(tid).get("pending_manual")
                if pending:
                    valid = (
                        pending["generation"] == state.get("user_generation", 0)
                        and pending["expires"] > now
                    )
                    if valid and pending["due"] <= now:
                        try:
                            row = await self.evaluate(tid, False)
                            if row.get("latest_turn_started_at", 0) > pending.get("queued_at", 0):
                                self.store.mutate_activity(
                                    tid, lambda d: d.pop("pending_manual", None)
                                )
                            elif row["eligible"] and not force_dry_run:
                                results.append(await self.mutate_one(row, False))
                                self.store.mutate_activity(
                                    tid, lambda d: d.pop("pending_manual", None)
                                )
                        except Exception as e:
                            results.append({"thread_id": tid, "success": False, "reason": str(e)})
                    elif not valid:
                        self.store.mutate_activity(tid, lambda d: d.pop("pending_manual", None))
                try:
                    row = await self.evaluate(tid, True, persist=True)
                    rows.append(row)
                    if (
                        row["eligible"]
                        and self.store.config().enabled
                        and not self.store.config().dry_run
                        and not force_dry_run
                        and len(results) < cfg.max_archives_per_check
                    ):
                        results.append(
                            await self.mutate_one(
                                row,
                                True,
                                remaining=cfg.max_archives_per_check
                                - sum(len(r.get("successful_thread_ids", [])) for r in results),
                            )
                        )
                        await asyncio.sleep(0.1)
                except Exception as e:
                    rows.append(
                        {
                            "thread_id": tid,
                            "eligible": False,
                            "skip_reasons": ["safety_read_failed:" + str(e)],
                        }
                    )
            reason_counts = {}
            for row in rows:
                for reason in row.get("skip_reasons", []):
                    category = reason.split(":", 1)[0]
                    reason_counts[category] = reason_counts.get(category, 0) + 1
            self.store.put(
                "last_scan_report",
                {"checked_at": now, "threads": rows, "skip_reason_counts": reason_counts},
            )
            result = {
                **self.result(results),
                "dry_run": self.store.config().dry_run or force_dry_run,
                "candidate_count": sum(r["eligible"] for r in rows),
                "threads": rows,
                "checked_at": now,
                "next_check_at": now + cfg.check_interval_minutes * 60,
            }
            # Keep unresolved/future manual deferrals eligible for the next one-minute wakeup.
            with self.store.db() as db:
                states = [
                    json.loads(r[0])
                    for r in db.execute("SELECT value FROM state WHERE key LIKE 'thread:%'")
                ]
            manual_times = [
                max(now + 60, d["pending_manual"]["due"]) for d in states if "pending_manual" in d
            ]
            self.store.put("next_manual_due", min(manual_times) if manual_times else 0)
            self.store.put(
                "last_check",
                {
                    "at": now,
                    "next_check_at": result["next_check_at"],
                    "candidate_count": result["candidate_count"],
                    "skip_reason_counts": reason_counts,
                    "affected_count": result["affected_count"],
                    "dry_run": result["dry_run"],
                },
            )
            return result
