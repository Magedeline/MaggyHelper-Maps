[CmdletBinding()]
param(
    [string]$CodeRepoPath = "",
    [switch]$Mirror
)

$ErrorActionPreference = "Stop"

$mapsRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($CodeRepoPath)) {
    $CodeRepoPath = Join-Path (Split-Path $mapsRoot -Parent) "MaggyHelper-Code"
}

$CodeRepoPath = [System.IO.Path]::GetFullPath($CodeRepoPath)
if (-not (Test-Path $CodeRepoPath)) {
    throw "Code repo not found: $CodeRepoPath"
}

$items = @("Loenn", "MapleStarters", "Maps", "Mountain", "loenn-mcp")
$excludeDirs = @(".git", ".vs", ".venv", "bin", "obj", "__pycache__")

foreach ($item in $items) {
    $sourcePath = Join-Path $mapsRoot $item
    if (-not (Test-Path $sourcePath)) {
        continue
    }

    $destPath = Join-Path $CodeRepoPath $item
    New-Item -ItemType Directory -Path $destPath -Force | Out-Null

    $args = @(
        $sourcePath,
        $destPath,
        "/E",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP"
    )

    if ($Mirror) {
        $args += "/MIR"
    }

    if ($excludeDirs.Count -gt 0) {
        $args += "/XD"
        $args += $excludeDirs
    }

    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed for $item with exit code $LASTEXITCODE"
    }
}

Write-Host "Map-side content synced into: $CodeRepoPath"
if (-not $Mirror) {
    Write-Host "Deletes were not mirrored. Re-run with -Mirror if you want exact directory mirroring."
}