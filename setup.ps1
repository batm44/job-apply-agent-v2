# One-time setup for job-apply-agent. Safe to run again: it skips what is already done.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nSTOPPED: $text" -ForegroundColor Red; exit 1 }

Step 'Checking Python (3.12 or newer)'
$py = $null
foreach ($candidate in @('py -3.12', 'py -3', 'python')) {
  try {
    $exe, $arg = $candidate.Split(' ')
    # No quotes inside the Python code: Windows PowerShell 5.1 strips them when calling programs.
    $code = & $exe @($arg | Where-Object { $_ }) -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>$null
    if ($code -and [int]$code -ge 312) { $py = $candidate; $ver = '{0}.{1}' -f [math]::Floor([int]$code / 100), ([int]$code % 100); break }
  } catch {}
}
if (-not $py) { Fail 'Python 3.12+ not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.' }
Write-Host "Found Python $ver"

Step 'Checking Node.js (22 or newer)'
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node -and (Test-Path "$env:LOCALAPPDATA\Programs\nodejs\node.exe")) { $env:Path = "$env:LOCALAPPDATA\Programs\nodejs;$env:Path"; $node = Get-Command node }
if (-not $node) { Fail 'Node.js not found. Install the LTS version from https://nodejs.org/ , close and reopen PowerShell, then run this again.' }
$nodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -lt 22) { Fail "Node.js $(node --version) is too old. Install the LTS version from https://nodejs.org/ ." }
Write-Host "Found Node.js $(node --version)"

Step 'Checking Git and Google Chrome'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'Git not found. Install it from https://git-scm.com/download/win , then run this again.' }
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ }
if (-not $chrome) { Fail 'Google Chrome not found. Install it from https://www.google.com/chrome/ , then run this again.' }
Write-Host 'Git and Chrome found'

Step 'Creating the Python environment (.venv) and installing packages'
if (-not (Test-Path '.venv\Scripts\python.exe')) { $exe, $arg = $py.Split(' '); & $exe @($arg | Where-Object { $_ }) -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

Step 'Creating your private folders (never uploaded to GitHub)'
foreach ($dir in 'data', 'resume', 'applications', 'daily-runs') { New-Item -ItemType Directory -Force $dir | Out-Null }

Step 'Downloading career-ops (job search and scoring engine)'
if (-not (Test-Path 'career-ops\package.json')) { git clone --depth 1 https://github.com/career-ops-hq/career-ops.git career-ops }
Push-Location career-ops
npm install --no-audit --no-fund
node doctor.mjs --json --init-templates | Out-Null
$custom = 'modes\_custom.md'
if (-not (Select-String -Path $custom -Pattern 'job-apply-agent' -Quiet -ErrorAction SilentlyContinue)) {
  Copy-Item -Force "$Root\career-ops-setup\_custom.md" $custom
}
Pop-Location

Step 'Connecting the browser tool to Claude Code (.mcp.json)'
$mcp = @{ mcpServers = @{ job_application_browser = @{
  command = (Resolve-Path '.venv\Scripts\python.exe').Path
  args = @((Join-Path $Root 'browser_mcp.py')) } } }
[IO.File]::WriteAllText((Join-Path $Root '.mcp.json'), ($mcp | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))

Step 'Testing the browser'
& .\.venv\Scripts\python.exe browser_mcp.py --check

Write-Host "`nSETUP COMPLETE." -ForegroundColor Green
Write-Host 'Next: put your resume PDF in the "resume" folder, open Claude Code in this folder, and say:'
Write-Host '  Set up my profile from my resume' -ForegroundColor Yellow
