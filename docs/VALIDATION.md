# v0.1.0 validation record

2026-10-22, Linux/WSL, Python 3.13.15, Codex CLI 0.160.0, official MCP SDK 1.30.0.

- Automated suite with both opt-in integrations enabled: **85 passed**. Includes real SDK stdio initialize/list/call, strict rejection of malformed tool parameters, and rule/safety/storage/protocol tests.
- Native integration: new isolated CODEX_HOME, local synthetic Responses fixture (no real model), official thread/start and turn/start to persist the disposable conversation, then production thread/list/read/turns/list/goal/get/archive/unarchive with archived/active membership verification. The fixture alone disables pin protection and is marked process-owned. No existing user thread is targeted.
- Official plugin integration: marketplace add → plugin add → App Server mcpServerStatus/list discovers **22 tools** → mcpServer/tool/call reads settings and changes idle days to 7 in isolated plugin state → plugin/marketplace removed. Custom data-directory propagation is asserted.
- Daily WSL profile: plugin installed using official CLI; App Server discovered 22 tools and called get_archive_settings successfully. Default inactivity remained 30 days and Dry Run remained true.
- Existing-store Dry Run: **67 threads read, 0 archived**. With a separate temporary 7-day policy, **22 matched the idle trigger, 0 passed all safety gates, 0 archived**. Unknown pin state and detached runtime were reported explicitly. Temporary policy never replaced the installed default.
- systemd user timer enabled; service Result=success and ExecMainStatus=0. Calendar wakeup is one minute, actual scan interval is 60 minutes by default.
- Ruff lint/format and source/wheel build checked before publication.

Native Windows Task Scheduler execution and a real Desktop sidebar refresh were **not verified locally**. A Windows PowerShell probe from WSL failed with the host's `UtilAcceptVsock ... accept4 failed 110`; no Windows configuration was changed. The repository includes Ubuntu/Windows Python 3.11/3.13 CI. See GitHub Actions for the current hosted run result; configured CI is not evidence that it passed.

The first-install configuration is unchanged: enabled=true, dry_run=true, idle=30d, all completion/workflow triggers off, grace=30min, pin protection on, restore cooldown=7d, check interval=60min, max=20 threads including descendants.
