#!/usr/bin/env python3
"""Entrypoint for cockpit on Koyeb.

Resolves the listen port, restores a Supabase config snapshot if configured,
starts a background sync watcher, then execs label-run with --no-tls.
"""

import os
import sys
import re

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


def resolve_port() -> str:
    for key, value in os.environ.items():
        m = PORT_RE.match(key)
        if m and value.upper() in ("HTTP", "HTTPS", "TCP", ""):
            return m.group(1)
    return os.environ.get("PORT", "9090")


def main() -> None:
    port = resolve_port()

    # Restore snapshot before anything else (all-or-nothing).
    try:
        restore()
    except Exception as exc:
        print(f"[entrypoint] restore skipped: {exc}", file=sys.stderr)

    # Start background watcher before exec replaces this process.
    try:
        watch()
    except Exception as exc:
        print(f"[entrypoint] watcher not started: {exc}", file=sys.stderr)

    label_run = "/container/label-run"
    os.execv(label_run, [label_run, "--no-tls", "--port", port])


if __name__ == "__main__":
    main()
