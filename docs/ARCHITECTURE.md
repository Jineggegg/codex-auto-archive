# Architecture and safety

`MCP (official Python SDK, stdio) → Service → Engine → official Codex App Server JSON-RPC`

`Command hooks → lightweight plugin-owned SQLite state`

`OS scheduler → one-shot Engine scan → native Archive / Unarchive`

Config is validated JSON with atomic replace, previous-file backup, schema migration and fail-closed corruption recovery. State, dedup IDs, workflow associations, pending tasks and audit are in **this plugin's own SQLite database**. No code opens a Codex database or rollout file. No deletion RPC is allowed; the adapter uses an explicit allowlist. Config imports reset Dry Run and remove executable connection authority.

The adapter initializes formally, sends initialized, handles concurrent response IDs, notifications, server-request rejection, disconnections, timeouts, full cursor pagination and all documented sourceKinds. Production code never resumes a thread or starts inference. The opt-in test materializes its disposable thread using a local synthetic Responses fixture. A read failure blocks the affected target; a discovery pagination failure aborts the scan before mutation. Mutation RPCs are never automatically retried within a scan.

Rules resolve per thread and exact normalized project path. Windows drive/UNC paths are case-normalized but never implicitly mapped to a WSL mount. Plugin state is scoped by an SHA-256 prefix of the selected CODEX_HOME; --data-dir supports explicit isolated stores. Archived logs are not exported or sent to GitHub.

Hooks retain only event identity, exact session ID, activity time, busy flag and agent IDs. Prompt, tool arguments and transcript contents are discarded. Events use host IDs when present, otherwise a two-second identity bucket. Duplicate events are ignored; dedup records expire after seven days. Subagent hooks report parent session IDs, so agent IDs are tracked separately. Unknown subagent identity stays protected. Stop/SessionEnd never imply completion. Archiving-triggered SessionEnd cannot recursively schedule archive.

A global file lock serializes scans and confirmed manual operations across processes. Config writes have a separate lock; SQLite transactions serialize event updates. A final safety snapshot checks current policy, pin, status, goal, activity, parent safety and every discoverable descendant again. Confirmation fingerprints bind policy, activity and descendant membership. An automatic parent archive is blocked if a descendant has more recent effective activity.

The official API has no documented atomic conditional archive transaction. Hooks cannot eliminate every race between a user prompt and an archive RPC. **Detached execution therefore defaults to unsupported for external-thread mutation.** A shared controlling App Server may be explicitly configured by an operator; their assertion must cover all relevant clients. Final rechecks narrow, but do not eliminate, the race. Never mark an unrelated independent process authoritative.

Completion waits are persisted and evaluated without a model. New activity cancels pending automatic work and suppresses the same stale completion signal. New prompts cancel manual current-thread deferrals; current-thread mutation must still pass runtime checks after its delay. Native unarchive is verified against active membership and starts a seven-day cooldown. A scan observes externally restored plugin-archived threads and applies the same cooldown.

The OS timer wakes once a minute, but reads the latest configured scan interval and normally exits before starting App Server. A due manual deferral can wake earlier. Windows uses StartWhenAvailable and IgnoreNew; systemd uses a persistent calendar timer. Restart catches up due work. Failures are audited with a five-minute retry backoff. No cloud daemon, listener, browser automation or model loop is involved. User systemd timers need a running user manager; WSL must be running, and catch-up occurs when it starts again.
