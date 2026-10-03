function Enter-LeadHiveMaintenanceLock([string]$InstanceId = '') {
    if (-not $InstanceId) { $InstanceId = (Get-LeadHiveInstance).Id }
    if ($InstanceId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid maintenance instance ID.' }
    $mutex = New-Object Threading.Mutex($false, "Global\LeadHive-Maintenance-$InstanceId")
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { $mutex.Dispose(); throw 'Another backup/update/recovery operation is running.' }
    return $mutex
}

function Enter-LeadHiveInstallationLock {
    # Before an environment exists, different imported IDs must still serialize writes to this path.
    $path = [IO.Path]::GetFullPath($script:LeadHiveEnv).ToUpperInvariant()
    $digest = Get-LeadHiveDigest $path
    $mutex = New-Object Threading.Mutex($false, "Global\LeadHive-Installation-$digest")
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { $mutex.Dispose(); throw 'Another import is writing this installation.' }
    return $mutex
}

function Set-LeadHiveEnvironmentValue([string]$Name, [string]$Value) {
    $lines = @(Get-Content -LiteralPath $script:LeadHiveEnv | Where-Object { $_ -notmatch "^$Name=" })
    $temporary = "$script:LeadHiveEnv.$([Guid]::NewGuid().ToString('N')).tmp"
    [IO.File]::WriteAllText($temporary, (($lines + "$Name=$Value") -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
    [IO.File]::Replace($temporary, $script:LeadHiveEnv, [NullString]::Value)
}

function Get-LeadHiveDatabaseName {
    $values = Read-LeadHiveEnvironment
    $name = $values['LEADHIVE_DATABASE_NAME']
    if (-not $name) { return 'leadhive_v2' }
    if ($name -notmatch '^leadhive_[a-z0-9_]{1,48}$') { throw 'Invalid deployment database name.' }
    return $name
}

function Assert-LeadHiveRelease {
    $versionPath = Join-Path $script:LeadHiveRoot 'VERSION.txt'
    $manifestPath = Join-Path $script:LeadHiveRoot 'MANIFEST-SHA256.txt'
    if (-not (Test-Path $versionPath) -or -not (Test-Path $manifestPath)) {
        throw 'Use a verified distribution package for backup/update/recovery.'
    }
    $rootPrefix = [IO.Path]::GetFullPath($script:LeadHiveRoot).TrimEnd('\') + '\'
    $seen = @{}
    foreach ($line in Get-Content -LiteralPath $manifestPath) {
        if ($line -notmatch '^([a-f0-9]{64})  (.+)$') { throw 'Invalid release manifest.' }
        $hash = $Matches[1]; $relative = $Matches[2]
        $path = [IO.Path]::GetFullPath((Join-Path $script:LeadHiveRoot $relative))
        if (-not $path.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or $seen.ContainsKey($relative)) {
            throw 'Unsafe or duplicate release manifest path.'
        }
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
            throw 'Release content differs from its manifest.'
        }
        $seen[$relative] = $true
    }
    foreach ($required in @('VERSION.txt', 'compose.local.yaml', 'scripts/windows/Maintenance.ps1', 'backend/app/maintenance.py')) {
        if (-not $seen.ContainsKey($required)) { throw 'Release manifest is incomplete.' }
    }
    foreach ($directory in @('backend/app', 'backend/migrations', 'frontend/src', 'scripts/windows', 'deploy')) {
        $contentRoot = Join-Path $script:LeadHiveRoot $directory
        if (-not (Test-Path -LiteralPath $contentRoot)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $contentRoot -File -Recurse) {
            if ($file.FullName -match '[\\/]__pycache__[\\/]') { continue }
            $relative = $file.FullName.Substring($rootPrefix.Length).Replace('\', '/')
            if (-not $seen.ContainsKey($relative)) { throw 'Unregistered executable/release content was found.' }
        }
    }
    $version = Get-Content -LiteralPath $versionPath -Raw
    if ($version -notmatch '(?m)^Commit: ([a-f0-9]{40})\r?$') { throw 'Release commit is not pinned.' }
    return $Matches[1]
}

function Suspend-LeadHiveForMaintenance {
    Assert-LeadHiveInstance | Out-Null
    Set-LeadHiveEnvironmentValue 'LEADHIVE_OUTBOUND_ENABLED' 'false'
    Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
    Set-LeadHiveEnvironmentValue 'LEADHIVE_MAINTENANCE_REQUIRED' 'true'
    Invoke-LeadHiveCompose stop api worker web
    Invoke-LeadHiveCompose up -d --wait db
}

function Complete-LeadHiveMaintenance {
    # Worker stays paused until a separate reviewed Resume operation.
    try {
        Invoke-LeadHiveCompose up -d --force-recreate api web
        $url = Wait-LeadHive
        Set-LeadHiveEnvironmentValue 'LEADHIVE_MAINTENANCE_REQUIRED' 'false'
    } catch {
        Invoke-LeadHiveCompose stop api worker web
        throw
    }
    Write-Host "Maintenance completed: $url. Worker remains paused."
}

function Get-LeadHiveDbContainer {
    Assert-LeadHiveInstance | Out-Null
    $id = (& docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv -f $script:LeadHiveCompose ps -q db).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $id) { throw 'Database container is missing.' }
    return $id
}

function Invoke-LeadHiveDatabaseReport([switch]$ResumeCheck) {
    $argsList = @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.maintenance')
    if ($ResumeCheck) { $argsList += '--resume-check' }
    $report = Invoke-LeadHiveCompose @argsList
    $parsed = ($report -join "`n") | ConvertFrom-Json
    if ($ResumeCheck) {
        if (@($parsed.PSObject.Properties).Count -ne 5) { throw 'Worker review returned unexpected fields.' }
        foreach ($name in @('email', 'form', 'campaign', 'batch', 'form_operation')) {
            $value = 0L
            if ($parsed.PSObject.Properties.Name -notcontains $name -or
                -not [long]::TryParse([string]$parsed.$name, [ref]$value) -or $value -lt 0) {
                throw 'Worker review returned an invalid or incomplete result.'
            }
        }
    } elseif (-not $parsed.fingerprints -or $parsed.schema_revision -notmatch '^[a-zA-Z0-9_]{1,32}$') {
        throw 'Recovery verification returned an invalid result.'
    }
    return $parsed
}

function New-LeadHiveBackup {
    $release = Assert-LeadHiveRelease
    $directory = Join-Path $script:LeadHiveRoot 'backups'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $name = 'leadhive-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
    $path = Join-Path $directory "$name.dump"
    $temporary = "/tmp/$name.dump"
    $container = Get-LeadHiveDbContainer
    try {
        & docker exec $container pg_dump -U postgres -d (Get-LeadHiveDatabaseName) -Fc -f $temporary
        if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
        & docker cp "${container}:$temporary" $path
        if ($LASTEXITCODE -ne 0) { throw 'Copying database backup failed.' }
        Copy-Item -LiteralPath $script:LeadHiveEnv -Destination "$path.env.local"
        Write-LeadHiveBackupIdentity $path
        $metadata = Get-Content -LiteralPath "$path.identity.json" -Raw | ConvertFrom-Json
        $metadata.format_version = 2
        $metadata | Add-Member -NotePropertyName release_commit -NotePropertyValue $release
        $metadata | Add-Member -NotePropertyName database_name -NotePropertyValue (Get-LeadHiveDatabaseName)
        $metadata | Add-Member -NotePropertyName database_report -NotePropertyValue (Invoke-LeadHiveDatabaseReport)
        [IO.File]::WriteAllText("$path.identity.json", ($metadata | ConvertTo-Json -Depth 12), (New-Object Text.UTF8Encoding($false)))
        return $path
    } catch {
        # A partial bundle must not be auto-selected as a completed backup.
        if (Test-Path -LiteralPath $path) { Move-Item -LiteralPath $path -Destination "$path.incomplete" }
        throw
    } finally { & docker exec $container rm -f $temporary | Out-Null }
}

function Restore-LeadHiveIntoNewDatabase([string]$BackupPath) {
    $metadata = Get-Content -LiteralPath "$BackupPath.identity.json" -Raw | ConvertFrom-Json
    if (-not $metadata.database_report -or $metadata.release_commit -notmatch '^[a-f0-9]{40}$') {
        throw 'Recovery needs a G1.2 backup with database verification evidence.'
    }
    $originalName = Get-LeadHiveDatabaseName
    $staging = 'leadhive_recovery_' + [Guid]::NewGuid().ToString('N')
    $container = Get-LeadHiveDbContainer
    $temporary = "/tmp/$staging.dump"
    try {
        & docker exec $container createdb -U postgres $staging
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create an isolated recovery database.' }
        & docker cp $BackupPath "${container}:$temporary"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot copy recovery backup.' }
        & docker exec $container pg_restore -U postgres -d $staging --no-owner --no-privileges --exit-on-error $temporary
        if ($LASTEXITCODE -ne 0) { throw 'Isolated database restore failed. Original DB preserved.' }
        Set-LeadHiveEnvironmentValue 'LEADHIVE_DATABASE_NAME' $staging
        $actual = Invoke-LeadHiveDatabaseReport
        $expected = $metadata.database_report
        if ($actual.schema_revision -cne $expected.schema_revision -or
            ($actual.fingerprints | ConvertTo-Json -Compress -Depth 8) -cne ($expected.fingerprints | ConvertTo-Json -Compress -Depth 8)) {
            throw 'Recovery content differs from its backup evidence.'
        }
        Invoke-LeadHiveCompose run --rm migrate
        Invoke-LeadHiveCompose -ComposeArguments @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'alembic', '-c', 'alembic.ini', 'check')
        Invoke-LeadHiveDatabaseReport | Out-Null
        Invoke-LeadHiveCompose -ComposeArguments @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.maintenance', '--invalidate-restored-auth') | Out-Null
        Write-Host "Verified restored database: $staging. Original database preserved: $originalName"
    } catch {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_DATABASE_NAME' $originalName
        throw
    } finally { & docker exec $container rm -f $temporary | Out-Null }
}

function Read-LeadHiveRecoveryBundle([string]$BackupPath) {
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) { throw 'Recovery dump is missing.' }
    $metadata = Get-Content -LiteralPath "$BackupPath.identity.json" -Raw | ConvertFrom-Json
    $values = Read-LeadHiveEnvironment "$BackupPath.env.local"
    $digest = Get-LeadHiveDigest ($values['POSTGRES_PASSWORD'] + "`n" + $values['SETTINGS_ENCRYPTION_KEY'])
    if ($metadata.format_version -ne 2 -or $metadata.instance_id -notmatch '^[a-f0-9]{32}$' -or
        $metadata.instance_id -cne $values['LEADHIVE_INSTANCE_ID'] -or
        $metadata.data_volume -cne $values['LEADHIVE_DATA_VOLUME'] -or
        $metadata.security_digest -cne $digest -or $metadata.release_commit -notmatch '^[a-f0-9]{40}$' -or
        -not $metadata.database_report.fingerprints -or
        $metadata.sha256 -cne (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'Recovery bundle is incomplete, inconsistent or corrupt.'
    }
    return [pscustomobject]@{ Metadata = $metadata; Environment = $values }
}
