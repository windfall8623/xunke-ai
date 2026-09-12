$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\Start-DockerDesktop.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) { throw 'FAIL: the safe Docker startup script is missing.' }
. $scriptPath

$testRoot = Join-Path ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\.superpowers'))) ('docker-startup-tests\' + [guid]::NewGuid().ToString('N'))
$dockerRoot = Join-Path $testRoot 'Docker'
$runPath = Join-Path $dockerRoot 'run'
$null = New-Item -ItemType Directory -Path $runPath -Force
[IO.File]::WriteAllText((Join-Path $runPath 'userAnalyticsOtlpHttp.sock'), 'preserve this fixture')

$dry = Move-DockerRuntimeDirectory -DockerDataRoot $dockerRoot -DryRun
if (-not $dry.WouldRotate -or -not (Test-Path -LiteralPath (Join-Path $runPath 'userAnalyticsOtlpHttp.sock'))) {
    throw 'FAIL: dry-run must report the repair without changing the socket.'
}
$first = Move-DockerRuntimeDirectory -DockerDataRoot $dockerRoot
if (-not (Test-Path -LiteralPath $runPath -PathType Container) -or -not $first.BackupPath) {
    throw 'FAIL: repair must recreate the runtime directory and return its backup.'
}
if ([IO.File]::ReadAllText((Join-Path $first.BackupPath 'userAnalyticsOtlpHttp.sock')) -ne 'preserve this fixture') {
    throw 'FAIL: repair must preserve all original socket-directory contents.'
}
[IO.File]::WriteAllText((Join-Path $runPath 'userAnalyticsOtlpHttp.sock'), 'second run')
$second = Move-DockerRuntimeDirectory -DockerDataRoot $dockerRoot
if ($first.BackupPath -eq $second.BackupPath -or -not (Test-Path -LiteralPath $first.BackupPath)) {
    throw 'FAIL: consecutive repairs must retain distinct backups.'
}
$empty = Move-DockerRuntimeDirectory -DockerDataRoot $dockerRoot
if ($empty.WouldRotate -or $empty.BackupPath) { throw 'FAIL: an empty runtime directory needs no rotation.' }

$null = New-Item -ItemType Directory -Path (Join-Path $runPath 'unexpected-data')
$rejected = $false
try { Move-DockerRuntimeDirectory -DockerDataRoot $dockerRoot | Out-Null } catch { $rejected = $true }
if (-not $rejected -or -not (Test-Path -LiteralPath (Join-Path $runPath 'unexpected-data'))) {
    throw 'FAIL: unknown subdirectories must be rejected and preserved.'
}

$wrongRoot = Join-Path $testRoot 'important-files'
$null = New-Item -ItemType Directory -Path (Join-Path $wrongRoot 'run') -Force
$rejected = $false
try { Move-DockerRuntimeDirectory -DockerDataRoot $wrongRoot | Out-Null } catch { $rejected = $true }
if (-not $rejected) { throw 'FAIL: a root other than the explicitly named Docker directory must be rejected.' }

Write-Output 'PASS: dry-run, preserved contents, unique repeated backups, empty no-op, unknown-directory rejection, and path boundary (6 checks).'
