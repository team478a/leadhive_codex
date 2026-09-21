. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed. Run Install-LeadHive.cmd first."
}

Write-Step "Starting LeadHive"
Invoke-LeadHiveCompose up -d db
Invoke-LeadHiveCompose run --rm migrate
Invoke-LeadHiveCompose up -d api worker web
$url = Wait-LeadHive
Start-LeadHiveBrowser $url
