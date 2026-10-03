# No Docker engine, network, application or database is used by these tests.
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $repository 'scripts/windows/Common.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('leadhive-identity-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$script:LeadHiveEnv = Join-Path $testRoot '.env.local'
$replica = Join-Path $testRoot 'replica'
$replicaScripts = Join-Path $replica 'scripts/windows'
$legacyEnv = Join-Path $replica '.env.local'
$global:G1MockFakeVolumes = @{}
$global:G1MockFakeContainers = @{}
$global:G1MockCalls = @()
$script:Passed = 0
$global:G1MockFailInspect = $false
$global:G1MockFailAction = ''
$global:G1MockReport = '{"schema_revision":"test_head","counts":{"table":1},"fingerprints":{"table":"abc"}}'
$savedEnvironment = @{}
foreach ($name in @('POSTGRES_PASSWORD', 'SETTINGS_ENCRYPTION_KEY', 'LEADHIVE_INSTANCE_ID',
        'LEADHIVE_PROJECT_NAME', 'LEADHIVE_DATA_VOLUME', 'LEADHIVE_PORT', 'CORS_ORIGINS', 'PUBLIC_APP_URL',
        'LEADHIVE_DATABASE_NAME', 'LEADHIVE_WORKER_PAUSED', 'LEADHIVE_OUTBOUND_ENABLED', 'OUTBOUND_ENABLED')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $null)
}

function docker {
    $global:G1MockCalls += ,@($args)
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'info' -or ($args[0] -eq 'compose' -and $args[1] -eq 'version')) { return 'mock engine' }
    if ($args[0] -eq 'volume' -and $args[1] -eq 'ls') { return @($global:G1MockFakeVolumes.Keys) }
    if ($args[0] -eq 'volume' -and $args[1] -eq 'inspect') {
        if ($global:G1MockFailInspect) { $global:LASTEXITCODE = 1; return }
        return ConvertTo-Json -Depth 8 -InputObject @($global:G1MockFakeVolumes[$args[2]])
    }
    if ($args[0] -eq 'volume' -and $args[1] -eq 'create') {
        $name = $args[-1]
        if (-not $global:G1MockFakeVolumes.ContainsKey($name)) {
            $labels = @{}
            for ($i = 2; $i -lt ($args.Count - 1); $i++) {
                if ($args[$i] -eq '--label') {
                    $i++; $parts = $args[$i].Split('=', 2); $labels[$parts[0]] = $parts[1]
                }
            }
            $global:G1MockFakeVolumes[$name] = @{ Name = $name; Labels = $labels }
        }
        return $name
    }
    if ($args[0] -eq 'ps') { return @($global:G1MockFakeContainers.Keys) }
    if ($args[0] -eq 'inspect') { return ConvertTo-Json -Depth 8 -InputObject @($global:G1MockFakeContainers[$args[1]]) }
    if ($args[0] -eq 'compose') {
        if ($global:G1MockFailAction -and $args -contains $global:G1MockFailAction) {
            $global:LASTEXITCODE = 1; return
        }
        if ($args -contains 'ps') { return 'db' }
        if ($args -contains 'app.maintenance') { return $global:G1MockReport }
        return
    }
    if ($args[0] -eq 'exec') {
        if ($global:G1MockFailAction -and $args -contains $global:G1MockFailAction) { $global:LASTEXITCODE = 1 }
        return
    }
    if ($args[0] -eq 'cp') {
        if ($args[1] -like 'db:/tmp/*') { [IO.File]::WriteAllText($args[2], 'mock dump') }
        return
    }
    throw "Unexpected Docker operation in isolated tests: $($args[0]) $($args[1])"
}

function Write-TestEnvironment([string]$Id = ('a' * 32), [switch]$Legacy) {
    $project = "leadhive-$Id"; $volume = "leadhive-$Id-data"
    if ($Legacy) { $project = 'leadhive-local'; $volume = 'leadhive-local-postgres-data' }
    [IO.File]::WriteAllText($script:LeadHiveEnv, @"
LEADHIVE_INSTANCE_ID=$Id
LEADHIVE_PROJECT_NAME=$project
LEADHIVE_DATA_VOLUME=$volume
POSTGRES_PASSWORD=test-only-password
SETTINGS_ENCRYPTION_KEY=test-only-encryption-key
LEADHIVE_PORT=8787
"@)
}
function Read-Host { return $global:G1MockConfirmation }

function Check([string]$Name, [scriptblock]$Action) {
    & $Action
    $script:Passed++
    Write-Output "PASS $Name"
}
function Denied([scriptblock]$Action, [string]$Message) {
    $caught = $false
    try { & $Action | Out-Null } catch {
        if ($_.Exception.Message -notlike "*$Message*") { throw }
        $caught = $true
    }
    if (-not $caught) { throw "Expected rejection: $Message" }
}

try {
    Write-TestEnvironment
    Check 'new instance binds data and identity' {
        Register-LeadHiveInstance -CreateNew
        $instance = Assert-LeadHiveInstance
        if ($instance.Id -cne ('a' * 32) -or $global:G1MockFakeVolumes.Count -ne 2) { throw 'Binding failed' }
    }
    Check 'Compose detach flag survives PowerShell common parameter binding' {
        Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', '--wait', 'db')
        $call = $global:G1MockCalls[-1]
        if ($call -notcontains '-d' -or ($call[-4..-1] -join ' ') -ne 'up -d --wait db') {
            throw 'Detached Compose arguments were lost.'
        }
    }
    Check 'production detached starts use explicit argument arrays' {
        foreach ($file in Get-ChildItem (Join-Path $repository 'scripts/windows') -Filter '*.ps1') {
            if ((Get-Content -LiteralPath $file.FullName -Raw) -match 'Invoke-LeadHiveCompose\s+up\s+-d\b') {
                throw 'PowerShell would consume Docker -d as Debug.'
            }
        }
    }
    Check 'repeat registration preserves volumes' {
        Register-LeadHiveInstance
        if ($global:G1MockFakeVolumes.Count -ne 2) { throw 'Unexpected new volume' }
    }
    Check 'missing identity volume cannot be silently rebound on start' {
        $name = "leadhive-$('a' * 32)-data-identity"
        $saved = $global:G1MockFakeVolumes[$name]; $global:G1MockFakeVolumes.Remove($name)
        Denied { Assert-LeadHiveInstance } 'missing'
        $global:G1MockFakeVolumes[$name] = $saved
    }
    Check 'duplicate environment identity rejected' {
        Add-Content -LiteralPath $script:LeadHiveEnv -Value "`nLEADHIVE_INSTANCE_ID=$('b' * 32)"
        Denied { Assert-LeadHiveInstance } 'Duplicate'
        Write-TestEnvironment
    }
    Check 'unlabelled existing data volume cannot be adopted as new' {
        $name = "leadhive-$('a' * 32)-data"
        $saved = $global:G1MockFakeVolumes[$name].Labels
        $global:G1MockFakeVolumes[$name].Labels = @{}
        Denied { Assert-LeadHiveInstance } 'different deployment'
        $global:G1MockFakeVolumes[$name].Labels = $saved
    }
    Check 'another company cannot use existing binding' {
        $pathText = Get-Content $script:LeadHiveEnv -Raw
        [IO.File]::WriteAllText($script:LeadHiveEnv, $pathText.Replace(('a' * 32), ('b' * 32)))
        Denied { Assert-LeadHiveInstance } 'missing'
        Write-TestEnvironment
    }
    Check 'tampered binding rejected' {
        $binding = $global:G1MockFakeVolumes["leadhive-$('a' * 32)-data-identity"]
        $binding.Labels['work.leadhive.instance'] = 'b' * 32
        Denied { Assert-LeadHiveInstance } 'do not match'
        $binding.Labels['work.leadhive.instance'] = 'a' * 32
    }
    Check 'changed encryption key rejected' {
        $text = Get-Content $script:LeadHiveEnv -Raw
        [IO.File]::WriteAllText($script:LeadHiveEnv, $text.Replace('test-only-encryption-key', 'different-key'))
        Denied { Assert-LeadHiveInstance } 'do not match'
        Write-TestEnvironment
    }
    Check 'ambient Compose override rejected' {
        [Environment]::SetEnvironmentVariable('LEADHIVE_DATA_VOLUME', 'other-company')
        Denied { Assert-LeadHiveInstance } 'inherited'
        [Environment]::SetEnvironmentVariable('LEADHIVE_DATA_VOLUME', $null)
    }
    Check 'inherited outbound enable cannot bypass local stop' {
        [Environment]::SetEnvironmentVariable('LEADHIVE_OUTBOUND_ENABLED', 'true')
        Denied { Assert-LeadHiveInstance } 'inherited'
        [Environment]::SetEnvironmentVariable('LEADHIVE_OUTBOUND_ENABLED', $null)
    }
    Check 'arbitrary project rejected' {
        $text = Get-Content $script:LeadHiveEnv -Raw
        [IO.File]::WriteAllText($script:LeadHiveEnv, $text.Replace("LEADHIVE_PROJECT_NAME=leadhive-$('a' * 32)", 'LEADHIVE_PROJECT_NAME=other-company'))
        Denied { Assert-LeadHiveInstance } 'do not match'
        Write-TestEnvironment
    }
    Check 'wrong container database mount rejected' {
        $global:G1MockFakeContainers['db'] = @{
            Config = @{ Labels = @{ 'com.docker.compose.service' = 'db' } }
            Mounts = @(@{ Destination = '/var/lib/postgresql/data'; Name = 'other-company' })
        }
        Denied { Assert-LeadHiveInstance } 'different database'
        $global:G1MockFakeContainers.Clear()
    }
    Check 'Docker inspection failure stops instead of creating database' {
        $global:G1MockFailInspect = $true
        Denied { Register-LeadHiveInstance } 'Cannot inspect'
        $global:G1MockFailInspect = $false
    }
    $dumpPath = Join-Path $testRoot 'test.dump'
    [IO.File]::WriteAllText($dumpPath, 'dummy backup, not a real DB')
    Copy-Item -LiteralPath $script:LeadHiveEnv -Destination "$dumpPath.env.local"
    Check 'own backup identity accepted' {
        Write-LeadHiveBackupIdentity $dumpPath
        Assert-LeadHiveBackupIdentity $dumpPath
    }
    Check 'modified dump rejected' {
        [IO.File]::WriteAllText($dumpPath, 'modified')
        Denied { Assert-LeadHiveBackupIdentity $dumpPath } 'integrity'
        [IO.File]::WriteAllText($dumpPath, 'dummy backup, not a real DB')
    }
    Check 'foreign backup rejected' {
        $metadata = Get-Content "$dumpPath.identity.json" -Raw | ConvertFrom-Json
        $metadata.instance_id = 'b' * 32
        $metadata | ConvertTo-Json | Set-Content "$dumpPath.identity.json"
        Denied { Assert-LeadHiveBackupIdentity $dumpPath } 'another deployment'
        Write-LeadHiveBackupIdentity $dumpPath
    }
    Check 'missing identity backup rejected' {
        Denied { Assert-LeadHiveBackupIdentity (Join-Path $testRoot 'old.dump') } 'missing'
    }
    Check 'wrong backup key rejected' {
        $text = Get-Content "$dumpPath.env.local" -Raw
        [IO.File]::WriteAllText("$dumpPath.env.local", $text.Replace('test-only-encryption-key', 'different-key'))
        Denied { Assert-LeadHiveBackupIdentity $dumpPath } 'security file'
    }
    $script:LeadHiveRoot = $testRoot
    $manifestFiles = @('VERSION.txt', 'compose.local.yaml', 'scripts/windows/Maintenance.ps1', 'backend/app/maintenance.py')
    foreach ($name in $manifestFiles) {
        $path = Join-Path $testRoot $name
        New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
        [IO.File]::WriteAllText($path, 'fixture')
    }
    [IO.File]::WriteAllText((Join-Path $testRoot 'VERSION.txt'), ('Commit: ' + ('c' * 40)))
    $manifest = foreach ($name in $manifestFiles) {
        (Get-FileHash -LiteralPath (Join-Path $testRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $name
    }
    [IO.File]::WriteAllText((Join-Path $testRoot 'MANIFEST-SHA256.txt'), ($manifest -join "`n"))
    function Wait-LeadHive { return 'http://localhost:8787' }
    Check 'release content manifest verifies exact commit' {
        if ((Assert-LeadHiveRelease) -cne ('c' * 40)) { throw 'Wrong release' }
    }
    Check 'changed release content rejected' {
        [IO.File]::WriteAllText((Join-Path $testRoot 'compose.local.yaml'), 'changed')
        Denied { Assert-LeadHiveRelease } 'differs'
        [IO.File]::WriteAllText((Join-Path $testRoot 'compose.local.yaml'), 'fixture')
    }
    Check 'maintenance mutex rejects another thread' {
        $lock = Enter-LeadHiveMaintenanceLock
        try {
            $runspace = [PowerShell]::Create()
            $runspace.AddScript('$m = New-Object Threading.Mutex($false, "Global\LeadHive-Maintenance-' + ('a' * 32) + '"); try { $m.WaitOne(0) } finally { $m.Dispose() }') | Out-Null
            $result = $runspace.Invoke(); $runspace.Dispose()
            if ($result[0] -ne $false) { throw 'Concurrent maintenance allowed' }
        } finally { $lock.ReleaseMutex(); $lock.Dispose() }
    }
    Check 'installation path lock serializes imports before environment creation' {
        $lock = Enter-LeadHiveInstallationLock
        try {
            $digest = Get-LeadHiveDigest ([IO.Path]::GetFullPath($script:LeadHiveEnv).ToUpperInvariant())
            $runspace = [PowerShell]::Create()
            $runspace.AddScript('$m = New-Object Threading.Mutex($false, "Global\LeadHive-Installation-' + $digest + '"); try { $m.WaitOne(0) } finally { $m.Dispose() }') | Out-Null
            $result = $runspace.Invoke(); $runspace.Dispose()
            if ($result[0] -ne $false) { throw 'Concurrent import path writes allowed' }
        } finally { $lock.ReleaseMutex(); $lock.Dispose() }
    }
    Check 'import obtains path and instance locks before writing environment' {
        $text = Get-Content (Join-Path $repository 'scripts/windows/Import-LeadHiveBackup.ps1') -Raw
        if ($text.IndexOf('Enter-LeadHiveInstallationLock') -gt $text.IndexOf('[IO.File]::WriteAllText') -or
            $text.IndexOf('Enter-LeadHiveMaintenanceLock') -gt $text.IndexOf('[IO.File]::WriteAllText')) { throw 'Import lock obtained too late' }
    }
    Check 'maintenance pauses worker before stopping services' {
        Suspend-LeadHiveForMaintenance
        $values = Read-LeadHiveEnvironment
        if ($values['LEADHIVE_WORKER_PAUSED'] -ne 'true' -or $values['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'true') { throw 'Missing pause flags' }
        Denied { Invoke-LeadHiveCompose up -d worker } 'Worker is paused'
    }
    Check 'isolated restore failure preserves original database and pause' {
        $global:G1MockFailAction = 'pg_restore'
        $metadata = [pscustomobject]@{ release_commit = ('c' * 40); database_report = @{ schema_revision = 'test_head'; fingerprints = @{ table = 'abc' } } }
        $metadata | ConvertTo-Json -Depth 8 | Set-Content "$dumpPath.identity.json"
        Denied { Restore-LeadHiveIntoNewDatabase $dumpPath } 'Original DB preserved'
        $global:G1MockFailAction = ''
        if ((Get-LeadHiveDatabaseName) -ne 'leadhive_v2' -or (Read-LeadHiveEnvironment)['LEADHIVE_WORKER_PAUSED'] -ne 'true') { throw 'Unsafe restore failure' }
    }
    Check 'restored content mismatch does not switch active database' {
        $global:G1MockReport = '{"schema_revision":"test_head","fingerprints":{"table":"different"}}'
        Denied { Restore-LeadHiveIntoNewDatabase $dumpPath } 'differs'
        if ((Get-LeadHiveDatabaseName) -ne 'leadhive_v2') { throw 'Switched unverified DB' }
        $global:G1MockReport = '{"schema_revision":"test_head","counts":{"table":1},"fingerprints":{"table":"abc"}}'
    }
    Check 'verified restore selects new database but keeps worker paused' {
        Restore-LeadHiveIntoNewDatabase $dumpPath
        if ((Get-LeadHiveDatabaseName) -notlike 'leadhive_recovery_*') { throw 'Did not select isolated DB' }
        Complete-LeadHiveMaintenance
        if ((Read-LeadHiveEnvironment)['LEADHIVE_WORKER_PAUSED'] -ne 'true') { throw 'Worker resumed automatically' }
    }
    Check 'backup includes verification report and unique dump path' {
        Suspend-LeadHiveForMaintenance
        $first = New-LeadHiveBackup; $second = New-LeadHiveBackup
        if ($first -eq $second) { throw 'Backup path collision' }
        $bundle = Read-LeadHiveRecoveryBundle $first
        if ($bundle.Metadata.format_version -ne 2 -or -not $bundle.Metadata.database_report) { throw 'Backup evidence missing' }
    }
    Check 'failed backup is not a completed dump' {
        $global:G1MockReport = 'invalid-json'
        Denied { New-LeadHiveBackup } 'invalid'
        $global:G1MockReport = '{"schema_revision":"test_head","counts":{"table":1},"fingerprints":{"table":"abc"}}'
    }
    Check 'resume result must include every delivery route' {
        $global:G1MockReport = '{"email":0}'
        Denied { Invoke-LeadHiveDatabaseReport -ResumeCheck } 'unexpected fields'
        $global:G1MockReport = '{"email":0,"form":0,"campaign":0,"batch":0,"form_operation":0}'
        Invoke-LeadHiveDatabaseReport -ResumeCheck | Out-Null
    }
    Check 'invalid database identifier rejected before Compose execution' {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_DATABASE_NAME' 'bad;DROP DATABASE'
        Denied { Invoke-LeadHiveCompose up -d db } 'Invalid deployment database'
        Set-LeadHiveEnvironmentValue 'LEADHIVE_DATABASE_NAME' 'leadhive_v2'
    }
    Write-TestEnvironment
    Check 'unbound legacy environment rejected' {
        [IO.File]::WriteAllText($script:LeadHiveEnv, 'POSTGRES_PASSWORD=legacy')
        Denied { Assert-LeadHiveInstance } 'Adopt-LeadHive'
    }
    Check 'legacy adoption command rejects mismatched original password before writing' {
        $replica = Join-Path $testRoot 'replica'
        $replicaScripts = Join-Path $replica 'scripts/windows'
        New-Item -ItemType Directory -Path $replicaScripts -Force | Out-Null
        foreach ($name in @('Common.ps1', 'InstanceIdentity.ps1', 'Maintenance.ps1', 'Adopt-LeadHive.ps1')) {
            Copy-Item -LiteralPath (Join-Path $repository "scripts/windows/$name") -Destination $replicaScripts
        }
        $legacyEnv = Join-Path $replica '.env.local'
        [IO.File]::WriteAllText($legacyEnv, "POSTGRES_PASSWORD=wrong`nSETTINGS_ENCRYPTION_KEY=original-key")
        $global:G1MockFakeVolumes['leadhive-local-postgres-data'] = @{
            Name = 'leadhive-local-postgres-data'; Labels = @{ 'com.docker.compose.project' = 'leadhive-local' }
        }
        $global:G1MockFakeContainers['legacy-db'] = @{
            Config = @{ Env = @('POSTGRES_PASSWORD=original-password'); Labels = @{ 'com.docker.compose.service' = 'db' } }
            Mounts = @(@{ Destination = '/var/lib/postgresql/data'; Name = 'leadhive-local-postgres-data' })
        }
        Denied { & (Join-Path $replicaScripts 'Adopt-LeadHive.ps1') } 'does not match'
        if ((Read-LeadHiveEnvironment $legacyEnv)['LEADHIVE_INSTANCE_ID']) { throw 'Wrote identity before validation' }
        $global:G1MockFakeContainers.Clear()
    }
    Check 'legacy adoption cancellation leaves original environment untouched' {
        [IO.File]::WriteAllText($legacyEnv, "POSTGRES_PASSWORD=original-password`nSETTINGS_ENCRYPTION_KEY=original-key")
        $global:G1MockFakeContainers['legacy-db'] = @{
            Config = @{ Env = @('POSTGRES_PASSWORD=original-password'); Labels = @{ 'com.docker.compose.service' = 'db' } }
            Mounts = @(@{ Destination = '/var/lib/postgresql/data'; Name = 'leadhive-local-postgres-data' })
        }
        $global:G1MockConfirmation = 'CANCEL'
        Denied { & (Join-Path $replicaScripts 'Adopt-LeadHive.ps1') } 'cancelled'
        if ((Read-LeadHiveEnvironment $legacyEnv)['LEADHIVE_INSTANCE_ID']) { throw 'Cancelled adoption wrote identity' }
    }
    Check 'confirmed legacy command preserves original secrets and database' {
        $global:G1MockConfirmation = 'ADOPT-leadhive-local'
        & (Join-Path $replicaScripts 'Adopt-LeadHive.ps1')
        $adopted = Read-LeadHiveEnvironment $legacyEnv
        if ($adopted['POSTGRES_PASSWORD'] -cne 'original-password' -or
            $adopted['SETTINGS_ENCRYPTION_KEY'] -cne 'original-key' -or
            -not $adopted['LEADHIVE_INSTANCE_ID'] -or
            -not (Test-Path -LiteralPath "$legacyEnv.pre-identity")) { throw 'Adoption lost original settings' }
        $global:G1MockFakeContainers.Clear()
        $global:G1MockFakeVolumes.Remove('leadhive-local-postgres-data-identity')
    }
    Check 'legacy requires explicit adoption and preserves data' {
        Write-TestEnvironment -Legacy
        $global:G1MockFakeVolumes['leadhive-local-postgres-data'] = @{
            Name = 'leadhive-local-postgres-data'; Labels = @{ 'com.docker.compose.project' = 'leadhive-local' }
        }
        Denied { Register-LeadHiveInstance } 'Recovery review'
        Register-LeadHiveInstance -AdoptLegacy
        Assert-LeadHiveInstance | Out-Null
    }
    Check 'second company cannot adopt already bound legacy database' {
        Write-TestEnvironment -Id ('b' * 32) -Legacy
        Denied { Register-LeadHiveInstance -AdoptLegacy } 'do not match'
    }
    Check 'every mutating command uses common guarded Compose' {
        foreach ($file in @('Start', 'Stop', 'Update', 'Backup', 'Restore', 'Install')) {
            $text = Get-Content (Join-Path $repository "scripts/windows/$file-LeadHive.ps1") -Raw
            if ($text -notmatch 'Invoke-LeadHiveCompose|Suspend-LeadHiveForMaintenance') { throw "Missing guard: $file" }
        }
        $text = Get-Content (Join-Path $repository 'scripts/windows/Restore-LeadHive.ps1') -Raw
        if ($text.IndexOf('Assert-LeadHiveBackupIdentity') -gt $text.IndexOf('Read-Host')) { throw 'Restore guard too late' }
    }
    $recoveryRoot = Join-Path $testRoot 'recovery-command-fixture'
    $recoveryScripts = Join-Path $recoveryRoot 'scripts/windows'
    New-Item -ItemType Directory -Path $recoveryScripts -Force | Out-Null
    foreach ($name in @('Common.ps1', 'InstanceIdentity.ps1', 'Maintenance.ps1', 'Repair-LeadHiveInstance.ps1',
            'Update-LeadHive.ps1', 'Resume-LeadHive.ps1', 'Import-LeadHiveBackup.ps1', 'Stop-LeadHiveOutbound.ps1')) {
        Copy-Item -LiteralPath (Join-Path $repository "scripts/windows/$name") -Destination $recoveryScripts
    }
    New-Item -ItemType Directory -Path (Join-Path $recoveryRoot 'backend/app') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $recoveryRoot 'backend/app/maintenance.py'), 'fixture')
    [IO.File]::WriteAllText((Join-Path $recoveryRoot 'compose.local.yaml'), 'fixture')
    [IO.File]::WriteAllText((Join-Path $recoveryRoot 'VERSION.txt'), ('Commit: ' + ('c' * 40)))
    $releaseManifest = Get-ChildItem -LiteralPath $recoveryRoot -File -Recurse | ForEach-Object {
        (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' +
            $_.FullName.Substring($recoveryRoot.Length + 1).Replace('\', '/')
    }
    [IO.File]::WriteAllText((Join-Path $recoveryRoot 'MANIFEST-SHA256.txt'), ($releaseManifest -join "`n"))
    $recoveryEnv = Join-Path $recoveryRoot '.env.local'
    [IO.File]::WriteAllText($recoveryEnv, @"
LEADHIVE_INSTANCE_ID=$('e' * 32)
LEADHIVE_PROJECT_NAME=leadhive-$('e' * 32)
LEADHIVE_DATA_VOLUME=leadhive-$('e' * 32)-data
POSTGRES_PASSWORD=test-only-password
SETTINGS_ENCRYPTION_KEY=test-only-encryption-key
"@)
    $global:G1MockFakeVolumes["leadhive-$('e' * 32)-data"] = @{
        Labels = @{
            'work.leadhive.instance' = ('e' * 32)
            'work.leadhive.security' = Get-LeadHiveDigest "test-only-password`ntest-only-encryption-key"
        }
    }
    function Invoke-RestMethod { return @{ status = 'ok'; database = 'ok' } }
    Check 'partial registration repair preserves data and pauses worker' {
        $global:G1MockConfirmation = "REPAIR-$('e' * 32)"
        & (Join-Path $recoveryScripts 'Repair-LeadHiveInstance.ps1')
        if ((Read-LeadHiveEnvironment $recoveryEnv)['LEADHIVE_WORKER_PAUSED'] -ne 'true') { throw 'Repair did not pause worker' }
    }
    Check 'update migration failure leaves application stopped and recovery flag set' {
        $global:G1MockReport = '{"schema_revision":"test_head","counts":{"table":1},"fingerprints":{"table":"abc"}}'
        $global:G1MockFailAction = 'migrate'
        Denied { & (Join-Path $recoveryScripts 'Update-LeadHive.ps1') } 'Compose command failed'
        $global:G1MockFailAction = ''
        $values = Read-LeadHiveEnvironment $recoveryEnv
        if ($values['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'true' -or $values['LEADHIVE_WORKER_PAUSED'] -ne 'true') { throw 'Update failed open' }
    }
    Check 'worker resume rejects incomplete maintenance before any send' {
        Denied { & (Join-Path $recoveryScripts 'Resume-LeadHive.ps1') } 'Incomplete maintenance'
    }
    Check 'incomplete new-PC migration can resume from its matching verified bundle' {
        $migrationBackup = Get-ChildItem (Join-Path $recoveryRoot 'backups') -Filter '*.dump' | Select-Object -First 1
        $global:G1MockConfirmation = "SOURCE-OFFLINE-IMPORT-$('e' * 32)"
        & (Join-Path $recoveryScripts 'Import-LeadHiveBackup.ps1') -BackupPath $migrationBackup.FullName
        $values = Read-LeadHiveEnvironment $recoveryEnv
        if ($values['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'false' -or $values['LEADHIVE_WORKER_PAUSED'] -ne 'true' -or
            $values['LEADHIVE_DATABASE_NAME'] -notlike 'leadhive_recovery_*') { throw 'Migration retry unsafe' }
    }
    . (Join-Path $recoveryScripts 'Common.ps1')
    Check 'worker resume refuses failed or queued delivery records' {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_OUTBOUND_ENABLED' 'true'
        $global:G1MockReport = '{"email":1,"form":0,"campaign":0,"batch":0,"form_operation":0}'
        Denied { & (Join-Path $recoveryScripts 'Resume-LeadHive.ps1') } 'Unresolved delivery'
        Set-LeadHiveEnvironmentValue 'LEADHIVE_OUTBOUND_ENABLED' 'false'
    }
    $newPcRoot = Join-Path $testRoot 'new-pc-fixture'
    foreach ($file in Get-ChildItem -LiteralPath $recoveryRoot -File -Recurse) {
        $relative = $file.FullName.Substring($recoveryRoot.Length + 1)
        if ($relative -like '.env*' -or $relative -like 'backups\*') { continue }
        $destination = Join-Path $newPcRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
    $sourceMigrationBackup = Get-ChildItem (Join-Path $recoveryRoot 'backups') -Filter '*.dump' | Select-Object -First 1
    Check 'new dedicated PC import preserves instance and keys without starting worker' {
        $savedVolumes = $global:G1MockFakeVolumes
        $global:G1MockFakeVolumes = @{}
        try {
            $global:G1MockConfirmation = "SOURCE-OFFLINE-IMPORT-$('e' * 32)"
            $global:G1MockReport = '{"schema_revision":"test_head","counts":{"table":1},"fingerprints":{"table":"abc"}}'
            & (Join-Path $newPcRoot 'scripts/windows/Import-LeadHiveBackup.ps1') -BackupPath $sourceMigrationBackup.FullName
            $values = Read-LeadHiveEnvironment (Join-Path $newPcRoot '.env.local')
            if ($values['LEADHIVE_INSTANCE_ID'] -cne ('e' * 32) -or
                $values['SETTINGS_ENCRYPTION_KEY'] -cne 'test-only-encryption-key' -or
                $values['LEADHIVE_WORKER_PAUSED'] -ne 'true') { throw 'Unsafe new-PC import' }
        } finally { $global:G1MockFakeVolumes = $savedVolumes }
    }
    Check 'reviewed empty delivery state allows explicit worker resume' {
        $global:G1MockConfirmation = "RESUME-$('e' * 32)"
        $global:G1MockReport = '{"email":0,"form":0,"campaign":0,"batch":0,"form_operation":0}'
        & (Join-Path $recoveryScripts 'Resume-LeadHive.ps1')
        if ((Read-LeadHiveEnvironment $recoveryEnv)['LEADHIVE_WORKER_PAUSED'] -ne 'false') { throw 'Explicit resume failed' }
    }
    . (Join-Path $recoveryScripts 'Common.ps1')
    Check 'outbound stopped allows collection resume without changing pending deliveries' {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
        $global:G1MockReport = '{"email":1,"form":1,"campaign":1,"batch":1,"form_operation":1}'
        & (Join-Path $recoveryScripts 'Resume-LeadHive.ps1')
        $values = Read-LeadHiveEnvironment $recoveryEnv
        if ($values['LEADHIVE_OUTBOUND_ENABLED'] -ne 'false' -or $values['LEADHIVE_WORKER_PAUSED'] -ne 'false') { throw 'Collection resume enabled sending' }
    }
    Check 'explicit outbound stop persists false and keeps worker paused' {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_OUTBOUND_ENABLED' 'true'
        & (Join-Path $recoveryScripts 'Stop-LeadHiveOutbound.ps1')
        $values = Read-LeadHiveEnvironment $recoveryEnv
        if ($values['LEADHIVE_OUTBOUND_ENABLED'] -ne 'false' -or $values['LEADHIVE_WORKER_PAUSED'] -ne 'true' -or $values['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'false') { throw 'Outbound stop failed open' }
    }
    Check 'outbound stop cannot clear incomplete migration or restart application' {
        Set-LeadHiveEnvironmentValue 'LEADHIVE_MAINTENANCE_REQUIRED' 'true'
        & (Join-Path $recoveryScripts 'Stop-LeadHiveOutbound.ps1')
        if ((Read-LeadHiveEnvironment $recoveryEnv)['LEADHIVE_MAINTENANCE_REQUIRED'] -ne 'true') { throw 'Incomplete maintenance bypassed' }
    }
    $companyFixtures = @()
    Check 'three modeled company environments have distinct bindings and secrets' {
        foreach ($label in @('A', 'B', 'C')) {
            $folder = Join-Path $testRoot "company-$label"
            New-Item -ItemType Directory -Path $folder | Out-Null
            $id = [Guid]::NewGuid().ToString('N')
            $script:LeadHiveEnv = Join-Path $folder '.env.local'
            $password = "test-only-password-$label"
            $key = "test-only-key-$label"
            [IO.File]::WriteAllText($script:LeadHiveEnv, @"
LEADHIVE_INSTANCE_ID=$id
LEADHIVE_PROJECT_NAME=leadhive-$id
LEADHIVE_DATA_VOLUME=leadhive-$id-data
POSTGRES_PASSWORD=$password
SETTINGS_ENCRYPTION_KEY=$key
LEADHIVE_OUTBOUND_ENABLED=false
"@)
            Register-LeadHiveInstance -CreateNew
            $instance = Assert-LeadHiveInstance
            $backup = Join-Path $folder 'company-test.dump'
            [IO.File]::WriteAllText($backup, "mock business data for $label")
            Copy-Item -LiteralPath $script:LeadHiveEnv -Destination "$backup.env.local"
            Write-LeadHiveBackupIdentity $backup
            $script:companyFixtures += [pscustomobject]@{ Id=$id; Env=$script:LeadHiveEnv; Backup=$backup; Volume=$instance.Volume; Digest=$instance.SecurityDigest }
        }
        foreach ($property in @('Id','Volume','Digest')) {
            if (@($companyFixtures | Select-Object -ExpandProperty $property -Unique).Count -ne 3) { throw "Shared company $property" }
        }
    }
    Check 'all six cross-company backup swaps are rejected' {
        $rejected = 0
        foreach ($target in $companyFixtures) {
            $script:LeadHiveEnv = $target.Env
            Assert-LeadHiveBackupIdentity $target.Backup
            foreach ($source in $companyFixtures) {
                if ($source.Id -eq $target.Id) { continue }
                Denied { Assert-LeadHiveBackupIdentity $source.Backup } 'another deployment'
                $rejected++
            }
        }
        if ($rejected -ne 6) { throw 'Incomplete cross-company matrix' }
    }
    Check 'three company copied encryption keys cannot silently reopen databases' {
        for ($index = 0; $index -lt 3; $index++) {
            $target = $companyFixtures[$index]
            $script:LeadHiveEnv = $target.Env
            $original = [IO.File]::ReadAllText($target.Env)
            $foreignKey = "test-only-key-$(@('A','B','C')[($index + 1) % 3])"
            try {
                $changed = $original -replace '(?m)^SETTINGS_ENCRYPTION_KEY=.*$', "SETTINGS_ENCRYPTION_KEY=$foreignKey"
                [IO.File]::WriteAllText($target.Env, $changed)
                Denied { Assert-LeadHiveInstance } 'do not match'
            } finally { [IO.File]::WriteAllText($target.Env, $original) }
        }
    }
    Write-Output "Instance identity tests: $script:Passed passed. Docker and DB were mocked."
} finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name]) }
    # This is an explicitly generated, verified temporary test directory.
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolvedTest = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTest.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedTest) -like 'leadhive-identity-test-*') {
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force
    }
}
