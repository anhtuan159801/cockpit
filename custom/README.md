# Custom overlay — cockpit fork

Thư mục này chứa toàn bộ code đặc thù của fork, tách biệt khỏi upstream
để merge upstream mà không conflict.

## Cấu trúc

```
custom/
  entrypoint.py       # Startup: resolve port → restore snapshot → watcher → exec label-run
  supabase_sync.py    # Supabase config snapshot (AES-256-GCM + PostgREST)
  patches/            # Patch bắt buộc khi phải sửa file upstream (xem patches/README.md)
  sync-upstream.ps1   # Script sync upstream/main → fork
  README.md           # File này
```

## Supabase sync

- Env: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_SYNC_ENCRYPTION_KEY`, `SUPABASE_SYNC_INSTANCE_ID`
- Bảng: `cockpit_config_snapshots` (xem `supabase/migrations/`)
- Allowlist ghi file: `/etc/cockpit/cockpit.conf`, `/etc/ssh/ssh_known_hosts`, `/etc/cockpit/ssh/*`
- Entry point tự restore snapshot (all-or-nothing) trước khi start watcher.

## Bridge overlay (BUILD_BRIDGE)

Mặc định `BUILD_BRIDGE=0` — image dùng bridge có sẵn trong `quay.io/cockpit/ws`.
Chỉ bật `BUILD_BRIDGE=1` khi fork diverge và cần bridge đã patch.
Vendor sources được clone theo SHA-pin trong Dockerfile stage `bridge`.

## Không sửa file upstream

- Code custom chỉ ở path mới → `git merge upstream/main` không conflict.
- Nếu bắt buộc sửa file upstream → tạo patch trong `custom/patches/` và apply lúc build.
- Xem `UPSTREAM.md` cho checklist sau mỗi lần sync.
