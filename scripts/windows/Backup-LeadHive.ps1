. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
Assert-LeadHiveInstance | Out-Null
Assert-LeadHiveRelease | Out-Null
$lock = Enter-LeadHiveMaintenanceLock
try {
    Suspend-LeadHiveForMaintenance
    Write-Step 'Creating a verified backup bundle'
    $backup = New-LeadHiveBackup
    Complete-LeadHiveMaintenance
    Write-Host "Backup created: $backup. Keep dump, env.local and identity.json together."
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
