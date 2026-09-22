#!/usr/bin/env python3
"""Entrypoint for cockpit on Koyeb.

Resolves the listen port, restores a Supabase config snapshot if configured,
creates the login user from COCKPIT_USER/COCKPIT_PASSWORD, starts a background
sync watcher, then execs cockpit-ws (--no-tls).

Local password login uses cockpit-session (PAM) via [Basic] Command — no SSH
loopback/sshd required. Skips containers/ws/label-run (privileged/host mounts).
"""

import os
import sys
import re
import shutil
import subprocess

sys.path.insert(0, "/custom/pylibs")

# Optional bridge overlay (BUILD_BRIDGE=1 bakes this path at image build).
if os.path.isfile("/custom/bridge.path"):
    try:
        with open("/custom/bridge.path") as f:
            bridge_path = f.read().strip()
        if bridge_path:
            sys.path.insert(0, bridge_path)
    except OSError:
        pass

try:
    from supabase_sync import restore, watch  # noqa: E402
except Exception as exc:
    print(f"[entrypoint] supabase_sync unavailable: {exc}", file=sys.stderr)

    def restore() -> None:
        return None

    def watch() -> None:
        return None

PORT_RE = re.compile(r"^KOYEB_PORT_(\d+)_PROTOCOL$")

# Minimal cockpit.conf for Koyeb (proxy TLS). [Basic] Command points at
# cockpit-session so local password auth works without systemd socket activation.
SAFE_CONF = """\
[WebService]
ProtocolHeader = X-Forwarded-Proto
LoginTitle = Cockpit

[Basic]
Command = /usr/libexec/cockpit-session
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
    os.makedirs("/var/log", exist_ok=True)
    for name, mode in (("btmp", 0o664), ("wtmp", 0o664), ("lastlog", 0o664)):
        path = f"/var/log/{name}"
        if not os.path.exists(path):
            open(path, "a").close()
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    # Always write a known-good conf (restored snapshot may be bastion-only).
    with open("/etc/cockpit/cockpit.conf", "w") as f:
        f.write(SAFE_CONF)
    # Branding: stub os-release if missing (label-run would do this).
    if not os.path.exists("/etc/os-release") and not os.path.exists("/usr/lib/os-release"):
        with open("/etc/os-release", "w") as f:
            f.write("NAME=cockpit\nID=cockpit\n")


def _run(cmd, input_text=None, check=False):
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def ensure_login_user() -> bool:
    """Create/update local user from COCKPIT_USER + COCKPIT_PASSWORD. Returns True if ready."""
    user = os.environ.get("COCKPIT_USER", "").strip()
    password = os.environ.get("COCKPIT_PASSWORD", "")
    if not user or not password:
        print("[entrypoint] COCKPIT_USER/PASSWORD not set — skip user create", file=sys.stderr, flush=True)
        return False

    if shutil.which("useradd") is None:
        print("[entrypoint] FATAL useradd not found (shadow-utils missing)", file=sys.stderr, flush=True)
        return False

    try:
        exists = _run(["id", "-u", user]).returncode == 0
        if not exists:
            r = _run(["useradd", "-m", "-u", "1000", "-s", "/bin/sh", user])
            if r.returncode != 0 and "already exists" not in (r.stderr or ""):
                # UID 1000 may be taken — retry without fixed UID.
                r = _run(["useradd", "-m", "-s", "/bin/sh", user])
            if r.returncode != 0 and "already exists" not in (r.stderr or ""):
                print(f"[entrypoint] useradd failed: {r.stderr.strip()}", file=sys.stderr, flush=True)
                return False
            print(f"[entrypoint] created user {user}", file=sys.stderr, flush=True)

        r = _run(["chpasswd"], input_text=f"{user}:{password}\n")
        if r.returncode != 0:
            print(f"[entrypoint] chpasswd failed: {r.stderr.strip()}", file=sys.stderr, flush=True)
            return False

        # Ensure account is not locked / expired.
        _run(["passwd", "-u", user])
        _run(["chage", "-m", "0", "-M", "99999", "-I", "-1", user])
        print(f"[entrypoint] login user ready: {user}", file=sys.stderr, flush=True)
        return True
    except Exception as exc:
        print(f"[entrypoint] ensure_login_user error: {exc}", file=sys.stderr, flush=True)
        return False


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

    user_ok = ensure_login_user()
    if not user_ok:
        print(
            "[entrypoint] WARNING login user not ready — auth may fail",
            file=sys.stderr,
            flush=True,
        )

    try:
        watch()
    except Exception as exc:
        print(f"[entrypoint] watcher not started: {exc}", file=sys.stderr, flush=True)

    ws = "/usr/libexec/cockpit-ws"
    if not os.path.isfile(ws):
        print(f"[entrypoint] FATAL missing {ws}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Local password auth via cockpit-session (PAM) — no --local-ssh/sshd.
    argv = [ws, "--no-tls", "--port", port]
    print(f"[entrypoint] exec {' '.join(argv)}", file=sys.stderr, flush=True)
    os.execv(ws, argv)


if __name__ == "__main__":
    main()
