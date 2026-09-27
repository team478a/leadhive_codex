param([string]$BackupPath = "")

. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed. Run Install-LeadHive.cmd first."
}

if (-not $BackupPath) {
    $backupDirectory = Join-Path $script:LeadHiveRoot "backups"
    $latest = Get-ChildItem $backupDirectory -Filter "leadhive-*.dump" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw "No LeadHive backup was found in the backups folder." }
    $BackupPath = $latest.FullName
}

$resolvedBackup = [IO.Path]::GetFullPath($BackupPath)
if (-not (Test-Path -LiteralPath $resolvedBackup -PathType Leaf)) {
    throw "Backup file was not found: $resolvedBackup"
}

Write-Host "This replaces the current LeadHive database with:" -ForegroundColor Yellow
Write-Host $resolvedBackup -ForegroundColor Yellow
$confirmation = Read-Host "Type RESTORE to continue"
if ($confirmation -cne "RESTORE") {
    Write-Host "Restore cancelled."
    exit 0
}

Write-Step "Creating a safety backup of the current database"
& (Join-Path $PSScriptRoot "Backup-LeadHive.ps1")
if ($LASTEXITCODE -ne 0) { throw "The safety backup failed. Restore was stopped." }

Write-Step "Stopping LeadHive application services"
Invoke-LeadHiveCompose stop api worker web
Invoke-LeadHiveCompose up -d --wait db
$containerId = (& docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv `
    -f $script:LeadHiveCompose ps -q db).Trim()
if (-not $containerId) { throw "Database container was not found." }

Write-Step "Restoring the database"
& docker cp $resolvedBackup "${containerId}:/tmp/leadhive-restore.dump"
if ($LASTEXITCODE -ne 0) { throw "Copying the restore file failed." }
try {
    & docker exec $containerId pg_restore -U postgres -d leadhive_v2 --clean --if-exists `
        --no-owner --no-privileges /tmp/leadhive-restore.dump
    if ($LASTEXITCODE -ne 0) { throw "Database restore failed." }
} finally {
    & docker exec $containerId rm -f /tmp/leadhive-restore.dump | Out-Null
}

Write-Step "Updating the restored database"
Invoke-LeadHiveCompose run --rm migrate
Write-Step "Starting LeadHive"
Invoke-LeadHiveCompose up -d api worker web
$url = Wait-LeadHive
Write-Host "Restore completed: $url" -ForegroundColor Green
Start-LeadHiveBrowser $url
