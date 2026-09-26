$ErrorActionPreference = "Stop"

$script:LeadHiveRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:LeadHiveEnv = Join-Path $script:LeadHiveRoot ".env.local"
$script:LeadHiveCompose = Join-Path $script:LeadHiveRoot "compose.local.yaml"
$script:LeadHiveProject = "leadhive-local"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is not installed. Install it from https://www.docker.com/products/docker-desktop/"
    }
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is not available. Update Docker Desktop."
    }
    & docker info | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running. Start Docker Desktop and try again."
    }
}

function Invoke-LeadHiveCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArguments)
    & docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv -f $script:LeadHiveCompose @ComposeArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed."
    }
}

function Get-LeadHivePort {
    if (-not (Test-Path $script:LeadHiveEnv)) { return 8787 }
    $line = Get-Content $script:LeadHiveEnv | Where-Object { $_ -match '^LEADHIVE_PORT=' } | Select-Object -First 1
    if (-not $line) { return 8787 }
    return [int]$line.Split('=', 2)[1]
}

function New-LeadHiveEnvironment {
    if (Test-Path $script:LeadHiveEnv) { return }

    $port = 8787
    while ($port -le 8797) {
        $used = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if (-not $used) { break }
        $port++
    }
    if ($port -gt 8797) {
        throw "No free local port was found between 8787 and 8797."
    }

    $passwordBytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($passwordBytes)
    $databasePassword = -join ($passwordBytes | ForEach-Object { $_.ToString('x2') })

    $keyBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($keyBytes)
    $encryptionKey = [Convert]::ToBase64String($keyBytes).Replace('+', '-').Replace('/', '_')

    $contents = @"
POSTGRES_PASSWORD=$databasePassword
SETTINGS_ENCRYPTION_KEY=$encryptionKey
LEADHIVE_PORT=$port
CORS_ORIGINS=http://localhost:$port,http://127.0.0.1:$port
PUBLIC_APP_URL=http://localhost:$port
"@
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($script:LeadHiveEnv, $contents, $utf8WithoutBom)
}

function Wait-LeadHive {
    $port = Get-LeadHivePort
    $healthUrl = "http://127.0.0.1:$port/api/health"
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
            if ($response.status -eq "ok" -and $response.database -eq "ok") {
                return "http://localhost:$port"
            }
        } catch {}
    } while ((Get-Date) -lt $deadline)
    throw "LeadHive did not become ready. Run docker compose logs to inspect the error."
}

function Start-LeadHiveBrowser([string]$Url) {
    Start-Process $Url
    Write-Host "LeadHive is ready: $Url" -ForegroundColor Green
}

function Install-LeadHiveCodexSkill {
    $source = Join-Path $script:LeadHiveRoot ".agents\skills\leadhive-form-submit"
    if (-not (Test-Path (Join-Path $source "SKILL.md") -PathType Leaf)) {
        Write-Host "Codex Skill was not included in this package." -ForegroundColor Yellow
        return
    }
    $skillRoot = Join-Path $HOME ".agents\skills"
    $destination = Join-Path $skillRoot "leadhive-form-submit"
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Copy-Item -Path (Join-Path $source "*") -Destination $destination -Recurse -Force
    Write-Host "Codex Skill installed: $destination" -ForegroundColor Green
}
