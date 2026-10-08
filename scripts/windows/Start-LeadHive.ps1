. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed. Run Install-LeadHive.cmd first."
}

Write-Step "Starting LeadHive"
$values = Read-LeadHiveEnvironment
if ($values['LEADHIVE_MAINTENANCE_REQUIRED'] -eq 'true') {
    throw 'Maintenance failed or recovery is incomplete. Services will not restart automatically.'
}
Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', 'db')
Invoke-LeadHiveCompose run --rm migrate
if ($values['LEADHIVE_WORKER_PAUSED'] -eq 'true') {
    Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', 'api', 'web')
    Write-Host 'Worker remains paused. Use Resume-LeadHive.cmd after review.'
} else { Invoke-LeadHiveCompose -ComposeArguments @('up', '-d', 'api', 'worker', 'web') }
$url = Wait-LeadHive
Start-LeadHiveBrowser $url
