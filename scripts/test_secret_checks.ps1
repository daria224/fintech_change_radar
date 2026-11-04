$ErrorActionPreference = 'Stop'

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw 'Run this script from inside the Fintech Change Radar Git repository.'
}

$scanner = Get-Command gitleaks -ErrorAction SilentlyContinue
$scannerPath = if ($scanner) { $scanner.Source } else { $null }
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
if (-not $scannerPath) {
    throw 'Gitleaks is not installed. Run: winget install --id Gitleaks.Gitleaks --exact'
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('radar-gitleaks-test-' + [guid]::NewGuid().ToString('N'))
$fixtureToken = 'ghp_' + [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$hookSource = Join-Path $repoRoot '.githooks'
$gitExe = (Get-Command git -ErrorAction Stop).Source
$env:Path = (Split-Path -Parent $scannerPath) + ';' + $env:Path

function Invoke-Git([string[]]$Arguments, [int]$ExpectedExit = 0) {
    $output = & $gitExe -C $testRoot @Arguments 2>&1
    $actualExit = $LASTEXITCODE
    if ($actualExit -ne $ExpectedExit) {
        $safeOutput = ($output | ForEach-Object { [string]$_ }) -join "`n"
        if ($safeOutput.Contains($fixtureToken)) {
            $safeOutput = $safeOutput.Replace($fixtureToken, '[REDACTED TEST FIXTURE]')
        }
        throw "Git test returned $actualExit; expected $ExpectedExit.`n$safeOutput"
    }
    return $output
}

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    & $gitExe -C $testRoot init --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize disposable test repository.' }
    & $gitExe -C $testRoot config user.name 'Gitleaks Test'
    & $gitExe -C $testRoot config user.email 'gitleaks-test@example.invalid'

    Copy-Item -LiteralPath (Join-Path $repoRoot '.gitignore') -Destination (Join-Path $testRoot '.gitignore')
    Copy-Item -LiteralPath $hookSource -Destination (Join-Path $testRoot '.githooks') -Recurse
    & $gitExe -C $testRoot config core.hooksPath .githooks

    foreach ($ignoredPath in @('.env', '.env.local', 'nested/.env.production', 'private.pem', 'secrets/token.txt', 'config.local.json')) {
        Invoke-Git @('check-ignore', '--quiet', $ignoredPath) | Out-Null
    }
    Invoke-Git @('check-ignore', '--quiet', '.env.example') 1 | Out-Null
    Write-Host 'PASS: ignore rules block local secrets and allow the safe .env.example template.'

    Set-Content -LiteralPath (Join-Path $testRoot 'safe.txt') -Value 'safe fixture' -NoNewline
    Invoke-Git @('add', 'safe.txt') | Out-Null
    Invoke-Git @('commit', '-m', 'safe fixture') | Out-Null
    Write-Host 'PASS: pre-commit allows a clean staged change.'

    Set-Content -LiteralPath (Join-Path $testRoot 'missing-scanner.txt') -Value 'safe fixture' -NoNewline
    Invoke-Git @('add', 'missing-scanner.txt') | Out-Null
    $savedPath = $env:Path
    $savedLocalAppData = $env:LOCALAPPDATA
    $noScannerAppData = Join-Path $testRoot 'no-scanner-appdata'
    New-Item -ItemType Directory -Path $noScannerAppData | Out-Null
    try {
        $scannerDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $scannerPath)).TrimEnd('\')
        $env:Path = (($savedPath -split ';') | Where-Object { $_ -and [IO.Path]::GetFullPath($_).TrimEnd('\') -ne $scannerDirectory }) -join ';'
        $env:LOCALAPPDATA = $noScannerAppData
        $headBeforeMissingScanner = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
        Invoke-Git @('commit', '-m', 'missing scanner must fail closed') 1 | Out-Null
        $headAfterMissingScanner = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
        if ($headBeforeMissingScanner -ne $headAfterMissingScanner) { throw 'Commit proceeded without Gitleaks.' }
        Invoke-Git @('reset', '--quiet', '--', 'missing-scanner.txt') | Out-Null
    }
    finally {
        $env:Path = $savedPath
        $env:LOCALAPPDATA = $savedLocalAppData
    }
    Write-Host 'PASS: pre-commit fails closed when Gitleaks cannot be found.'

    Set-Content -LiteralPath (Join-Path $testRoot '.env.local') -Value $fixtureToken -NoNewline
    Set-Content -LiteralPath (Join-Path $testRoot 'safe-with-local-env.txt') -Value 'safe fixture' -NoNewline
    Invoke-Git @('add', 'safe-with-local-env.txt') | Out-Null
    Invoke-Git @('commit', '-m', 'ignored local env does not block') | Out-Null
    Write-Host 'PASS: an ignored .env.local does not enter the staged scan or block a safe commit.'

    foreach ($sensitivePath in @('.env', '.env.local', 'nested/.env.production', 'private.pem', 'secrets/token.txt', 'credentials/local.json', 'config.local.json')) {
        $sensitiveFile = Join-Path $testRoot $sensitivePath
        $sensitiveDirectory = Split-Path -Parent $sensitiveFile
        if ($sensitiveDirectory) { New-Item -ItemType Directory -Path $sensitiveDirectory -Force | Out-Null }
        Set-Content -LiteralPath $sensitiveFile -Value 'synthetic fixture only' -NoNewline
        Invoke-Git @('add', '--force', $sensitivePath) | Out-Null
        $beforeBlockedPathCommit = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
        Invoke-Git @('commit', '-m', 'forced sensitive path must be blocked') 1 | Out-Null
        $afterBlockedPathCommit = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
        if ($beforeBlockedPathCommit -ne $afterBlockedPathCommit) { throw "Pre-commit did not block forced sensitive path: $sensitivePath" }
        Invoke-Git @('reset', '--quiet', '--', $sensitivePath) | Out-Null
    }
    Write-Host 'PASS: pre-commit blocks forced additions of environment, private-key, and local credential paths.'

    Set-Content -LiteralPath (Join-Path $testRoot 'fake-secret.txt') -Value $fixtureToken -NoNewline
    Invoke-Git @('add', 'fake-secret.txt') | Out-Null
    $beforeBlockedCommit = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
    Invoke-Git @('commit', '-m', 'synthetic secret must be blocked') 1 | Out-Null
    $afterBlockedCommit = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
    if ($beforeBlockedCommit -ne $afterBlockedCommit) { throw 'Pre-commit did not block the synthetic secret.' }
    Write-Host 'PASS: pre-commit blocks a synthetic token; output remains redacted.'

    $bareRemote = Join-Path $testRoot 'remote.git'
    & $gitExe init --bare --quiet $bareRemote
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize disposable bare test remote.' }
    Invoke-Git @('-c', 'core.hooksPath=.githooks-disabled', 'push', $bareRemote, 'HEAD:refs/heads/main') | Out-Null

    & $gitExe -C $testRoot config core.hooksPath .githooks-disabled
    Invoke-Git @('commit', '--allow-empty', '-m', 'synthetic token in history') | Out-Null
    & $gitExe -C $testRoot config core.hooksPath .githooks
    $localHead = (& $gitExe -C $testRoot rev-parse HEAD).Trim()
    $remoteHeadBefore = (& $gitExe --git-dir=$bareRemote rev-parse refs/heads/main).Trim()

    Invoke-Git @('push', $bareRemote, 'HEAD:refs/heads/main') 1 | Out-Null
    $remoteHeadAfter = (& $gitExe --git-dir=$bareRemote rev-parse refs/heads/main).Trim()
    if ($remoteHeadBefore -ne $remoteHeadAfter) { throw 'Pre-push did not block the synthetic secret.' }
    Write-Host 'PASS: pre-push blocks a commit containing the synthetic token.'
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
