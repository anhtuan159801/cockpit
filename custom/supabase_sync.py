#!/usr/bin/env python3
"""Supabase config snapshot sync for cockpit on Koyeb.

Ports 9router's config.js / crypto.js / store.js to Python.
Stores an encrypted JSON envelope of allowlisted config files in a Supabase
table so a fresh container can restore state after redeploy.

Env contract (all required for sync to activate):
  SUPABASE_URL                  HTTPS project URL
  SUPABASE_SECRET_KEY           service-role key (legacy: SUPABASE_SERVICE_ROLE_KEY)
  SUPABASE_SYNC_ENCRYPTION_KEY  base64 32-byte AES-256-GCM key
  SUPABASE_SYNC_INSTANCE_ID     ^[A-Za-z0-9._-]{1,128}$
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --- constants -------------------------------------------------------------

TABLE = "cockpit_config_snapshots"
FORMAT_VERSION = 1
AAD = b"cockpit:1"
RETRY_CAP = 30

# Only these paths may be written on restore.
ALLOWLIST = (
    "/etc/cockpit/cockpit.conf",
    "/etc/ssh/ssh_known_hosts",
    "/etc/cockpit/ssh",
)

# Files to snapshot (relative → absolute). Missing files are skipped.
SNAPSHOT_TARGETS = (
    "/etc/cockpit/cockpit.conf",
    "/etc/ssh/ssh_known_hosts",
)


# --- env -------------------------------------------------------------------

def _env(name: str, legacy: str = "") -> str:
    val = os.environ.get(name, "")
    if not val and legacy:
        val = os.environ.get(legacy, "")
    return val


def config() -> dict:
    url = _env("SUPABASE_URL").rstrip("/")
    key = _env("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    enc = _env("SUPABASE_SYNC_ENCRYPTION_KEY")
    iid = _env("SUPABASE_SYNC_INSTANCE_ID")
    if not url or not key or not enc or not iid:
        raise RuntimeError("Supabase env not fully configured")
    if not url.startswith("https://"):
        raise RuntimeError("SUPABASE_URL must be HTTPS")
    if not re_match_iid(iid):
        raise RuntimeError("SUPABASE_SYNC_INSTANCE_ID invalid format")
    raw = base64.b64decode(enc)
    if len(raw) != 32:
        raise RuntimeError("SUPABASE_SYNC_ENCRYPTION_KEY must decode to 32 bytes")
    return {"url": url, "key": key, "aes": raw, "iid": iid}


def re_match_iid(v: str) -> bool:
    import re
    return bool(re.match(r"^[A-Za-z0-9._-]{1,128}$", v))


# --- crypto (AES-256-GCM envelope) ----------------------------------------

def encrypt(plaintext: bytes, key: bytes) -> str:
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, plaintext, AAD)
    # AESGCM returns ciphertext||tag; last 16 bytes = tag.
    data, tag = ct[:-16], ct[-16:]
    return json.dumps({
        "version": 1,
        "iv": base64.b64encode(iv).decode(),
        "tag": base64.b64encode(tag).decode(),
        "data": base64.b64encode(data).decode(),
    })


def decrypt(envelope_json: str, key: bytes) -> bytes:
    env = json.loads(envelope_json)
    if env.get("version") != 1:
        raise RuntimeError(f"unsupported envelope version {env.get('version')}")
    iv = base64.b64decode(env["iv"])
    tag = base64.b64decode(env["tag"])
    data = base64.b64decode(env["data"])
    return AESGCM(key).decrypt(iv, data + tag, AAD)


# --- HTTP helpers ----------------------------------------------------------

def _req(cfg: dict, method: str, path: str, body: object = None) -> dict:
    url = cfg["url"] + "/rest/v1/" + path
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return {}
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")


# --- store -----------------------------------------------------------------

def payload() -> dict:
    files = {}
    for path in SNAPSHOT_TARGETS:
        try:
            with open(path, "rb") as f:
                files[path] = base64.b64encode(f.read()).decode()
        except OSError:
            continue
    return {
        "formatVersion": FORMAT_VERSION,
        "createdAt": int(time.time() * 1000),
        "files": files,
    }


def checksum(ciphertext: str) -> str:
    return hashlib.sha256(ciphertext.encode()).hexdigest()


def upload() -> None:
    cfg = config()
    body = payload()
    plain = json.dumps(body, separators=(",", ":")).encode()
    ct = encrypt(plain, cfg["aes"])
    row = {
        "instance_id": cfg["iid"],
        "format_version": FORMAT_VERSION,
        "revision": int(time.time()),
        "ciphertext": ct,
        "checksum": checksum(ct),
        "updated_at": "now()",
    }
    _req(
        cfg,
        "POST",
        f"{TABLE}?on_conflict=instance_id",
        body=row,
    )
    # Prefer header for upsert merge — urllib cannot set easily; use PATCH fallback.
    # Re-issue as upsert via Prefer header:
    url = cfg["url"] + f"/rest/v1/{TABLE}?on_conflict=instance_id"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    req = urllib.request.Request(url, data=json.dumps(row).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15):
        pass


def restore() -> None:
    cfg = config()
    rows = _req(cfg, "GET", f"{TABLE}?instance_id=eq.{cfg['iid']}&select=*")
    if not rows:
        print("[sync] no snapshot found", file=sys.stderr)
        return
    row = rows[0]
    ct = row["ciphertext"]
    if checksum(ct) != row.get("checksum", ""):
        raise RuntimeError("checksum mismatch — refusing restore")
    plain = decrypt(ct, cfg["aes"])
    body = json.loads(plain)
    if body.get("formatVersion") != FORMAT_VERSION:
        raise RuntimeError("format version mismatch")
    files = body.get("files", {})
    for path, b64 in files.items():
        if not _allowed(path):
            print(f"[sync] skip non-allowlisted path: {path}", file=sys.stderr)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"[sync] restored {path}", file=sys.stderr)


def _allowed(path: str) -> bool:
    return any(path == a or path.startswith(a + "/") for a in ALLOWLIST)


# --- watcher ---------------------------------------------------------------

def watch(interval: int = 60) -> None:
    """Fork a background process that uploads a snapshot every `interval` seconds."""
    pid = os.fork()
    if pid != 0:
        return
    # Child.
    try:
        os.setsid()
    except OSError:
        pass
    delay = 5
    while True:
        try:
            upload()
            delay = 5
        except Exception as exc:
            print(f"[sync] upload failed: {exc}", file=sys.stderr)
            delay = min(delay * 2, RETRY_CAP)
        time.sleep(delay)


# --- CLI -------------------------------------------------------------------

def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "restore":
        restore()
    elif cmd == "upload":
        upload()
    elif cmd == "status":
        try:
            cfg = config()
            print(f"configured: url={cfg['url']} iid={cfg['iid']}")
        except Exception as e:
            print(f"not configured: {e}")
    else:
        print(f"usage: {sys.argv[0]} restore|upload|status")
        sys.exit(1)


if __name__ == "__main__":
    main()
