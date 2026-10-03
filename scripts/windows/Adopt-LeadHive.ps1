param([string]$EnvironmentPath = '')

. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
if (-not $EnvironmentPath) { $EnvironmentPath = $script:LeadHiveEnv }
$sourcePath = [IO.Path]::GetFullPath($EnvironmentPath)
$values = Read-LeadHiveEnvironment $sourcePath
if ($values['LEADHIVE_INSTANCE_ID']) {
    if ($sourcePath -cne $script:LeadHiveEnv) { throw 'Already bound environment must be used in its own installation.' }
    Assert-LeadHiveInstance | Out-Null
    Write-Host 'Existing deployment identity verified. No services were started.'
    exit 0
}
if (-not $values['POSTGRES_PASSWORD'] -or -not $values['SETTINGS_ENCRYPTION_KEY']) {
    throw 'Original database password and encryption key are required. Adoption never replaces secrets.'
}
$volumeName = 'leadhive-local-postgres-data'
$data = Get-LeadHiveVolume $volumeName
if (-not $data) { throw 'No supported legacy database was found.' }
if (Get-LeadHiveVolume "$volumeName-identity") { throw 'Legacy database is already bound. Use its bound environment file.' }
$owner = $data.Labels.'com.docker.compose.project'
if ($owner -notin @('leadhive', 'leadhive-local')) { throw 'Legacy database owner is unknown. Adoption stopped.' }
if (($values['LEADHIVE_DATA_VOLUME'] -and $values['LEADHIVE_DATA_VOLUME'] -cne $volumeName) -or
    ($values['LEADHIVE_PROJECT_NAME'] -and $values['LEADHIVE_PROJECT_NAME'] -cne $owner)) {
    throw 'Original environment points to a different deployment.'
}
$ids = @(& docker ps -aq --filter "label=com.docker.compose.project=$owner" --filter 'label=com.docker.compose.service=db')
if ($LASTEXITCODE -ne 0 -or $ids.Count -ne 1 -or -not $ids[0]) {
    throw 'Exactly one existing legacy database container is required for verification.'
}
$json = & docker inspect $ids[0]
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect legacy database.' }
$container = @($json | ConvertFrom-Json)[0]
$mount = @($container.Mounts | Where-Object { $_.Destination -eq '/var/lib/postgresql/data' })
$passwordLine = @($container.Config.Env | Where-Object { $_ -like 'POSTGRES_PASSWORD=*' })
if ($mount.Count -ne 1 -or $mount[0].Name -cne $volumeName -or $passwordLine.Count -ne 1 -or
    $passwordLine[0].Substring('POSTGRES_PASSWORD='.Length) -cne $values['POSTGRES_PASSWORD']) {
    throw 'Original environment does not match the legacy database container.'
}
Write-Host "This binds existing database '$volumeName' in project '$owner'." -ForegroundColor Yellow
Write-Host 'Confirm this is the intended company. Use its original encryption key and make a backup first.'
$confirmation = Read-Host "Type ADOPT-$owner to register this existing environment"
if ($confirmation -cne "ADOPT-$owner") { throw 'Adoption cancelled. Nothing was changed.' }
if (Test-Path -LiteralPath $script:LeadHiveEnv) {
    if ($sourcePath -cne $script:LeadHiveEnv) { throw 'A local environment already exists. Resolve it manually before adoption.' }
}
$id = [Guid]::NewGuid().ToString('N')
$originalLines = Get-Content -LiteralPath $sourcePath | Where-Object {
    $_ -notmatch '^LEADHIVE_(INSTANCE_ID|PROJECT_NAME|DATA_VOLUME)='
}
$contents = ($originalLines -join "`n").TrimEnd() + "`n" +
    "LEADHIVE_INSTANCE_ID=$id`nLEADHIVE_PROJECT_NAME=$owner`nLEADHIVE_DATA_VOLUME=$volumeName`n"
# Keep the original unchanged as recovery evidence when adopting .env.local.
if ($sourcePath -ceq $script:LeadHiveEnv) {
    $originalPath = "$script:LeadHiveEnv.pre-identity"
    if (Test-Path -LiteralPath $originalPath) { throw 'Original environment backup already exists. Review it before retrying.' }
    Copy-Item -LiteralPath $sourcePath -Destination $originalPath
}
[IO.File]::WriteAllText($script:LeadHiveEnv, $contents, (New-Object Text.UTF8Encoding($false)))
Register-LeadHiveInstance -AdoptLegacy
Write-Host "Deployment registered: $id. Existing database, keys and services were preserved."
