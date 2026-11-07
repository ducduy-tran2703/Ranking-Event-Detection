# Windows fallback: executable từ GitHub release chính thức, lưu ngoài Git.
# Docker là lựa chọn thay thế; chỉ chạy MỘT trong hai trên cổng 6333/6334.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$binary = Join-Path $repoRoot 'data\tools\qdrant-v1.20.0\qdrant.exe'
$stateDir = Join-Path $repoRoot 'data\rag\qdrant'
if (-not (Test-Path -LiteralPath $binary)) {
    throw 'Thiếu data/tools/qdrant-v1.20.0/qdrant.exe. Xem docs/handoff/rag.md.'
}
foreach ($port in @(6333, 6334)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Cổng $port đang được dùng. Không khởi động thêm Qdrant."
    }
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
# Đường dẫn storage tương đối tính từ WorkingDirectory của tiến trình Qdrant.
$configText = @'
storage:
  storage_path: ./storage
  snapshots_path: ./snapshots
service:
  host: 127.0.0.1
  http_port: 6333
  grpc_port: 6334
telemetry_disabled: true
'@
[System.IO.File]::WriteAllText((Join-Path $stateDir 'config.yaml'), $configText,
    [System.Text.UTF8Encoding]::new($false))
$process = Start-Process -FilePath $binary -ArgumentList '--config-path', 'config.yaml' `
    -WorkingDirectory $stateDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateDir 'stdout.log') `
    -RedirectStandardError (Join-Path $stateDir 'stderr.log')
Write-Output "Qdrant started: PID=$($process.Id), URL=http://127.0.0.1:6333"
