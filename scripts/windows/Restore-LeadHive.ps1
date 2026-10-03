param([string]$BackupPath = '')
. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
Assert-LeadHiveInstance | Out-Null
Assert-LeadHiveRelease | Out-Null
if (-not $BackupPath) {
    $latest = Get-ChildItem (Join-Path $script:LeadHiveRoot 'backups') -Filter 'leadhive-*.dump' -File -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath "$($_.FullName).identity.json" } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw 'No completed backup bundle was found.' }
    $BackupPath = $latest.FullName
}
$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)
Assert-LeadHiveBackupIdentity $resolvedBackup
Read-LeadHiveRecoveryBundle $resolvedBackup | Out-Null
Write-Host "Restore into a NEW database; original database will be kept: $resolvedBackup" -ForegroundColor Yellow
if ((Read-Host 'Type RESTORE to continue') -cne 'RESTORE') { throw 'Restore cancelled.' }
$lock = Enter-LeadHiveMaintenanceLock
try {
    Assert-LeadHiveBackupIdentity $resolvedBackup
    Suspend-LeadHiveForMaintenance
    Invoke-LeadHiveCompose build
    Write-Host "Safety backup: $(New-LeadHiveBackup)"
    Restore-LeadHiveIntoNewDatabase $resolvedBackup
    Complete-LeadHiveMaintenance
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
