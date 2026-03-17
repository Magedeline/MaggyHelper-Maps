param(
    [string]$Starter = "starter_route_map.jl",
    [switch]$LaunchLoenn,
    [string]$LoennDir = ""
)

$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$juliaExe = "C:\Users\Gabriel L\AppData\Local\Programs\Julia-1.12.5\bin\julia.exe"
$pythonExe = Join-Path $workspace ".venv\Scripts\python.exe"
$previewPy = Join-Path $workspace "loenn-mcp\preview_map.py"
$starterPath = Join-Path $PSScriptRoot $Starter

if (-not (Test-Path $juliaExe)) {
    throw "Julia not found at $juliaExe"
}

if (-not (Test-Path $pythonExe)) {
    throw "Python venv not found at $pythonExe"
}

if (-not (Test-Path $starterPath)) {
    throw "Starter script not found: $starterPath"
}

Write-Host "Running Maple starter: $Starter"
& $juliaExe $starterPath

$outputName = switch ($Starter) {
    "starter_minimal_map.jl" { "MapleStarter.bin" }
    "starter_entity_map.jl" { "MapleStarterEntity.bin" }
    "starter_route_map.jl" { "MapleStarterRoute.bin" }
    default {
        $base = [System.IO.Path]::GetFileNameWithoutExtension($Starter)
        if ($base.StartsWith("starter_")) {
            $base = $base.Substring(8)
        }
        "Maple$base.bin"
    }
}

$binPath = Join-Path $workspace "Maps\Maggy\$outputName"

if (-not (Test-Path $binPath)) {
    throw "Expected output not found: $binPath"
}

Write-Host "Previewing map: $binPath"
& $pythonExe $previewPy $binPath

if ($LaunchLoenn) {
    $launcher = Join-Path $PSScriptRoot "launch_loenn_checked.ps1"
    if (-not (Test-Path $launcher)) {
        throw "Loenn launcher not found: $launcher"
    }

    if ([string]::IsNullOrWhiteSpace($LoennDir)) {
        $LoennDir = $env:LOENN_DIR
    }

    Write-Host "Launching Loenn via DLL-checked launcher..."
    & $launcher -LoennDir $LoennDir
}
