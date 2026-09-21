. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed."
}

Write-Step "Creating a database backup"
Invoke-LeadHiveCompose up -d --wait db
$backupDirectory = Join-Path $script:LeadHiveRoot "backups"
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $backupDirectory "leadhive-$timestamp.dump"
$containerId = (& docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv -f $script:LeadHiveCompose ps -q db).Trim()
if (-not $containerId) { throw "Database container was not found." }
& docker exec $containerId pg_dump -U postgres -d leadhive_v2 -Fc -f /tmp/leadhive.dump
if ($LASTEXITCODE -ne 0) { throw "Database backup failed." }
& docker cp "${containerId}:/tmp/leadhive.dump" $backupPath
if ($LASTEXITCODE -ne 0) { throw "Copying the backup failed." }
& docker exec $containerId rm -f /tmp/leadhive.dump
Copy-Item $script:LeadHiveEnv "$backupPath.env.local"
Write-Host "Backup created: $backupPath" -ForegroundColor Green
