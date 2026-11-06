# run_version.ps1 - run one archived version of NQ Cockpit next to the others.
#
# Usage:
#   scripts\run_version.bat v03-symbols
#   scripts\run_version.bat                 (lists the versions and their ports)
#
# Each tag gets its own git worktree in ..\nq-cockpit-versions\<tag> and its
# own port (v00 -> 8510, v01 -> 8511, ...). The main working tree is never
# modified, the real database is never written, and Telegram is disabled for
# the launched process.

param(
    [Parameter(Position = 0)][string]$Tag,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VersionsRoot = Join-Path (Split-Path $RepoRoot -Parent) 'nq-cockpit-versions'
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$AppRel = 'src\nqcockpit\ui\app.py'

function Get-VersionPort([string]$Name) {
    if ($Name -notmatch '^v(\d{2})') {
        throw "Version tag '$Name' does not start with vNN, so it has no fixed port."
    }
    return 8510 + [int]$Matches[1]
}

function Get-VersionTags {
    return @(git -C $RepoRoot tag --list 'v*' --sort=version:refname)
}

if (-not $Tag) {
    $tags = Get-VersionTags
    Write-Host ''
    Write-Host 'NQ Cockpit - archived versions (one port each):'
    Write-Host ''
    Write-Host ('  {0,-24} {1,-6} {2}' -f 'TAG', 'PORT', 'WHAT IT IS')
    foreach ($t in $tags) {
        $port = Get-VersionPort $t
        $desc = (git -C $RepoRoot tag -l --format='%(contents:subject)' $t) -join ' '
        Write-Host ('  {0,-24} {1,-6} {2}' -f $t, $port, $desc)
    }
    Write-Host ''
    Write-Host 'Open one:  scripts\run_version.bat v00-base'
    Write-Host 'Open all:  scripts\run_all_versions.bat'
    Write-Host 'Stop all:  scripts\stop_versions.bat'
    Write-Host ''
    exit 0
}

# --- validate the tag ------------------------------------------------------
git -C $RepoRoot rev-parse -q --verify "refs/tags/$Tag" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Unknown version tag '$Tag'. Run scripts\run_version.bat with no argument to list them."
}
$Port = Get-VersionPort $Tag
if ($Port -lt 8510 -or $Port -gt 8529) {
    throw "Computed port $Port is outside the reserved range 8510-8529."
}
if (-not (Test-Path $Python)) {
    throw "Python venv not found at $Python."
}

# --- worktree (created once, reused afterwards) ----------------------------
$Worktree = Join-Path $VersionsRoot $Tag
if (-not (Test-Path (Join-Path $Worktree '.git'))) {
    if (Test-Path $Worktree) {
        throw "Path exists but is not a git worktree: $Worktree. Remove it manually, then retry."
    }
    New-Item -ItemType Directory -Force -Path $VersionsRoot | Out-Null
    git -C $RepoRoot worktree prune | Out-Null
    Write-Host "Creating worktree for $Tag in $Worktree ..."
    git -C $RepoRoot worktree add --detach $Worktree $Tag
    if ($LASTEXITCODE -ne 0) { throw "git worktree add failed for $Tag." }
}
$AppPath = Join-Path $Worktree $AppRel
if (-not (Test-Path $AppPath)) { throw "Application entry point missing in worktree: $AppPath" }

# --- per-version database copy (the real database is never touched) -------
$VersionData = Join-Path (Join-Path $VersionsRoot '_data') $Tag
New-Item -ItemType Directory -Force -Path $VersionData | Out-Null
$SourceDb = Join-Path $RepoRoot 'data\nqcockpit.db'
$DbPath = Join-Path $VersionData 'nqcockpit.db'
if (-not (Test-Path $DbPath)) {
    if (Test-Path $SourceDb) {
        Write-Host 'Copying the local database for this version ...'
        Copy-Item -LiteralPath $SourceDb -Destination $DbPath -Force
    } else {
        Write-Host 'No local database found: starting this version with an empty one.'
        New-Item -ItemType File -Force -Path $DbPath | Out-Null
    }
}

# Environment for the launched process: version code first, copy of the DB,
# and no Telegram credentials at all.
$env:PYTHONPATH = Join-Path $Worktree 'src'
$env:NQ_DATA_DB_PATH = $DbPath
$env:NQ_DATA_BACKUP_DIR = (Join-Path $VersionData 'backups')
Remove-Item Env:TELEGRAM_BOT_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:TELEGRAM_CHAT_ID -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $env:NQ_DATA_BACKUP_DIR | Out-Null

# Sanity check: can this version's code open the database copy?
$ProbePath = Join-Path $VersionData '_db_probe.py'
$Probe = @'
import os
import sqlite3
import sys

db = os.environ["NQ_DATA_DB_PATH"]
try:
    conn = sqlite3.connect(db)
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    try:
        from nqcockpit.data.db import apply_migrations
        apply_migrations(conn)
    except ImportError:
        pass
    conn.close()
except Exception as exc:
    sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc))
    sys.exit(2)
'@
Set-Content -Path $ProbePath -Value $Probe -Encoding UTF8

$probeErr = & $Python $ProbePath 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warning "This version cannot open the database copy ($probeErr)."
    Write-Warning 'Falling back to a fresh empty database for this version.'
    $DbPath = Join-Path $VersionData 'empty.db'
    if (Test-Path $DbPath) { Remove-Item -LiteralPath $DbPath -Force }
    New-Item -ItemType File -Force -Path $DbPath | Out-Null
    $env:NQ_DATA_DB_PATH = $DbPath
}

# --- port must be free -----------------------------------------------------
$busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($busy) {
    throw "Port $Port is already in use. Run scripts\stop_versions.bat, then retry."
}

# --- launch ----------------------------------------------------------------
Set-Location $Worktree
$LogPath = Join-Path $VersionData 'streamlit.log'
$ErrPath = Join-Path $VersionData 'streamlit.err.log'
Remove-Item $LogPath, $ErrPath -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "NQ Cockpit $Tag"
Write-Host "  port : $Port"
Write-Host "  code : $Worktree"
Write-Host "  data : $DbPath"
Write-Host "  log  : $LogPath"
Write-Host '  Telegram: disabled for this process'
Write-Host ''

$StreamlitArgs = '-m streamlit run "' + $AppPath + '"' +
    ' --server.headless true --server.address 127.0.0.1' +
    ' --server.port ' + $Port + ' --browser.gatherUsageStats false'
$proc = Start-Process -FilePath $Python -ArgumentList $StreamlitArgs `
    -WorkingDirectory $Worktree -PassThru -NoNewWindow `
    -RedirectStandardOutput $LogPath -RedirectStandardError $ErrPath

$healthy = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { break }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/_stcore/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        # not up yet
    }
}

if ($healthy) {
    $url = "http://127.0.0.1:$Port/"
    Write-Host "Ready: $url"
    if (-not $NoBrowser) { Start-Process $url }
    Write-Host ('Closing this window does not stop the server; use scripts\stop_versions.bat.')
} else {
    Write-Warning "This version did not answer on /_stcore/health (port $Port)."
    if (Test-Path $ErrPath) {
        Write-Host '--- last error lines ---'
        Get-Content $ErrPath -Tail 20 | Write-Host
    }
    if ($proc.HasExited) {
        Write-Warning "The process exited with code $($proc.ExitCode)."
        exit 1
    }
    Write-Warning 'The process is still running; check the log above.'
}

Wait-Process -Id $proc.Id
