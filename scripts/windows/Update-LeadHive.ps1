. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
Assert-LeadHiveInstance | Out-Null
Assert-LeadHiveRelease | Out-Null
$lock = Enter-LeadHiveMaintenanceLock
try {
    Suspend-LeadHiveForMaintenance
    Write-Step 'Building the verified release while application services are stopped'
    Invoke-LeadHiveCompose build
    Write-Step 'Backing up the database before migration'
    $backup = New-LeadHiveBackup
    Write-Host "Pre-update backup: $backup"
    Invoke-LeadHiveCompose run --rm migrate
    Invoke-LeadHiveCompose -ComposeArguments @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'alembic', '-c', 'alembic.ini', 'check')
    Install-LeadHiveCodexSkill
    Complete-LeadHiveMaintenance
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
