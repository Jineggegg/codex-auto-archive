# MCP tool reference

All tools reject unknown arguments and invalid/coerced types. Only exact thread IDs returned by Codex are accepted. Tool errors have `isError=true`, `affected_count=0` and an explanation; a timeout may leave a mutation outcome unknown, so inspect membership/history before retrying.

| Tool | Arguments / purpose |
|---|---|
| get_archive_settings | Optional project/thread_id; raw config and resolved policy |
| update_archive_settings | settings patch; activate=true required with dry_run=false |
| get_archive_status | Health, scheduler registration, last/next checks and limitations |
| list_threads | archived, project, limit; scans all cursor pages before truncating response |
| preview_archive | thread_ids/project/inactive_days/horizon_days/automatic/current |
| archive_threads | Fresh confirmation_token, confirmed=true after user confirmation |
| restore_threads | Exact thread_ids; preview first, then token + confirmed=true |
| exclude_thread / include_thread | Exact thread_id, or current=true |
| exclude_project / include_project | Absolute project path |
| set_project_policy | Project and policy patch |
| set_thread_policy | Exact/current thread and policy patch |
| get_archive_history | limit, UTC Unix since, action filter |
| run_archive_check | dry_run defaults true; false still respects persisted Dry Run |
| pause_auto_archive | Global or thread; days optional (omitted means indefinite) |
| resume_auto_archive | Remove pause globally or for exact/current thread |
| set_archive_mode | conservative / standard / aggressive / custom |
| reset_archive_settings | confirmed=true; resets rules and whitelist, restores Dry Run |
| link_workflow | Exact/current thread, repo, pr/issue, optional branch, confirmed=true |
| record_completion | Exact/current thread, evidence=user_explicit_completion, confirmed=true |
| set_thread_tags | Exact/current thread, list of reliable plugin-owned tags |

Independent policy keys: `archive_inactive_threads`, `inactive_days`, `archive_completed_threads`, `archive_on_pr_merged`, `archive_on_pr_closed`, `archive_on_ci_success`, `archive_on_issue_closed`, `archive_on_goal_completed`, `archive_on_user_explicit_completion`, `completion_grace_minutes`, `exclude_pinned`, `excluded_tags`, `workflow_all_of`.

Global-only settings include enabled, dry_run, check_interval_minutes, restore_cooldown_days, max_archives_per_check and locale. The connection command is deliberately not writable by MCP; an operator configures the local official server using the CLI.

An archive preview includes eligible candidates, skipped reasons, triggers, due/activity time, descendant IDs and a configuration/activity fingerprint. Confirmation cannot add targets. A final fresh read can still skip a changed target. Successful responses list verified successful IDs, failed IDs, actual affected count, and recoverable IDs. Native parent archive can partially archive descendants: each verified descendant is audited separately. Restore each desired ID explicitly.
