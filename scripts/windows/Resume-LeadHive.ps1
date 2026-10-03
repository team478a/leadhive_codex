. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
$instance = Assert-LeadHiveInstance
Assert-LeadHiveRelease | Out-Null
$lock = Enter-LeadHiveMaintenanceLock
try {
    $values = Read-LeadHiveEnvironment
    if ($values['LEADHIVE_MAINTENANCE_REQUIRED'] -eq 'true') { throw 'Incomplete maintenance must be recovered first.' }
    Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
    Invoke-LeadHiveCompose stop worker
    $sendingEnabled = $values['LEADHIVE_OUTBOUND_ENABLED'] -eq 'true'
    $blockers = Invoke-LeadHiveDatabaseReport -ResumeCheck
    $pending = ($blockers.PSObject.Properties | Measure-Object -Property Value -Sum).Sum
    if ($sendingEnabled -and $pending -gt 0) {
        Write-Host ($blockers | ConvertTo-Json -Compress)
        throw 'Unresolved delivery/campaign/form records exist. Worker stays paused; human reconciliation is required.'
    }
    Write-Host 'Review remote send history and confirm this environment is the only active copy.' -ForegroundColor Yellow
    if ((Read-Host "Type RESUME-$($instance.Id) after reviewing recovery") -cne "RESUME-$($instance.Id)") { throw 'Resume cancelled.' }
    $blockers = Invoke-LeadHiveDatabaseReport -ResumeCheck
    if ($sendingEnabled -and ($blockers.PSObject.Properties | Measure-Object -Property Value -Sum).Sum -gt 0) { throw 'Delivery state changed during review.' }
    if (-not $sendingEnabled) {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_OUTBOUND_ENABLED' 'false'
        Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', '--force-recreate', 'api', 'web')
        Wait-LeadHive | Out-Null
        Write-Host 'Collection/analysis worker only. All LeadHive outbound execution remains disabled.'
    }
    Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'false'
    try { Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', '--force-recreate', 'worker') } catch {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
        Invoke-LeadHiveCompose stop worker
        throw
    }
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
