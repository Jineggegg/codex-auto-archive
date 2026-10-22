# Compatibility and validation

## Official interface boundaries

Verified against installed Codex CLI **0.160.0** on Linux/WSL on 2026-10-22 and current [App Server documentation](https://learn.chatgpt.com/docs/app-server), [hooks documentation](https://learn.chatgpt.com/docs/hooks), [plugin packaging](https://developers.openai.com/plugins/build/plugins).

| Capability | Status |
|---|---|
| Official plugin marketplace install | Supported; tested locally |
| Official MCP SDK stdio tools | Supported; real handshake, discovery and call tested |
| Native Archive / Unarchive | Supported through official RPC, with membership verification |
| Rule engine and persisted state | Implemented, automated tests |
| Independent trigger configuration, exact workflow association | Implemented; gh uses existing auth |
| Linux/WSL scheduler | systemd user timer; WSL must be running |
| Windows scheduler | Task Scheduler XML and installer implemented; native Windows execution needs Windows validation |
| Third-party custom settings UI | Not provided; natural language is the UI |
| Cloud/remote/unknown source threads | Unsupported; skipped |
| Pin protection on 0.160.0 | Protocol does not expose isPinned; unknown pins skipped |
| Cross-process Desktop runtime | Not globally observable from detached App Server; automatic execution skipped |
| Shared official controlling App Server | Operator-configured Unix proxy on Linux/WSL; not a substitute for Desktop global runtime visibility |
| Goal completion | Official goal/get required; absent/failing safety API skips |
| Public universal plugin directory | Hook plugins currently need manual/local distribution; GitHub marketplace is provided |
| Desktop sidebar refresh and cross-window consistency | Not verified by a real Desktop client; native stored Archive verification is narrower |

The default safe configuration on the tested installation deliberately produces **no real automatic archives**. Upgrading Codex may expose pin fields but does not by itself resolve cross-process runtime safety. Do not disable pin protection or assert runtime authority just to make tests pass on personal conversations.

Installation cannot pre-trust hooks. Official Codex requires review of the exact hook definition. The plugin never writes internal trust stores or uses bypass-hook-trust flags. Tests of hook ingestion are independent of a claim that your Desktop executed trusted hooks.

## Validation

The automated suite covers 1/3/7/14/30/60/90/custom days; metadata vs effective activity; time-only/PR-only/disabled/combined rules; all-of workflows; completion delay and cancellation; pin/project/thread/tag protection; active/approval/error/Goal safety; parent/descendant safety; network failure/reconnect; hook dedup; persisted restart; duplicate scans; confirmed batch archive/restore; token expiry and changes; current-thread delay/cancellation; unsupported sources; Windows/WSL path normalization and isolated data profiles; strict MCP schemas and real SDK stdio calls.

The opt-in native integration test uses a new temporary CODEX_HOME and a plugin-created thread whose runtime is owned by the test process. It disables pin protection **only for that disposable fixture**, because this CLI version lacks the field. It uses a local mock Responses endpoint, with no real model or external inference request. It verifies list → read → archive → archived membership → unarchive → active membership and cooldown.

See [VALIDATION.md](VALIDATION.md) for the exact final run results and installation evidence. Windows execution and real Desktop synchronization must not be inferred from Linux unit tests.

## Open-source review

GitHub searches for Codex archive MCP/auto archive found no directly reusable official-API automation project. Reviewed [andreidita22/codex-archiver](https://github.com/andreidita22/codex-archiver) (browser export/DOM capture) and [shaypal5/codex-archiver](https://github.com/shaypal5/codex-archiver) (local archive browsing and file-oriented restoration). Those approaches do not meet this project's native-API boundary and were not copied. Reused official Python MCP SDK, Pydantic, platformdirs and portalocker, with versions pinned in uv.lock.
