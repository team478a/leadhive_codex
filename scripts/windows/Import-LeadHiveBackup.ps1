param([Parameter(Mandatory = $true)][string]$BackupPath)
. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
Assert-LeadHiveRelease | Out-Null
$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)
$bundle = Read-LeadHiveRecoveryBundle $resolvedBackup
$id = $bundle.Metadata.instance_id
$installationLock = Enter-LeadHiveInstallationLock
$lock = $null
try {
    $lock = Enter-LeadHiveMaintenanceLock -InstanceId $id
    $retry = Test-Path -LiteralPath $script:LeadHiveEnv
    if ($retry) {
        $target = Assert-LeadHiveInstance
        $current = Read-LeadHiveEnvironment
        if ($target.Id -cne $id -or $target.SecurityDigest -cne $bundle.Metadata.security_digest -or
            $target.Legacy -or $current['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'true') {
            throw 'Import retry is permitted only for the same incomplete migrated environment.'
        }
    }
    if (-not $retry -and ((Get-LeadHiveVolume "leadhive-$id-data") -or (Get-LeadHiveVolume "leadhive-$id-data-identity") -or
        (Get-LeadHiveVolume 'leadhive-local-postgres-data'))) { throw 'An existing deployment was found. Import requires a dedicated empty environment.' }
    Write-Host 'The source PC MUST be stopped. Do not operate two copies of the same company.' -ForegroundColor Yellow
    if ((Read-Host "Type SOURCE-OFFLINE-IMPORT-$id to migrate this backup") -cne "SOURCE-OFFLINE-IMPORT-$id") { throw 'Import cancelled.' }
    if (-not $retry) {
        $values = $bundle.Environment
        $values['LEADHIVE_PROJECT_NAME'] = "leadhive-$id"
        $values['LEADHIVE_DATA_VOLUME'] = "leadhive-$id-data"
        $values['LEADHIVE_DATABASE_NAME'] = 'leadhive_v2'
        $values['LEADHIVE_WORKER_PAUSED'] = 'true'
        $values['LEADHIVE_OUTBOUND_ENABLED'] = 'false'
        $values['LEADHIVE_MAINTENANCE_REQUIRED'] = 'true'
        $lines = foreach ($name in $values.Keys) { "$name=$($values[$name])" }
        [IO.File]::WriteAllText($script:LeadHiveEnv, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
        Register-LeadHiveInstance -CreateNew
    }
    Invoke-LeadHiveCompose stop api worker web
    Invoke-LeadHiveCompose build
    Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', '--wait', 'db')
    Restore-LeadHiveIntoNewDatabase $resolvedBackup
    Complete-LeadHiveMaintenance
} finally {
    if ($lock) { $lock.ReleaseMutex(); $lock.Dispose() }
    $installationLock.ReleaseMutex(); $installationLock.Dispose()
}
