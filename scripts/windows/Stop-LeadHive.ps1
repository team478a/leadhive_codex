. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed."
}

Write-Step "Stopping LeadHive"
Invoke-LeadHiveCompose stop
Write-Host "LeadHive stopped. Your data is preserved." -ForegroundColor Green
