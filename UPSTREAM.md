# Upstream sync guide — cockpit fork

Fork: `https://github.com/anhtuan159801/cockpit.git` (origin)
Upstream: `https://github.com/cockpit-project/cockpit.git` (upstream)

> **Lưu ý từ HACKING.md upstream:** "Do not clone a fork."
> Cách làm của ta (origin = fork, upstream = official) là đúng —
> chỉ cần đảm bảo luôn merge từ `upstream/main`, không push ngược lên official.

## Isolation strategy

| Vùng | Path | Merge behavior |
|------|------|----------------|
| Code custom (luôn tạo mới) | `custom/**`, `Dockerfile`, `.dockerignore`, `.env.example`, `UPSTREAM.md`, `supabase/**` | Không conflict — path mới |
| Code upstream | `src/**`, `pkg/**`, `test/**`, `tools/**`, `build.js`, `files.js`, ... | Giữ nguyên, merge sạch |
| Bắt buộc sửa upstream | Tạo `custom/patches/*.patch`, apply lúc build | Có conflict → resolve một lần, convert sang patch |
| `.gitignore` | Append 1 dòng `.env` + marker `# custom: .env` | Conflict nhỏ nếu upstream sửa `.gitignore` |

**Quy tắc vàng:** Code custom chỉ ở path MỚI. Không sửa file upstream trừ khi bất khả kháng → patch.

## Sync workflow

```powershell
# 1. Tree phải sạch
git status

# 2. Chạy script sync (fetch + merge + verify + checklist)
powershell -File custom/sync-upstream.ps1

# 3. Nếu conflict → resolve rồi commit
git add -A && git commit -m "merge upstream/main"

# 4. Test build
docker build -t cockpit-custom .

# 5. Push fork
git push origin main
```

## Checklist sau mỗi sync

- [ ] `ARG FEDORA_VERSION` trong Dockerfile khớp `containers/ws/Containerfile` (hiện: fedora:43)
- [ ] Image tag `WS_IMAGE` / `quay.io/cockpit/ws:latest` còn valid
- [ ] Flags của `label-run` (`--no-tls`, `--port`) không đổi
- [ ] Shape của `files.js` (array of strings) không đổi
- [ ] `vendor/checkout` SHAs — nếu thay đổi → cập nhật SHA-pin trong Dockerfile stage `bridge`
- [ ] po plugin vẫn đọc `po/*.po` trực tiếp (không cần `.pot` / `POTFILES.in`)
- [ ] `.gitignore` vẫn có dòng `.env` + marker `# custom: .env`

## Vendor SHAs (pin trong Dockerfile)

| Submodule | SHA |
|-----------|-----|
| beipack | `4217d8ade60885a18156e86e566b808edad000ee` |
| ferny | `73dd163349bf048d3d0a36f43228a9d052104e30` |
| systemd_ctypes | `a627fb8b2b58e6dead4ab85aa14abb41d1a48397` |

Kiểm tra: `git submodule status 'vendor/*'`
Nếu SHA thay đổi → cập nhật Dockerfile stage `bridge`.

## Tại sao không clone theo HACKING.md

Upstream khuyến nghị clone thẳng official thay vì fork để tránh drift.
Ta giữ fork vì cần custom Dockerfile + Supabase overlay + Koyeb deploy.
Bù lại: luôn sync từ `upstream/main`, custom code tách path mới → drift tối thiểu.
