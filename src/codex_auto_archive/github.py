from __future__ import annotations

import asyncio
import json
import re


class GitHub:
    """Use existing gh authentication. Cache only within a single scan."""

    def __init__(self):
        self.cache = {}

    async def api(self, endpoint):
        if endpoint in self.cache:
            return self.cache[endpoint]
        p = await asyncio.create_subprocess_exec(
            "gh", "api", endpoint, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            out, _ = await asyncio.wait_for(p.communicate(), 20)
        except TimeoutError:
            p.kill()
            await p.wait()
            raise RuntimeError("GitHub timeout; workflow trigger not confirmed") from None
        if p.returncode:
            raise RuntimeError("GitHub unavailable or unauthorized; workflow trigger not confirmed")
        value = json.loads(out)
        self.cache[endpoint] = value
        return value

    async def signals(self, mapping, required=None):
        required = (
            set(required)
            if required is not None
            else {"pr_merged", "pr_closed", "ci_success", "issue_closed"}
        )
        repo = mapping["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Expected owner/repo")
        result = {}
        if number := mapping.get("pr"):
            pr = await self.api(f"repos/{repo}/pulls/{number}")
            if pr.get("base", {}).get("repo", {}).get("full_name", "").lower() != repo.lower():
                raise RuntimeError("PR repository does not match the confirmed mapping")
            if mapping.get("branch") and pr["head"]["ref"] != mapping["branch"]:
                raise RuntimeError("PR branch no longer matches the confirmed mapping")
            result.update(
                pr_merged=bool(pr.get("merged_at")),
                pr_closed=pr.get("state") == "closed" and not pr.get("merged_at"),
            )
            # Require at least one completed check/status and no pending/failing checks.
            sha = pr["head"]["sha"]
            result["_revision"] = sha + ":" + str(pr.get("merged_at"))
            if "ci_success" in required:
                checks = await self.api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100")
                status = await self.api(f"repos/{repo}/commits/{sha}/status?per_page=100")
                runs = checks.get("check_runs", [])
                statuses = status.get("statuses", [])
                # Larger result sets are unknown rather than partially evaluated as successful.
                complete = (
                    checks.get("total_count", len(runs)) <= 100
                    and status.get("total_count", len(statuses)) <= 100
                )
                result["ci_success"] = (
                    bool(runs or statuses)
                    and complete
                    and all(
                        r.get("status") == "completed" and r.get("conclusion") == "success"
                        for r in runs
                    )
                    and (not statuses or status.get("state") == "success")
                )
        if (number := mapping.get("issue")) and "issue_closed" in required:
            issue = await self.api(f"repos/{repo}/issues/{number}")
            result["issue_closed"] = issue.get("state") == "closed" and "pull_request" not in issue
        return result
