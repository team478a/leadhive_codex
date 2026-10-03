. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
$instance = Assert-LeadHiveInstance
Assert-LeadHiveRelease | Out-Null
$lock = Enter-LeadHiveMaintenanceLock
try {
    $values = Read-LeadHiveEnvironment
    if ($values['LEADHIVE_MAINTENANCE_REQUIRED'] -eq 'true') { throw 'Incomplete maintenance must be recovered first.' }
    $blockers = Invoke-LeadHiveDatabaseReport -ResumeCheck
    $pending = ($blockers.PSObject.Properties | Measure-Object -Property Value -Sum).Sum
    if ($pending -gt 0) {
        Write-Host ($blockers | ConvertTo-Json -Compress)
        throw 'Unresolved delivery/campaign/form records exist. Worker stays paused; human reconciliation is required.'
    }
    Write-Host 'Review remote send history and confirm this environment is the only active copy.' -ForegroundColor Yellow
    if ((Read-Host "Type RESUME-$($instance.Id) after reviewing recovery") -cne "RESUME-$($instance.Id)") { throw 'Resume cancelled.' }
    $blockers = Invoke-LeadHiveDatabaseReport -ResumeCheck
    if (($blockers.PSObject.Properties | Measure-Object -Property Value -Sum).Sum -gt 0) { throw 'Delivery state changed during review.' }
    Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'false'
    try { Invoke-LeadHiveCompose up -d --force-recreate worker } catch {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
        Invoke-LeadHiveCompose stop worker
        throw
    }
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
