. (Join-Path $PSScriptRoot 'Common.ps1')
Assert-Docker
$instance = Get-LeadHiveInstance
$lock = Enter-LeadHiveMaintenanceLock
try {
    $data = Get-LeadHiveVolume $instance.Volume
    if ($instance.Legacy -or -not $data -or
        $data.Labels.'work.leadhive.instance' -cne $instance.Id -or
        $data.Labels.'work.leadhive.security' -cne $instance.SecurityDigest) {
        throw 'Cannot verify partial registration. Keep the original files and request recovery support.'
    }
    if (Get-LeadHiveVolume $instance.Binding) { Assert-LeadHiveInstance | Out-Null; throw 'Identity is already registered; repair is unnecessary.' }
    if ((Read-Host "Type REPAIR-$($instance.Id) to complete registration without changing data or keys") -cne "REPAIR-$($instance.Id)") { throw 'Repair cancelled.' }
    Register-LeadHiveInstance -CreateNew
    Set-LeadHiveEnvironmentValue 'LEADHIVE_WORKER_PAUSED' 'true'
    Write-Host 'Identity repaired. Data and keys preserved; worker remains paused.'
} finally { $lock.ReleaseMutex(); $lock.Dispose() }
