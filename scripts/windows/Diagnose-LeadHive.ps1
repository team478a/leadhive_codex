. (Join-Path $PSScriptRoot "Common.ps1")

$diagnosticDirectory = Join-Path $script:LeadHiveRoot "diagnostics"
New-Item -ItemType Directory -Path $diagnosticDirectory -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path $diagnosticDirectory "leadhive-diagnostics-$timestamp.txt"
$lines = [Collections.Generic.List[string]]::new()

function Add-Diagnostic([string]$Title, [scriptblock]$Command) {
    $lines.Add("")
    $lines.Add("=== $Title ===")
    try {
        $result = & $Command 2>&1 | Out-String
        $lines.Add($result.Trim())
    } catch {
        $lines.Add("ERROR: $($_.Exception.Message)")
    }
}

$lines.Add("LeadHive diagnostics")
$lines.Add("Created: $([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz'))")
$lines.Add("Secrets and .env.local values are intentionally omitted.")

Add-Diagnostic "Windows" {
    $operatingSystem = Get-CimInstance Win32_OperatingSystem
    $computer = Get-CimInstance Win32_ComputerSystem
    "OS: $($operatingSystem.Caption) $($operatingSystem.Version)"
    "Architecture: $env:PROCESSOR_ARCHITECTURE"
    "MemoryGB: $([Math]::Round($computer.TotalPhysicalMemory / 1GB, 1))"
}
Add-Diagnostic "WSL" { & wsl.exe --status; & wsl.exe --list --verbose }
Add-Diagnostic "Docker executable" {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { "Found: $($command.Source)" } else { "Not installed" }
}
Add-Diagnostic "Docker version" { & docker version }
Add-Diagnostic "Docker Compose" { & docker compose version }
Add-Diagnostic "Docker engine" { & docker info }

Add-Diagnostic "Docker Desktop runtime paths" {
    foreach ($relativePath in @(
        "Docker\run\dockerInference",
        "docker-secrets-engine\engine.sock"
    )) {
        $path = Join-Path $env:LOCALAPPDATA $relativePath
        $state = if (Test-Path -LiteralPath $path) { "present" } else { "absent" }
        "LOCALAPPDATA\$relativePath : $state"
    }
}

Add-Diagnostic "LeadHive configuration" {
    "Environment file: $(if (Test-Path $script:LeadHiveEnv) { 'present' } else { 'absent' })"
    "Compose file: $(if (Test-Path $script:LeadHiveCompose) { 'present' } else { 'absent' })"
    if (Test-Path $script:LeadHiveEnv) {
        $names = Get-Content $script:LeadHiveEnv | ForEach-Object {
            if ($_ -match '^([A-Z0-9_]+)=') { $Matches[1] }
        }
        "Configured names: $($names -join ', ')"
        "Configured port: $(Get-LeadHivePort)"
    }
}

if ((Get-Command docker -ErrorAction SilentlyContinue) -and (Test-Path $script:LeadHiveEnv)) {
    Add-Diagnostic "LeadHive services" {
        Resolve-LeadHiveComposeProject
        & docker compose -p $script:LeadHiveProject --env-file $script:LeadHiveEnv `
            -f $script:LeadHiveCompose ps --all
    }
    Add-Diagnostic "LeadHive compose validation" {
        & docker compose --env-file $script:LeadHiveEnv -f $script:LeadHiveCompose config --quiet
        if ($LASTEXITCODE -eq 0) { "Valid" } else { "Invalid" }
    }
}

$lines.Add("")
$lines.Add("=== Safe recovery order ===")
$lines.Add("1. Quit Docker Desktop completely, start it again, and retry Start-LeadHive.cmd.")
$lines.Add("2. If Docker reports an inaccessible runtime path, restart Windows and retry.")
$lines.Add("3. Run Docker Desktop's built-in diagnostics if the engine still does not start.")
$lines.Add("4. Use Reset to factory defaults only after preserving LeadHive backups.")

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllLines($outputPath, $lines, $utf8WithoutBom)
Write-Host "Diagnostics created: $outputPath" -ForegroundColor Green
Write-Host "The report omits .env.local values and application data." -ForegroundColor Green
