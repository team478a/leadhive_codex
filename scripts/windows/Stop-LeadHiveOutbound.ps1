. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
Assert-LeadHiveInstance | Out-Null
Assert-LeadHiveRelease | Out-Null
$lock = Enter-LeadHiveMaintenanceLock
try {
    $wasIncomplete = (Read-LeadHiveEnvironment)['LEADHIVE_MAINTENANCE_REQUIRED'] -eq 'true'
    Suspend-LeadHiveForMaintenance
    if ($wasIncomplete) {
        Write-Host 'Outbound disabled. Incomplete maintenance remains blocked; recover before starting services.'
        return
    }
    Complete-LeadHiveMaintenance
    Write-Host 'Outbound disabled. Use Resume-LeadHive.cmd for collection/analysis only.'
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
