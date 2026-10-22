from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

NAME = "codex-auto-archive"


def command(store):
    return [
        sys.executable,
        "-m",
        "codex_auto_archive",
        "--data-dir",
        str(store.root),
        "check",
        "--scheduled",
    ]


def windows_xml(store):
    cmd = command(store)
    # Task Scheduler uses the Windows command-line quoting rules, never a shell.
    args = subprocess.list2cmdline(cmd[1:])
    env_home = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    # CODEX_HOME is explicitly persisted in our own connection/installation metadata.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<RegistrationInfo><Description>Native Codex Archive checks; no LLM, no deletion.</Description></RegistrationInfo>
<Triggers><TimeTrigger><Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
<Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT15M</ExecutionTimeLimit><Enabled>true</Enabled></Settings>
<Actions Context="Author"><Exec><Command>{escape(cmd[0])}</Command><Arguments>{escape(args)}</Arguments><WorkingDirectory>{escape(env_home)}</WorkingDirectory></Exec></Actions>
</Task>"""


def install(store):
    # Include store identity to avoid collisions between multiple CODEX_HOME profiles.
    suffix = hashlib.sha256(str(store.root.resolve()).encode()).hexdigest()[:12]
    if os.name == "nt":
        name = NAME + "-" + suffix
        with tempfile.TemporaryDirectory() as temp:
            xml = Path(temp) / "task.xml"
            xml.write_text(windows_xml(store), encoding="utf-16")
            subprocess.run(
                ["schtasks", "/Create", "/TN", name, "/XML", str(xml), "/F"],
                check=True,
                capture_output=True,
            )
        result = {
            "installed": True,
            "kind": "windows-task-scheduler",
            "name": name,
            "cadence": "1-minute wakeup; configured scan interval is respected",
        }
    elif sys.platform.startswith("linux"):
        name = NAME + "-" + suffix
        root = Path.home() / ".config/systemd/user"
        root.mkdir(parents=True, exist_ok=True)

        def quoted(arg):
            # systemd ExecStart has its own quoting/percent expansion rules.
            return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

        home = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        service = "[Unit]\nDescription=Native Codex Archive check\n[Service]\nType=oneshot\n"
        service += "Environment=" + quoted("CODEX_HOME=" + home) + "\n"
        service += "Environment=" + quoted("PATH=" + os.environ.get("PATH", "/usr/bin:/bin")) + "\n"
        service += (
            "ExecStart=" + " ".join(quoted(a) for a in command(store)) + "\nTimeoutStartSec=15min\n"
        )
        (root / (name + ".service")).write_text(service, encoding="utf-8")
        (root / (name + ".timer")).write_text(
            "[Unit]\nDescription=Wake Codex Archive scheduler\n[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nRandomizedDelaySec=10\n[Install]\nWantedBy=timers.target\n",
            encoding="utf-8",
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", name + ".timer"],
            check=True,
            capture_output=True,
        )
        result = {
            "installed": True,
            "kind": "systemd-user",
            "name": name,
            "cadence": "1-minute wakeup; configured scan interval is respected",
        }
    else:
        raise RuntimeError(
            "Automatic installer supports Windows and Linux/WSL with systemd. Use the check command with your OS scheduler elsewhere."
        )
    store.put("codex_home", os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    store.put("scheduler", result)
    return result


def uninstall(store):
    info = store.get("scheduler", {})
    if info.get("installed"):
        name = info["name"]
        if info["kind"] == "windows-task-scheduler":
            subprocess.run(
                ["schtasks", "/Delete", "/TN", name, "/F"], check=True, capture_output=True
            )
        else:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", name + ".timer"],
                check=True,
                capture_output=True,
            )
            root = Path.home() / ".config/systemd/user"
            for ext in (".service", ".timer"):
                (root / (name + ext)).unlink(missing_ok=True)
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"], check=True, capture_output=True
            )
    store.put("scheduler", {"installed": False})
    return {"uninstalled": True}
