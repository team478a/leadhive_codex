# Deployment identity only; this is not a substitute for tenant authorization.
function Read-LeadHiveEnvironment([string]$Path = $script:LeadHiveEnv) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Environment file is missing. Run Install-LeadHive.cmd."
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') {
            if ($values.ContainsKey($Matches[1])) { throw "Duplicate environment setting." }
            $values[$Matches[1]] = $Matches[2]
        }
    }
    return $values
}

function Get-LeadHiveDigest([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) |
            ForEach-Object { $_.ToString('x2') })
    } finally { $sha.Dispose() }
}

function Get-LeadHiveVolume([string]$Name) {
    # List first: an inspect failure must not be mistaken for a missing volume.
    $names = @(& docker volume ls --format '{{.Name}}')
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect Docker volumes." }
    if ($names -notcontains $Name) { return $null }
    $json = & docker volume inspect $Name
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect the deployment volume." }
    return @($json | ConvertFrom-Json)[0]
}

function Get-LeadHiveInstance {
    $values = Read-LeadHiveEnvironment
    $id = $values['LEADHIVE_INSTANCE_ID']
    if ($id -notmatch '^[a-f0-9]{32}$') {
        throw "Unbound legacy environment. Run Adopt-LeadHive.cmd before starting or updating."
    }
    $project = $values['LEADHIVE_PROJECT_NAME']
    $volume = $values['LEADHIVE_DATA_VOLUME']
    $isLegacy = $volume -eq 'leadhive-local-postgres-data' -and
        $project -in @('leadhive', 'leadhive-local')
    if (-not $isLegacy -and ($project -cne "leadhive-$id" -or $volume -cne "leadhive-$id-data")) {
        throw "Deployment ID, Compose project and data volume do not match."
    }
    if (-not $values['POSTGRES_PASSWORD'] -or -not $values['SETTINGS_ENCRYPTION_KEY']) {
        throw "Deployment security settings are missing. Do not generate replacement keys."
    }
    # Compose gives inherited environment variables priority over --env-file.
    foreach ($name in @('POSTGRES_PASSWORD', 'SETTINGS_ENCRYPTION_KEY', 'LEADHIVE_INSTANCE_ID',
            'LEADHIVE_PROJECT_NAME', 'LEADHIVE_DATA_VOLUME', 'LEADHIVE_PORT', 'CORS_ORIGINS',
            'PUBLIC_APP_URL', 'LEADHIVE_DATABASE_NAME', 'LEADHIVE_WORKER_PAUSED', 'LEADHIVE_OUTBOUND_ENABLED', 'OUTBOUND_ENABLED')) {
        $inherited = [Environment]::GetEnvironmentVariable($name)
        if ($null -ne $inherited -and ($inherited -cne $values[$name] -or
            $name -in @('LEADHIVE_DATABASE_NAME', 'LEADHIVE_WORKER_PAUSED', 'LEADHIVE_OUTBOUND_ENABLED', 'OUTBOUND_ENABLED'))) {
            throw "An inherited environment setting conflicts with this deployment."
        }
    }
    $script:LeadHiveProject = $project
    return [pscustomobject]@{
        Id = $id; Project = $project; Volume = $volume; Legacy = $isLegacy
        Binding = "$volume-identity"
        SecurityDigest = Get-LeadHiveDigest ($values['POSTGRES_PASSWORD'] + "`n" + $values['SETTINGS_ENCRYPTION_KEY'])
    }
}

function Assert-LeadHiveProjectMounts($Instance) {
    $ids = @(& docker ps -aq --filter "label=com.docker.compose.project=$($Instance.Project)")
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect deployment containers." }
    foreach ($containerId in $ids) {
        if (-not $containerId) { continue }
        $json = & docker inspect $containerId
        if ($LASTEXITCODE -ne 0) { throw "Cannot inspect deployment containers." }
        $container = @($json | ConvertFrom-Json)[0]
        if ($container.Config.Labels.'com.docker.compose.service' -eq 'db') {
            $mounts = @($container.Mounts | Where-Object { $_.Destination -eq '/var/lib/postgresql/data' })
            if ($mounts.Count -ne 1 -or $mounts[0].Name -cne $Instance.Volume) {
                throw "Compose project is connected to a different database. Operation stopped."
            }
        }
    }
}

function Assert-LeadHiveInstance {
    $instance = Get-LeadHiveInstance
    $data = Get-LeadHiveVolume $instance.Volume
    $binding = Get-LeadHiveVolume $instance.Binding
    if (-not $data -or -not $binding) {
        throw "Deployment binding or data volume is missing. Do not start with a new database."
    }
    if ($binding.Labels.'work.leadhive.instance' -cne $instance.Id -or
        $binding.Labels.'work.leadhive.project' -cne $instance.Project -or
        $binding.Labels.'work.leadhive.data' -cne $instance.Volume -or
        $binding.Labels.'work.leadhive.security' -cne $instance.SecurityDigest) {
        throw "Deployment identity or security settings do not match the database binding."
    }
    if (-not $instance.Legacy -and $data.Labels.'work.leadhive.instance' -cne $instance.Id) {
        throw "Data volume belongs to a different deployment."
    }
    if ($instance.Legacy -and $data.Labels.'com.docker.compose.project' -cne $instance.Project) {
        throw "Legacy data volume owner does not match the deployment."
    }
    Assert-LeadHiveProjectMounts $instance
    return $instance
}

function Register-LeadHiveInstance([switch]$AdoptLegacy, [switch]$CreateNew) {
    $instance = Get-LeadHiveInstance
    $data = Get-LeadHiveVolume $instance.Volume
    $binding = Get-LeadHiveVolume $instance.Binding
    if ($binding) { Assert-LeadHiveInstance | Out-Null; return }
    if (-not $AdoptLegacy -and -not $CreateNew) {
        throw "Deployment binding is missing. Recovery review is required; a new database will not be created."
    }
    if ($instance.Legacy) {
        if (-not $AdoptLegacy -or -not $data) { throw "Legacy database requires explicit adoption." }
    } elseif ($data) {
        if ($data.Labels.'work.leadhive.instance' -cne $instance.Id) {
            throw "Refusing to bind an existing unrelated volume."
        }
    } else {
        & docker volume create --label "work.leadhive.instance=$($instance.Id)" `
            --label "work.leadhive.security=$($instance.SecurityDigest)" $instance.Volume | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Cannot create deployment data volume." }
    }
    Assert-LeadHiveProjectMounts $instance
    & docker volume create --label "work.leadhive.instance=$($instance.Id)" `
        --label "work.leadhive.project=$($instance.Project)" --label "work.leadhive.data=$($instance.Volume)" `
        --label "work.leadhive.security=$($instance.SecurityDigest)" $instance.Binding | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot register deployment identity." }
    Assert-LeadHiveInstance | Out-Null
}

function Write-LeadHiveBackupIdentity([string]$BackupPath) {
    $instance = Assert-LeadHiveInstance
    $metadata = [ordered]@{
        format_version = 1; instance_id = $instance.Id; data_volume = $instance.Volume
        sha256 = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()
        security_digest = $instance.SecurityDigest; created_at = [DateTime]::UtcNow.ToString('o')
    }
    [IO.File]::WriteAllText("$BackupPath.identity.json", ($metadata | ConvertTo-Json),
        (New-Object Text.UTF8Encoding($false)))
}

function Assert-LeadHiveBackupIdentity([string]$BackupPath) {
    $instance = Assert-LeadHiveInstance
    $metadataPath = "$BackupPath.identity.json"
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
        throw "Backup identity is missing. Unidentified legacy backups require separate recovery review."
    }
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    if ($metadata.format_version -notin @(1, 2) -or $metadata.instance_id -cne $instance.Id -or
        $metadata.data_volume -cne $instance.Volume -or $metadata.security_digest -cne $instance.SecurityDigest -or
        $metadata.sha256 -cne (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "Backup belongs to another deployment, has different keys, or failed integrity validation."
    }
    $backupEnv = Read-LeadHiveEnvironment "$BackupPath.env.local"
    if ($backupEnv['LEADHIVE_INSTANCE_ID'] -cne $instance.Id -or
        (Get-LeadHiveDigest ($backupEnv['POSTGRES_PASSWORD'] + "`n" + $backupEnv['SETTINGS_ENCRYPTION_KEY'])) -cne $instance.SecurityDigest) {
        throw "Backup security file does not match this deployment."
    }
}
