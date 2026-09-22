# Sync upstream/main → fork
# Chạy từ root repo: powershell -File custom/sync-upstream.ps1
# Tree phải sạch trước khi chạy.

$ErrorActionPreference = "Stop"

Write-Host "=== Cockpit upstream sync ===" -ForegroundColor Cyan

# 0. Verify clean tree
$status = git status --porcelain
if ($status) {
    Write-Host "ERROR: working tree not clean. Commit or stash first." -ForegroundColor Red
    exit 1
}

# 1. Fetch upstream
Write-Host "[1/6] Fetching upstream..." -ForegroundColor Yellow
git fetch upstream

# 2. Show what would merge
Write-Host "[2/6] Commits to merge:" -ForegroundColor Yellow
git log --oneline HEAD..upstream/main | Select-Object -First 20

# 3. Merge
Write-Host "[3/6] Merging upstream/main..." -ForegroundColor Yellow
git merge upstream/main --no-edit
if ($LASTEXITCODE -ne 0) {
    Write-Host "MERGE CONFLICT — resolve manually, then re-run." -ForegroundColor Red
    Write-Host "Custom paths should NOT conflict. Conflicts in upstream files = need patch strategy." -ForegroundColor Red
    exit 1
}

# 4. Verify vendor SHAs still match Dockerfile pins
Write-Host "[4/6] Verifying vendor SHAs..." -ForegroundColor Yellow
$expected = @{
    "vendor/beipack"        = "4217d8ade60885a18156e86e566b808edad000ee"
    "vendor/ferny"          = "73dd163349bf048d3d0a36f43228a9d052104e30"
    "vendor/systemd_ctypes" = "a627fb8b2b58e6dead4ab85aa14abb41d1a48397"
}
$submodules = git submodule status "vendor/*"
foreach ($line in $submodules) {
    if ($line -match "^\+?\s*([0-9a-f]{40})\s+(vendor/\S+)") {
        $sha = $Matches[1]; $path = $Matches[2]
        if ($expected.ContainsKey($path) -and $expected[$path] -ne $sha) {
            Write-Host "  SHA changed: $path = $sha (was $($expected[$path]))" -ForegroundColor Yellow
            Write-Host "  → Update Dockerfile ARG pins!" -ForegroundColor Yellow
        }
    }
}

# 5. Checklist items (manual)
Write-Host "[5/6] Manual checklist:" -ForegroundColor Yellow
Write-Host "  - ARG FEDORA_VERSION in Dockerfile matches containers/ws/Containerfile"
Write-Host "  - WS_IMAGE tag still valid (quay.io/cockpit/ws:latest or pin)"
Write-Host "  - label-run flags (--no-tls/--port) unchanged"
Write-Host "  - files.js shape unchanged (array of strings)"
Write-Host "  - vendor/checkout SHAs (if changed → update Dockerfile pins)"
Write-Host "  - po plugin still reads po/*.po directly"

# 6. Show diff summary
Write-Host "[6/6] Diff summary vs previous HEAD:" -ForegroundColor Yellow
git diff --stat HEAD@{1}..HEAD | Select-Object -First 30

Write-Host "=== Sync complete. Review, test build, commit. ===" -ForegroundColor Green
