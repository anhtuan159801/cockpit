# Patches — file upstream bắt buộc phải sửa

Khi fork **bắt buộc** sửa một file vốn tồn tại ở upstream (không thể tách thành
path mới), tạo patch ở đây thay vì sửa trực tiếp trong tree.

## Quy ước

- Tên file: `< mô tả ngắn>.patch` (ví dụ: `allow-unix-socket.patch`)
- Patch được tạo từ gốc repo: `git diff > custom/patches/<tên>.patch`
- Apply lúc build (thêm vào Dockerfile) hoặc lúc sync: `git apply custom/patches/*.patch`
- Mỗi patch phải kèm ghi chú trong `UPSTREAM.md`: lý do, file ảnh hưởng, upstream commit liên quan.

## Khi nào cần patch

- Sửa `src/` hoặc `pkg/` upstream mà không thể fork logic ra file riêng.
- Thêm flag/env vào script upstream (ví dụ `label-run`).
- Sửa `files.js` array (ưu tiên: append-only, không reorder).

## Khi nào KHÔNG cần patch

- Thêm file mới (path mới → merge sạch).
- Thêm dependency vào `package.json` (merge thường clean hoặc conflict nhỏ tự resolve).
- Sửa file chỉ tồn tại trong fork (ví dụ `custom/*`, `Dockerfile`, `.env.example`).
