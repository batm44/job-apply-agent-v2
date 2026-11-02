# Optional: run the agent automatically every day at 09:00 (your PC's local time).
# Runs only while you are logged in; if the PC was off at 09:00 it runs when you next log in.
# Turn it off again with:  Unregister-ScheduledTask -TaskName JobApplyDaily -Confirm:$false
$script = Join-Path $PSScriptRoot 'run_daily.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At 09:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
  -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'JobApplyDaily' -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Daily job search and auto-apply (job-apply-agent)' -Force
