---
name: auto-archive
description: Manage native Codex Archive in natural language: settings, idle days, completion and PR/CI rules, whitelist, preview, delayed current-thread archive, restore, and history. Use for 开启/关闭自动归档、闲置7天、归档当前会话、恢复昨天归档、白名单、保守/标准/积极模式, or equivalent requests in any language.
---

Use the bundled auto-archive MCP tools. Reply in the user's language (English, 简体中文, 日本語, Español, or the requested language). Read existing settings before changing only the fields requested. Return the actual effective settings, not a promise.

- Idle and completion/workflow triggers are independent. “Idle 7 days, PR merged immediately” sets inactive_days=7, archive_inactive_threads=true, archive_on_pr_merged=true, completion_grace_minutes=0; preserve other unspecified switches.
- “Enable auto archive” sets enabled=true and dry_run=false with activate=true because that sentence explicitly authorizes activation. Installation, asking about settings, a preset, or changing a number alone does not authorize leaving Dry Run. “Disable auto archive” sets enabled=false. Manual tools remain available.
- Use set_project_policy for the exact absolute project path; use set_thread_policy for exact thread overrides. “All new sessions default 30 days” changes global inactive_days; existing explicit overrides remain.
- “Task is finished” may call record_completion only when the user explicitly means the entire thread goal. Finishing a response, Stop, SessionEnd, successful tests or CI do not imply completion. Never manufacture evidence.
- Link only exact user-confirmed repo/PR/Issue associations with link_workflow. Never infer that any PR in the same repository belongs to this thread. workflow_all_of=[pr_merged,ci_success] requires both switches enabled and both signals true. An enabled ungrouped event remains an independent OR trigger.
- For current-thread operations use current=true. If reliable CODEX_THREAD_ID is unavailable, list threads and ask the user to select an exact ID. Never select by title, recency or cwd alone.
- For manual archive call preview_archive, show candidate count, IDs/titles, descendants and skipped reasons, then obtain explicit confirmation before archive_threads. Never set confirmed=true without that confirmation. Tokens expire after 10 minutes and are single-use. Even a single current-thread archive requires the preview. A deferred operation is scheduled, not executed.
- Restore: query get_archive_history (auto_archive and date range) or list_threads(archived=true), call restore_threads(confirmed=false) for exact IDs, show preview, obtain confirmation, then execute with the token. Parent archive may archive descendants; restore those explicit IDs too.
- “Next 7 days” uses preview_archive(automatic=true,horizon_days=7); it is a read-only forecast and must never be executed as a manual archive token.
- Presets: conservative=90 days/24h grace, standard=30 days/30min grace, aggressive=7 days/5min grace; completion/workflow disabled, pin protection enabled. They never activate real automation. Custom preserves settings.
- Whitelist outranks everything. Unknown pin state, unknown cross-process runtime, active goals, active agents, approvals or unsafe descendants mean skip. Explain the concrete unsupported state. Never disable a protection simply to make an archive succeed.
- Do not claim Desktop sidebar synchronization was verified unless a real Desktop client test established it. An official Archive API verification alone proves stored Archive state.
- Settings locale can be auto/en/zh-CN/ja/es. Tool data uses stable machine keys; produce concise localized prose in chat. No local/background LLM is involved.
