# Codex Auto Archive

[English](README.md) · [简体中文](docs/README.zh-CN.md) · [日本語](docs/README.ja.md) · [Español](docs/README.es.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![MCP stdio](https://img.shields.io/badge/MCP-local%20stdio-6366f1.svg)](.mcp.json)

Manage **Codex's own Archive** in natural language. Independent idle, completion and GitHub workflow rules; exact-thread protection; previews and reversible operations; a local scheduler that never calls an LLM.

**v0.1.0 is safety-gated.** Native archive/restore and MCP work, but a detached App Server cannot prove whether Desktop or another process is busy. Automatic execution is blocked for those threads. On the tested Codex CLI 0.160.0, pin state is also absent from the protocol, so default pin protection skips these threads. Installing this plugin does **not** mean unattended Desktop archiving is verified or supported on that version. See [compatibility](docs/COMPATIBILITY.md).

## Install once

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), a local Codex CLI with App Server and plugin support. `gh` is optional and reuses your existing login.

```bash
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
bash scripts/install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/Jineggegg/codex-auto-archive.git
cd codex-auto-archive
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

The execution policy switch applies only to that installer invocation. Dependencies are pinned in `uv.lock`. The installer uses official `codex plugin marketplace add` and `codex plugin add`, then creates a systemd user timer or Windows scheduled task. It opens no ports and never modifies Codex session files.

Open a **new Codex conversation**. In Codex, review and trust the plugin's command hooks with `/hooks` (or the native hook review UI). Official Codex requires trust for the exact hook definitions; the installer does not bypass it. Time-rule evaluation and Dry Run work without hooks. Local plugin commands require uv on the Codex client's PATH.

For a different profile, set `CODEX_HOME` before installation (PowerShell installer also accepts `-CodexHome`). Windows and WSL profiles are separate; installing in WSL does not install into Windows Desktop. Keep the checkout/runtime while the scheduler is installed.

## Say it in Codex

- “Use 7 idle days, and archive after the linked PR merges.”
- “Disable completion archiving but keep time archiving.”
- “Never automatically archive this project.”
- “Show the next 7 days of archive candidates.”
- “Show the latest 10 automatically archived conversations.”
- “Restore yesterday's automatically archived conversations.”
- “Set language to Simplified Chinese.”

The bundled skill translates requests into strictly typed MCP tools using the **existing conversation model**. The MCP server, hooks and scheduler make no additional model calls. `locale` supports `auto`, `en`, `zh-CN`, `ja`, `es`; chat responses follow the user's language. Machine-readable tool keys stay stable.

“Enable auto archive” explicitly authorizes leaving Dry Run; changing days, selecting a preset or installing does not. Runtime/pin/goal/agent protections still apply after enabling. Batch archive and restore always require a displayed preview followed by explicit confirmation. A confirmation token is single-use, lasts 10 minutes and binds the selected IDs and configuration. A forecast token cannot archive anything.

Current-thread operations use `CODEX_THREAD_ID` only when the host provides it and App Server can read the exact thread. Otherwise, Codex asks you to select an ID from the thread list. Current-thread archive is deferred at least 60 seconds and until idle; new user input cancels it. Never treat “scheduled” as “archived.”

## Defaults and rules

| Setting | First-install value |
|---|---|
| Master automation | Enabled in **Dry Run** |
| Idle rule | 30 days after effective activity |
| Generic task completion | Off |
| PR merged / PR closed / CI success / Issue closed / Goal complete / explicit completion | Each off independently |
| Completion grace | 30 minutes |
| Pin protection | On; unknown pin state skips |
| Restored-thread cooldown | 7 days |
| Full scan interval | 60 minutes |
| Per-scan archive limit | 20 threads, counting descendants |
| Language | Auto |

Priority: exclusions → safety → thread overrides → project overrides → global policy → defaults. Enabled triggers are OR-combined, except `workflow_all_of` explicitly requires all its enabled events. Presets reset global trigger policy: conservative=90d/24h grace, standard=30d/30min, aggressive=7d/5min. Presets keep pin protection and disable completion/workflow triggers; overrides remain.

Effective activity comes from official turn start/completion timestamps and lightweight activity hooks, not creation time or metadata `updatedAt`. A normal reply, Stop or SessionEnd never marks a task complete. Active/paused/blocked goals, approval waits, active agents, unknown descendants and unsupported sources are protected. Recent child activity prevents an older parent from cascading an automatic archive.

PR/Issue links require exact user-confirmed owner/repository and number. GitHub is used only to confirm workflow conditions through authenticated `gh api`. CI must have real successful checks/statuses on the exact PR head SHA; an empty suite isn't success. Network/auth failures cannot produce a positive workflow signal. Time triggers remain independent.

## Tools and maintenance

[Tool reference](docs/TOOLS.md) · [Architecture and safety](docs/ARCHITECTURE.md) · [Compatibility and validation](docs/COMPATIBILITY.md)

```bash
uv run codex-auto-archive doctor
uv run codex-auto-archive check --dry-run
uv run codex-auto-archive disable
uv run codex-auto-archive enable             # preserves Dry Run
uv run codex-auto-archive export policy.json
uv run codex-auto-archive import policy.json # always returns to Dry Run
uv run codex-auto-archive scheduler-remove
uv run codex-auto-archive scheduler-install
uv run codex-auto-archive uninstall         # keeps settings/audit
uv run codex-auto-archive uninstall --purge # removes only plugin state
```

Use the same `UV_PROJECT_ENVIRONMENT` as the installer when invoking from the checkout if you want to reuse its environment; the plugin's cached environment is separate. You can also invoke the installed runtime's `python -m codex_auto_archive` directly.

Update: `git pull --ff-only`, rerun the installer. Published versions bump the plugin version so the official plugin cache refreshes. Reinstalling keeps settings/audit and does not silently activate archiving. Uninstall removes this plugin and its marketplace/timer; it never deletes or unarchives Codex conversations. Remove the checkout and dedicated runtime directory afterward if no longer wanted. Config export excludes executable connection configuration; importing resets the connection and requires new execution consent.

Advanced Linux/WSL hosts with a **single official controlling App Server** can configure its existing control socket using `connect --proxy-socket /absolute/socket --confirm-shared-runtime`. This is an operator assertion that every relevant client uses that server, not automatic discovery. Do not point at an unrelated daemon to bypass a Desktop protection. No daemon is started or Desktop restarted by this plugin. Real automation still requires known pin state and explicit activation.

## Development

```bash
uv sync --extra dev --frozen
uv run pytest -q
ARCHIVE_REAL_INTEGRATION=1 uv run pytest -q tests/test_integration.py
uv run ruff check src tests
```

The opt-in integration test creates a disposable, isolated CODEX_HOME, materializes a test thread using a local synthetic Responses fixture, archives and restores that thread through official RPC, and checks native membership. It never targets existing user threads or calls a real model. [Validation details](docs/COMPATIBILITY.md#validation).

Official interfaces: [App Server](https://learn.chatgpt.com/docs/app-server), [hooks](https://learn.chatgpt.com/docs/hooks), [plugin packaging](https://developers.openai.com/plugins/build/plugins). This is an independent community project, not an OpenAI product.
