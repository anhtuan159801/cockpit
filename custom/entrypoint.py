#!/usr/bin/env python3
"""Entrypoint for cockpit on Koyeb.

Resolves the listen port, restores a Supabase config snapshot if configured,
starts a background sync watcher, then execs cockpit-ws directly (--no-tls).
Skips containers/ws/label-run: that script assumes privileged/host mounts and
ssh-agent, and fails silently on Koyeb.
"""

import os
import sys
import re
import subprocess

sys.path.insert(0, "/custom/pylibs")
sys.path.insert(0, "/custom/bridge")

try:
    from supabase_sync import restore, watch  # noqa: E402
except Exception as exc:
    print(f"[entrypoint] supabase_sync unavailable: {exc}", file=sys.stderr)

    def restore() -> None:
        return None

    def watch() -> None:
        return None

PORT_RE = re.compile(r"^KOYEB_PORT_(\d+)_PROTOCOL$")

# Minimal cockpit.conf for Koyeb (proxy TLS). Overrides any restored snapshot
# so RequireHost / bastion SSH auth cannot break the health check.
SAFE_CONF = """\
[WebService]
ProtocolHeader = X-Forwarded-Proto
LoginTitle = Cockpit
"""


def resolve_port() -> str:
    for key, value in os.environ.items():
        m = PORT_RE.match(key)
        if m and value.upper() in ("HTTP", "HTTPS", "TCP", ""):
            return m.group(1)
    return os.environ.get("PORT", "9090")


def ensure_runtime() -> None:
    os.makedirs("/run/cockpit/tls", exist_ok=True)
    os.makedirs("/etc/cockpit", exist_ok=True)
    # Always write a known-good conf (restored snapshot may be bastion-only).
    with open("/etc/cockpit/cockpit.conf", "w") as f:
        f.write(SAFE_CONF)
    # Branding: stub os-release if missing (label-run would do this).
    if not os.path.exists("/etc/os-release") and not os.path.exists("/usr/lib/os-release"):
        with open("/etc/os-release", "w") as f:
            f.write("NAME=cockpit\nID=cockpit\n")


def ensure_login_user() -> None:
    """Create/update local PAM user from COCKPIT_USER + COCKPIT_PASSWORD."""
    user = os.environ.get("COCKPIT_USER", "").strip()
    password = os.environ.get("COCKPIT_PASSWORD", "")
    if not user or not password:
        return
    try:
        exists = subprocess.run(
            ["id", "-u", user],
            capture_output=True,
            check=False,
        ).returncode == 0
        if not exists:
            subprocess.run(
                ["useradd", "-m", "-s", "/bin/sh", user],
                capture_output=True,
                check=True,
            )
            print(f"[entrypoint] created user {user}", file=sys.stderr, flush=True)
        # chpasswd: set password non-interactively (PAM auth for cockpit-ws).
        proc = subprocess.run(
            ["chpasswd"],
            input=f"{user}:{password}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            print(
                f"[entrypoint] chpasswd failed: {proc.stderr.strip()}",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"[entrypoint] login user ready: {user}", file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[entrypoint] ensure_login_user error: {exc}", file=sys.stderr, flush=True)


def main() -> None:
    port = resolve_port()
    print(
        f"[entrypoint] port={port} PORT={os.environ.get('PORT', '')}",
        file=sys.stderr,
        flush=True,
    )

    try:
        restore()
    except Exception as exc:
        print(f"[entrypoint] restore skipped: {exc}", file=sys.stderr, flush=True)

    ensure_runtime()
    print("[entrypoint] wrote safe /etc/cockpit/cockpit.conf", file=sys.stderr, flush=True)

    ensure_login_user()

    try:
        watch()
    except Exception as exc:
        print(f"[entrypoint] watcher not started: {exc}", file=sys.stderr, flush=True)

    ws = "/usr/libexec/cockpit-ws"
    if not os.path.isfile(ws):
        print(f"[entrypoint] FATAL missing {ws}", file=sys.stderr, flush=True)
        sys.exit(1)

    argv = [ws, "--no-tls", "--port", port]
    print(f"[entrypoint] exec {' '.join(argv)}", file=sys.stderr, flush=True)
    os.execv(ws, argv)


if __name__ == "__main__":
    main()
