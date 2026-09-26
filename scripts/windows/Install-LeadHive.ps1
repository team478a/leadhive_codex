. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "DockerSetup.ps1")

Write-Host "LeadHive local installer" -ForegroundColor Green
Ensure-DockerDesktop

Write-Step "Creating local security settings"
New-LeadHiveEnvironment

Write-Step "Installing the LeadHive Codex Skill"
Install-LeadHiveCodexSkill

Write-Step "Building LeadHive (the first run can take several minutes)"
Invoke-LeadHiveCompose build --pull

Write-Step "Starting the database"
Invoke-LeadHiveCompose up -d --wait db

Write-Step "Updating the database"
Invoke-LeadHiveCompose run --rm migrate

Write-Step "Starting LeadHive"
Invoke-LeadHiveCompose up -d api worker web
$url = Wait-LeadHive

$userStatus = (& docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv -f $script:LeadHiveCompose exec -T api python -m app.cli --status).Trim()
if ($userStatus -eq "no-users") {
    Write-Step "Creating the first administrator"
    $email = Read-Host "Email address"
    Write-Host "Enter a password of at least 12 characters twice. Input is hidden."
    Invoke-LeadHiveCompose exec api python -m app.cli $email
}

Write-Step "Installation completed"
Start-LeadHiveBrowser $url
Write-Host "Keep the .env.local file and the Docker volume when moving or updating LeadHive."
Write-Host "If the LeadHive Form Submit skill is not visible, restart Codex once."
