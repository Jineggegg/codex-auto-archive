from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import portalocker

from .models import Config, Connection
from .storage import Store, atomic_write


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


async def check(store, args):
    from .appserver import AppServer
    from .engine import Engine

    if args.scheduled:
        # Rehydrate profile even when Scheduler starts with a minimal environment.
        if home := store.get("codex_home"):
            os.environ["CODEX_HOME"] = home
        cfg = store.config()
        last = store.get("last_check", {})
        next_at = last.get("at", 0) + cfg.check_interval_minutes * 60
        manual_due = store.get("next_manual_due", 0)
        if manual_due:
            next_at = min(next_at, manual_due)
        if time.time() < max(next_at, store.get("retry_after", 0)):
            return {"skipped": True, "reason": "not_due", "next_check_at": next_at}
    try:
        async with AppServer(store.config().connection) as client:
            result = await Engine(store, client).check(args.dry_run)
        store.put("last_error", None)
        store.put("retry_after", 0)
        if args.scheduled:
            # Scheduler logs aggregate counts, never all conversation titles.
            return {k: v for k, v in result.items() if k != "threads"}
        return result
    except portalocker.exceptions.LockException:
        return {"skipped": True, "reason": "another_scan_is_running", "affected_count": 0}
    except Exception as e:
        result = {
            "executed": False,
            "affected_count": 0,
            "error": str(e),
            "retry_after": time.time() + 300,
        }
        store.put("last_error", result)
        store.put("retry_after", result["retry_after"])
        store.audit("scan_error", None, result)
        raise


async def doctor(store):
    from .appserver import AppServer
    from .service import Service

    status = await Service(store).call("get_archive_status", {})
    status["codex"] = shutil.which("codex")
    status["gh"] = shutil.which("gh")
    try:
        async with AppServer(store.config().connection) as client:
            status["app_server"] = {
                "connected": True,
                "identity": client.identity,
                "loaded_threads": len(await client.pages("thread/loaded/list", {})),
            }
    except Exception as e:
        status["app_server"] = {"connected": False, "error": str(e)}
    return status


def parser():
    p = argparse.ArgumentParser(
        description="Native Codex Archive automation. No deletion; defaults to Dry Run."
    )
    p.add_argument(
        "--data-dir", type=Path, help="Separate plugin data directory (not Codex storage)"
    )
    p.add_argument("--codex-home", type=Path, help="Select exact Codex data profile")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("hook")
    c = sub.add_parser("check")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--scheduled", action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("status")
    install = sub.add_parser("install")
    install.add_argument("--plugin-root", type=Path, default=Path.cwd())
    install.add_argument("--no-scheduler", action="store_true")
    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument(
        "--purge",
        action="store_true",
        help="Also remove only this plugin's settings and audit; never touches Codex sessions",
    )
    sub.add_parser("scheduler-install")
    sub.add_parser("scheduler-remove")
    sub.add_parser("enable")
    sub.add_parser("disable")
    exp = sub.add_parser("export")
    exp.add_argument("file", type=Path)
    imp = sub.add_parser("import")
    imp.add_argument("file", type=Path)
    conn = sub.add_parser("connect")
    conn.add_argument("--proxy-socket", type=Path, required=True)
    conn.add_argument(
        "--confirm-shared-runtime",
        action="store_true",
        help="Attest every relevant client uses this controlling server; never set for an unrelated detached process",
    )
    sub.add_parser("disconnect")
    return p


def main():
    args = parser().parse_args()
    if args.codex_home:
        os.environ["CODEX_HOME"] = str(args.codex_home.expanduser().resolve())
    store = Store(args.data_dir)
    try:
        if args.command == "serve":
            from .mcp_server import serve

            asyncio.run(serve(store))
            return
        if args.command == "hook":
            from .hooks import ingest

            payload = sys.stdin.read(1024 * 1024 + 1)
            if len(payload) > 1024 * 1024:
                raise ValueError("Hook payload too large")
            ingest(store, json.loads(payload))
            # Silence is the supported command-hook success contract.
            return
        if args.command == "check":
            output(asyncio.run(check(store, args)))
        elif args.command == "doctor":
            output(asyncio.run(doctor(store)))
        elif args.command == "status":
            from .service import Service

            output(asyncio.run(Service(store).call("get_archive_status", {})))
        elif args.command in ("scheduler-install", "scheduler-remove"):
            from . import scheduler

            output(
                (scheduler.install if args.command == "scheduler-install" else scheduler.uninstall)(
                    store
                )
            )
        elif args.command == "install":
            root = args.plugin_root.resolve()
            if not (root / ".codex-plugin/plugin.json").is_file():
                raise ValueError("Point --plugin-root at the repository checkout")
            subprocess.run(["codex", "plugin", "marketplace", "add", str(root)], check=True)
            installed = subprocess.run(
                ["codex", "plugin", "add", "codex-auto-archive@codex-auto-archive", "--json"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            installed_path = json.loads(installed.stdout)["installedPath"]
            warm_env = os.environ.copy()
            warm_env.pop("UV_PROJECT_ENVIRONMENT", None)
            subprocess.run(
                ["uv", "sync", "--frozen", "--project", installed_path], check=True, env=warm_env
            )
            if not args.no_scheduler:
                from .scheduler import install

                install(store)
            output(
                {
                    "installed": True,
                    "dry_run": store.config().dry_run,
                    "hooks": "Review and trust the bundled hooks in Codex /hooks; installer never bypasses trust.",
                    "restart": "Open a new Codex conversation to discover newly installed tools.",
                }
            )
        elif args.command == "uninstall":
            from .scheduler import uninstall

            uninstall(store)
            subprocess.run(
                ["codex", "plugin", "remove", "codex-auto-archive@codex-auto-archive"], check=True
            )
            subprocess.run(
                ["codex", "plugin", "marketplace", "remove", "codex-auto-archive"], check=True
            )
            if args.purge:
                shutil.rmtree(store.root)
            output(
                {
                    "uninstalled": True,
                    "settings_retained": not args.purge,
                    "codex_sessions_changed": False,
                }
            )
        elif args.command in ("enable", "disable"):
            cfg = store.edit(lambda c: setattr(c, "enabled", args.command == "enable"))
            output({"enabled": cfg.enabled, "dry_run": cfg.dry_run})
        elif args.command == "export":
            # Don't export executable commands or machine-specific connection authority.
            data = store.config().model_dump(exclude_none=True)
            data["connection"] = Connection().model_dump()
            atomic_write(args.file, data)
            output({"exported": str(args.file)})
        elif args.command == "import":
            imported = Config.model_validate_json(args.file.read_text(encoding="utf-8"))
            imported.dry_run = True
            imported.connection = Connection()

            def change(cfg):
                for k in Config.model_fields:
                    setattr(cfg, k, getattr(imported, k))

            store.edit(change)
            output({"imported": True, "dry_run": True, "connection_reset": True})
        elif args.command == "connect":
            if os.name == "nt":
                raise ValueError(
                    "Unix proxy sockets require Linux/WSL. Native Windows detached mode remains available for queries and Dry Run."
                )
            if not args.confirm_shared_runtime:
                raise ValueError(
                    "Confirm that this is the official controlling server for every relevant client. A separate daemon cannot observe another Desktop server."
                )
            sock = args.proxy_socket.expanduser().resolve()
            if not sock.is_socket():
                raise ValueError("Official App Server socket not found")
            conn = Connection(
                command=["codex", "app-server", "proxy", "--sock", str(sock)], authoritative=True
            )
            store.edit(lambda c: setattr(c, "connection", conn))
            output({"connected_to_shared_runtime": True, "dry_run": store.config().dry_run})
        elif args.command == "disconnect":
            store.edit(lambda c: setattr(c, "connection", Connection()))
            output({"mode": "detached", "automatic_execution": "blocked_when_runtime_unknown"})
    except Exception as e:
        if args.command == "hook":
            # Advisory hooks must not interrupt a user's task; persist a local error if possible.
            try:
                store.audit("hook_error", None, {"error_type": type(e).__name__})
            except Exception:
                pass
            return
        output({"error": str(e), "error_type": type(e).__name__, "affected_count": 0})
        raise SystemExit(1) from None
