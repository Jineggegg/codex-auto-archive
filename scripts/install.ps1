param([string]$CodexHome = "", [switch]$NoScheduler)
$ErrorActionPreference = "Stop"
$archiveRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "codex-auto-archive\runtime"
if ($CodexHome) { $env:CODEX_HOME = $CodexHome }
& uv sync --frozen --project $archiveRoot
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
$archiveArgs = @("run", "--frozen", "--no-sync", "--project", $archiveRoot, "codex-auto-archive", "install", "--plugin-root", $archiveRoot)
if ($NoScheduler) { $archiveArgs += "--no-scheduler" }
& uv @archiveArgs
if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed" }
