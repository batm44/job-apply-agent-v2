# Optional: one unattended run, used by register_task.ps1. You can also just ask Claude Code
# "find and apply jobs for me" whenever you like instead of scheduling.
# Only the tools listed below are allowed; anything else is denied (dontAsk), so it never hangs on a prompt.
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $Claude) { $Claude = "$env:USERPROFILE\.local\bin\claude.exe" }
if (Test-Path "$env:LOCALAPPDATA\Programs\nodejs\node.exe") { $env:Path = "$env:LOCALAPPDATA\Programs\nodejs;$env:Path" }

$day = Get-Date -Format 'yyyy-MM-dd'
$runDir = Join-Path $Root "daily-runs\$day"
New-Item -ItemType Directory -Force $runDir | Out-Null
$log = Join-Path $runDir 'claude.log'
$python = (Join-Path $Root '.venv\Scripts\python.exe') -replace '\\', '/'

$prompt = @"
In $Root, read DAILY_RUN.md and execute the complete search-and-apply workflow: career-ops scan,
triage and evaluation, then journal ingest, plan, documents and browser applications. Use
$python for autoapply.py and node for career-ops. Respect saved authorization, eligibility
gates, daily limits and the submission journal. Stop if paused or onboarding is incomplete.
Record confirmed employer receipts, run autoapply.py manual-queue, and write the daily digest.
Use the Bash tool for shell commands.
"@

$allowed = @(
  'Read', 'Glob', 'Grep', 'Edit', 'Write', 'WebSearch', 'WebFetch',
  'mcp__job_application_browser__browser_action',
  'Bash(node:*)', 'Bash(npm run:*)', "Bash(${python}:*)", 'Bash(.venv/Scripts/python.exe:*)',
  'Bash(cd:*)', 'Bash(ls:*)', 'Bash(cat:*)', 'Bash(head:*)', 'Bash(tail:*)', 'Bash(grep:*)',
  'Bash(mkdir:*)', 'Bash(cp:*)', 'Bash(date:*)', 'Bash(wc:*)'
)
$denied = @('Bash(git push:*)', 'Bash(git commit:*)', 'Bash(rm:*)', 'Bash(curl:*)')

Set-Location $Root
"=== $(Get-Date -Format o) start" | Out-File -Append -Encoding utf8 $log
& $Claude -p $prompt `
  --permission-mode dontAsk `
  --allowedTools $allowed `
  --disallowedTools $denied `
  --mcp-config (Join-Path $Root '.mcp.json') `
  --add-dir (Join-Path $Root 'career-ops') `
  --output-format text 2>&1 | Out-File -Append -Encoding utf8 $log
"=== $(Get-Date -Format o) exit $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log
