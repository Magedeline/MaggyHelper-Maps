param(
    [string]$LoennDir = "",
    [switch]$ShowDlls
)

$ErrorActionPreference = "Stop"

$requiredFiles = @(
    "main.exe",
    "love.dll",
    "lua51.dll",
    "SDL2.dll"
)

function Test-LoennFolder {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string[]]$RequiredFiles
    )

    if (-not (Test-Path $Path)) {
        return $false
    }

    foreach ($file in $RequiredFiles) {
        if (-not (Test-Path (Join-Path $Path $file))) {
            return $false
        }
    }

    return $true
}

function Find-LoennFolder {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$RequiredFiles
    )

    $roots = @(
        "$env:USERPROFILE\Desktop",
        "$env:USERPROFILE\Downloads"
    )

    $mainExeFiles = @()
    foreach ($root in $roots) {
        if (Test-Path $root) {
            $mainExeFiles += Get-ChildItem -Path $root -Filter "main.exe" -File -Recurse -ErrorAction SilentlyContinue
        }
    }

    $candidateDirs = $mainExeFiles |
        ForEach-Object { $_.DirectoryName } |
        Sort-Object -Unique

    $scored = foreach ($dir in $candidateDirs) {
        if (Test-LoennFolder -Path $dir -RequiredFiles $RequiredFiles) {
            $nameScore = if ($dir -match "(?i)loenn|lonn") { 1 } else { 0 }
            [PSCustomObject]@{
                Path = $dir
                NameScore = $nameScore
            }
        }
    }

    return $scored |
        Sort-Object -Property @{Expression = 'NameScore'; Descending = $true}, @{Expression = 'Path'; Descending = $false} |
        Select-Object -ExpandProperty Path -First 1
}

if ([string]::IsNullOrWhiteSpace($LoennDir)) {
    $LoennDir = $env:LOENN_DIR
}

if (-not [string]::IsNullOrWhiteSpace($LoennDir)) {
    if (-not (Test-LoennFolder -Path $LoennDir -RequiredFiles $requiredFiles)) {
        Write-Host "Configured Loenn path is incomplete or missing files: $LoennDir" -ForegroundColor Yellow
        Write-Host "Trying auto-discovery under Desktop and Downloads..." -ForegroundColor Yellow
        $LoennDir = ""
    }
}

if ([string]::IsNullOrWhiteSpace($LoennDir)) {
    $LoennDir = Find-LoennFolder -RequiredFiles $requiredFiles
}

if ([string]::IsNullOrWhiteSpace($LoennDir)) {
    throw "No valid Loenn install found. Provide -LoennDir or set LOENN_DIR to a folder containing main.exe, love.dll, lua51.dll, and SDL2.dll."
}

$missingFiles = @()
foreach ($name in $requiredFiles) {
    $fullPath = Join-Path $LoennDir $name
    if (-not (Test-Path $fullPath)) {
        $missingFiles += $name
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host "Loenn launch blocked: required files are missing." -ForegroundColor Red
    Write-Host "Folder: $LoennDir"
    Write-Host "Missing: $($missingFiles -join ', ')"
    Write-Host ""
    Write-Host "Fix: re-extract the full Windows release zip so all DLLs sit next to main.exe."
    exit 1
}

if ($ShowDlls) {
    Write-Host "Detected DLL files in ${LoennDir}:" -ForegroundColor Cyan
    Get-ChildItem $LoennDir -Filter *.dll | Select-Object Name
}

$mainExe = Join-Path $LoennDir "main.exe"
Write-Host "Starting Loenn from: $LoennDir" -ForegroundColor Green
Start-Process -FilePath $mainExe -WorkingDirectory $LoennDir
