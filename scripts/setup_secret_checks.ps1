$ErrorActionPreference = 'Stop'

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw 'Run this script from inside the Fintech Change Radar Git repository.'
}

$scanner = Get-Command gitleaks -ErrorAction SilentlyContinue
if (-not $scanner -and $env:LOCALAPPDATA) {
    $wingetLink = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\gitleaks.exe'
    if (Test-Path -LiteralPath $wingetLink) {
        $scannerPath = $wingetLink
    } else {
        $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        $scannerPath = Get-ChildItem -LiteralPath $packageRoot -Directory -Filter 'Gitleaks.Gitleaks_*' -ErrorAction SilentlyContinue |
            ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Filter 'gitleaks.exe' -ErrorAction SilentlyContinue } |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $scanner -and -not $scannerPath) {
    throw 'Gitleaks is not installed. Run: winget install --id Gitleaks.Gitleaks --exact'
}

$hookDirectory = Join-Path $repoRoot '.githooks'
foreach ($hook in @('pre-commit', 'pre-push')) {
    if (-not (Test-Path -LiteralPath (Join-Path $hookDirectory $hook))) {
        throw "Required Git hook is missing: $hook"
    }
}

& git -C $repoRoot config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw 'Could not configure core.hooksPath.'
}

Write-Host 'Secret checks enabled for this repository.'
Write-Host 'Gitleaks runs automatically before every Git commit and push, including Git commands started by Codex.'
Write-Host 'If a check fails, review the finding locally; Gitleaks output is redacted.'
