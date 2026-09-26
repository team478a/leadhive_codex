. (Join-Path $PSScriptRoot "Common.ps1")

Assert-Docker
if (-not (Test-Path $script:LeadHiveEnv)) {
    throw "LeadHive is not installed. Run Install-LeadHive.cmd first."
}

Write-Step "Updating the LeadHive Codex Skill"
Install-LeadHiveCodexSkill

Write-Step "Building the updated application"
Invoke-LeadHiveCompose build --pull
Invoke-LeadHiveCompose up -d --wait db

Write-Step "Updating the database"
Invoke-LeadHiveCompose run --rm migrate

Write-Step "Restarting LeadHive"
Invoke-LeadHiveCompose up -d --force-recreate api worker web
$url = Wait-LeadHive
Start-LeadHiveBrowser $url
